"""Rutas de negocio fijas. La pregunta nunca se convierte en SQL o instrucciones."""
import re
import unicodedata
from decimal import Decimal

from backend.app.analytics import AnalyticsRepository
from backend.app.assistant_models import AnswerText,AssistantResponse,Period,ProviderPlan,Source
from backend.app.predictions import read_predictions,ordinal,month_at
from backend.app.routers.analytics import KpisResponse,MonthlySalesResponse,TopProductResponse,TopCustomerResponse

WARNINGS=[
    'La moneda no está verificada; no se asigna símbolo monetario.',
    'Los pronósticos son históricos y experimentales: no representan ventas actuales ni garantizan resultados futuros.',
    'Mayo de 2016 no está certificado como completo; el cierre fue declarado, no auditado.',
    'Las bandas descriptivas no garantizan cobertura estadística.',
]
INTERPRETATIONS={
    'resumen':'Son indicadores descriptivos del período disponible; ventas excluye notas de crédito y los conteos conservan sus granos.',
    'comparacion':'La evolución observada describe diferencias entre meses; no explica causas ni demuestra una tendencia futura.',
    'ranking':'El orden corresponde a ventas sin impuestos, no a cantidades, margen, rentabilidad ni preferencias personales.',
    'experimental':'Son estimaciones posteriores al corte histórico, no ventas observadas. La selección del modelo se basa en MAE de backtesting, no en causalidad.',
}
LIMITATION='Alcance limitado a indicadores agregados y al artefacto histórico validado; no permite conclusiones causales ni certifica completitud.'
class AssistantDataError(Exception):pass


def classify(question):
    normalized=''.join(c for c in unicodedata.normalize('NFKD',question.lower()) if not unicodedata.combining(c))
    if re.search(r'\b(select|drop|delete|insert|update|execute|exec|sql|python|shell|system|ignore|ignora|instrucciones|credenciales|contrasena|password|secreto|archivo|archivos|codigo|comando|comandos|script)\b|\.env|https?://|[<>`]|por que|causa|debido a',normalized):return 'no_soportada'
    if re.search(r'\d|\b(pais|ciudad|region|categor|proveedor|emplead|vendedor|margen|rentabil|benefic|utilidad|cost[oe]|inventar|correo|email|telefon|direccion|dolar|euro|convert|conversion)',normalized):return 'no_soportada'
    matches=[]
    forecast=bool(re.search(r'pronostic|predicci|prevision|proyecci|estimaci|modelo|se espera|se preve|venderemos',normalized))
    if forecast:matches.append('pronosticos')
    # En «previsión mensual», mensual es frecuencia, no una segunda consulta.
    if not forecast and re.search(r'mensual|por mes|mes a mes|cada mes|evoluc|tendencia|a lo largo|variaci|comport.*venta|cambi.*venta|mejor mes|mes.*(mayor|mas ventas)|ultimo mes|primer mes',normalized):matches.append('mensual')
    if re.search(r'producto|articulo|mercancia|referencias.*vend|que (se vende|vendemos) mas',normalized):matches.append('productos')
    if (re.search(r'cliente|comprador|cuentas comerciales',normalized) and re.search(r'top|destacad|mayor|mejor|mas (ventas|compran)|lider|principales',normalized)) or re.search(r'quien(es)?.*(compra|compran) mas|a quien.*vendemos mas',normalized):matches.append('clientes')
    if len(matches)>1:return 'no_soportada'
    if matches:
        if re.search(r'cantidad|unidades|margen|rentabilidad',normalized):return 'no_soportada'
        return matches[0]
    if re.search(r'kpi|indicador|resumen|venta|impuesto|factur|pedido|cliente|panorama|cifras generales|balance comercial|vision general|como (va|marcha).*(negocio|empresa)',normalized):return 'kpis'
    return 'no_soportada'


def amount(value):return format(Decimal(value),'.2f')


def collect(topic,repo,forecast_path):
    rows=[MonthlySalesResponse.model_validate(r) for r in repo.monthly()]
    if not rows or len(rows)>600 or any(r.anio is None or r.mes is None for r in rows):raise AssistantDataError
    months=[f'{r.anio:04d}-{r.mes:02d}' for r in rows]
    if [ordinal(m) for m in months]!=list(range(ordinal(months[0]),ordinal(months[-1])+1)):raise AssistantDataError
    period=Period(inicio=months[0],fin=months[-1]);sources=[Source(nombre='Ventas mensuales',ruta='/api/v1/ventas/por-mes')]
    facts=[];safe=[]
    def fact(text,values):
        identifier=f'f{len(facts)+1}';facts.append((identifier,text));safe.append(dict(id=identifier,aggregates=values))
    interpretation='resumen'
    if topic=='kpis':
        k=KpisResponse.model_validate(repo.kpis());sources.append(Source(nombre='Indicadores globales',ruta='/api/v1/kpis'))
        fact(f'Ventas sin impuestos: {amount(k.ventas_sin_impuestos)}; impuestos: {amount(k.impuestos)}; total facturado: {amount(k.total_facturado)}.',dict(base=amount(k.ventas_sin_impuestos),impuestos=amount(k.impuestos),total=amount(k.total_facturado)))
        fact(f'Facturas distintas con líneas: {k.cantidad_facturas}; pedidos: {k.cantidad_pedidos}; clientes registrados, sin desconocido: {k.cantidad_clientes}.',dict(facturas=k.cantidad_facturas,pedidos=k.cantidad_pedidos,clientes=k.cantidad_clientes))
    elif topic=='mensual':
        interpretation='comparacion';maximum=max(range(len(rows)),key=lambda i:rows[i].importe)
        fact(f'Serie de {len(rows)} meses: {period.inicio} a {period.fin}.',dict(meses=len(rows)))
        fact(f'Primer mes {months[0]}: {amount(rows[0].importe)}; último mes {months[-1]}: {amount(rows[-1].importe)}.',dict(primero=amount(rows[0].importe),ultimo=amount(rows[-1].importe)))
        fact(f'Mes con mayor venta sin impuestos: {months[maximum]}, con {amount(rows[maximum].importe)}.',dict(mes=months[maximum],importe=amount(rows[maximum].importe)))
    elif topic in ('productos','clientes'):
        interpretation='ranking';product=topic=='productos'
        ranking=[(TopProductResponse if product else TopCustomerResponse).model_validate(r) for r in (repo.products(3) if product else repo.customers(3))]
        if not ranking:raise AssistantDataError
        sources.append(Source(nombre='Top productos' if product else 'Top clientes comerciales',ruta='/api/v1/productos/top' if product else '/api/v1/clientes/top'))
        for rank,row in enumerate(ranking,1):
            identity=row.stock_item_id if product else row.customer_id
            fact(f'Puesto {rank}: {"StockItemID" if product else "CustomerID"} {identity if identity is not None else "desconocido"}, ventas sin impuestos {amount(row.ventas_sin_impuestos)}.',dict(puesto=rank,ventas=amount(row.ventas_sin_impuestos)))
    elif topic=='pronosticos':
        interpretation='experimental';prediction=read_predictions(forecast_path);coverage=prediction.coverage
        if (period.inicio,period.fin,len(rows))!=(coverage.observed_first,coverage.observed_last,coverage.observed_months):raise AssistantDataError
        period=Period(inicio=coverage.observed_first,fin=coverage.complete_through)
        sources.append(Source(nombre='Predicciones históricas validadas',ruta='/api/v1/predicciones/ventas'))
        m=prediction.backtesting
        fact(f'Modelo seleccionado: {prediction.selected_model}; MAE {m.mae}, RMSE {m.rmse}, sMAPE {m.smape}%.',dict(modelo=prediction.selected_model,mae=str(m.mae),rmse=str(m.rmse),smape=str(m.smape)))
        for row in prediction.forecasts:
            fact(f'{row.month}: estimación {row.forecast}; banda descriptiva {row.lower} a {row.upper}.',dict(mes=row.month,estimacion=row.forecast,inferior=row.lower,superior=row.upper))
        fact(f'Cobertura observada del último mes: {coverage.final_first_invoice_date} a {coverage.final_last_invoice_date}; {coverage.final_days_with_sales} días con ventas. Completitud no certificada.',dict(primera_fecha=str(coverage.final_first_invoice_date),ultima_fecha=str(coverage.final_last_invoice_date),dias=coverage.final_days_with_sales))
    return facts,safe,period,sources,interpretation


def answer(question,repo,forecast_path,provider=None):
    topic=classify(question)
    if topic=='no_soportada':
        return AssistantResponse(soportada=False,tema=topic,modo='reglas',respuesta=AnswerText(hechos=[],interpretacion='Puedo consultar KPI, evolución mensual, productos destacados, clientes destacados o pronósticos históricos. Formula una pregunta de un solo tema, sin filtros de fecha o dimensiones nuevas ni tamaño de ranking configurable; no ejecuto instrucciones ni explico causas.',limitaciones=[LIMITATION]),fuentes=[],periodo=None,advertencias=list(WARNINGS))
    facts,safe,period,sources,interpretation=collect(topic,repo,forecast_path)
    mode='reglas';model_name=None;warnings=list(WARNINGS)
    identifiers=[identifier for identifier,_ in facts]
    if provider is not None:
        # Nunca se envían pregunta libre, nombres, IDs, filas, rutas o credenciales.
        context=dict(topic=topic,periodo=period.model_dump(),facts=safe,interpretation=interpretation,warnings=list(WARNINGS))
        try:
            plan=ProviderPlan.model_validate(provider.generate(context))
            if len(plan.fact_ids)!=len(identifiers) or set(plan.fact_ids)!=set(identifiers) or plan.interpretation!=interpretation:raise ValueError
            ordered=dict(facts);facts=[(key,ordered[key]) for key in plan.fact_ids];mode='llm_local_restringido'
            candidate_name=getattr(provider,'model_name',None)
            model_name=candidate_name if isinstance(candidate_name,str) and len(candidate_name)<=80 else None
        except Exception:
            warnings.append('Ollama no está disponible o su salida no superó la validación dentro del límite; se usa la respuesta local basada en reglas.')
    return AssistantResponse(soportada=True,tema=topic,modo=mode,proveedor='ollama' if mode=='llm_local_restringido' else 'local',modelo=model_name,
        respuesta=AnswerText(hechos=[text for _,text in facts],interpretacion=INTERPRETATIONS[interpretation],limitaciones=[LIMITATION]),
        fuentes=sources,periodo=period,advertencias=warnings)
