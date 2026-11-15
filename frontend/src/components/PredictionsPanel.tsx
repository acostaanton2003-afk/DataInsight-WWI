import {useId,useMemo} from 'react';
import type {Month} from '../lib/api';
import type {Resource} from '../lib/useResource';
import {compatibleHistory,type Predictions} from '../lib/predictions';
import {formatAmount,formatMetric} from '../lib/format';
import {predictionOption} from './predictionChart';
import {Chart} from './Chart';
import {SectionState} from './SectionState';

type Query<T>={state:Resource<T>;reload:()=>void};
const names={naive:'Último valor',moving_average_3:'Promedio móvil de 3 meses',ridge:'Regresión Ridge'};
function ForecastView({history,prediction}:{history:Month[];prediction:Predictions}) {
  const option=useMemo(()=>predictionOption(history,prediction),[history,prediction]);
  const tableHintId=useId();
  const {coverage,backtesting}=prediction;const [year,month]=coverage.observed_last.split('-').map(Number);
  return <><div className="forecast-metrics">
    <article><span>Modelo seleccionado</span><strong>{names[prediction.selected_model]}</strong><small>Selección fuera de muestra</small></article>
    <article><span>MAE de backtesting</span><strong>{formatMetric(backtesting.mae)}</strong><small>Error absoluto medio</small></article>
    <article><span>RMSE de backtesting</span><strong>{formatMetric(backtesting.rmse)}</strong><small>Raíz del error cuadrático medio</small></article>
    <article><span>sMAPE de backtesting</span><strong>{formatMetric(backtesting.smape)}%</strong><small>Error relativo simétrico</small></article>
  </div><p className="coverage-warning"><strong>Cobertura de {new Intl.DateTimeFormat('es-ES',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(Date.UTC(year,month-1,1)))} no certificada.</strong> El cierre fue declarado, no auditado. Facturación observada del {coverage.final_first_invoice_date} al {coverage.final_last_invoice_date} ({coverage.final_days_with_sales} días con ventas). Llegar al último día no demuestra que todas las ventas estén incluidas.</p>
    <div className="forecast-legend" aria-label="Leyenda"><span><i className="real-line"/>Ventas reales</span><span><i className="forecast-line"/>Pronóstico experimental</span><span><i className="forecast-band"/>Banda descriptiva</span></div>
    <Chart option={option} label="Ventas históricas y tres pronósticos experimentales con bandas descriptivas"/>
    <p className="forecast-note">{coverage.usable_months} meses utilizados; corte {coverage.complete_through}. Importes sin impuestos y sin moneda verificada. Las bandas no garantizan cobertura estadística; {prediction.uncertainty.samples_per_horizon} errores históricos por horizonte.</p>
    {coverage.excluded_months.length>0&&<p className="forecast-note">Meses observados excluidos del tramo histórico del gráfico: {coverage.excluded_months.join(', ')}.</p>}
    <p id={tableHintId} className="forecast-table-hint">Desplaza horizontalmente para ver las cuatro columnas.<span className="sr-only"> Usa las flechas izquierda y derecha cuando la tabla tenga el foco.</span></p>
    <div className="table-scroll forecast-table-scroll" role="region" aria-label="Tabla de pronósticos desplazable" aria-describedby={tableHintId} tabIndex={0}><table><caption className="sr-only">Pronósticos y bandas descriptivas exactas</caption><thead><tr><th scope="col">Mes estimado</th><th scope="col">Pronóstico</th><th scope="col">Inferior</th><th scope="col">Superior</th></tr></thead><tbody>{prediction.forecasts.map(row=><tr key={row.month}><td>{row.month}</td><td>{formatAmount(row.forecast)}</td><td>{formatAmount(row.lower)}</td><td>{formatAmount(row.upper)}</td></tr>)}</tbody></table></div></>;
}
export function PredictionsPanel({prediction,history}:{prediction:Query<Predictions>;history:Query<Month[]>}) {
  const combined=useMemo(()=>{
    if(prediction.state.status!=='success'||history.state.status!=='success')return null;
    try{return {data:compatibleHistory(history.state.data,prediction.state.data)};}catch{return {error:true};}
  },[prediction.state,history.state]);
  const retry=()=>{prediction.reload();if(history.state.status!=='success'||combined?.error)history.reload();};
  let content;
  if(prediction.state.status==='loading'||history.state.status==='loading')content=<SectionState kind="loading"/>;
  else if(prediction.state.status==='error'||history.state.status==='error')content=<div className="section-state error" role="alert"><strong>Predicciones no disponibles</strong><p>El artefacto puede estar ausente o ser inválido, o FastAPI no está disponible. No se muestran estimaciones de reemplazo.</p><button className="button subtle" onClick={retry}>Reintentar predicciones</button></div>;
  else if(history.state.data.length===0)content=<SectionState kind="empty"/>;
  else if(combined?.error)content=<div className="section-state error" role="alert"><strong>Las series no son compatibles</strong><p>El período histórico o las unidades no coinciden con el artefacto. Actualiza ambas consultas antes de combinarlas.</p><button className="button subtle" onClick={retry}>Reintentar predicciones</button></div>;
  else if(combined?.data)content=<ForecastView history={combined.data} prediction={prediction.state.data}/>;
  return <section className="panel predictions-panel" id="predicciones" aria-labelledby="predictions-title"><div className="panel-heading"><div><span className="section-index">04 / EXPERIMENTO</span><h2 id="predictions-title">Predicciones de ventas</h2><p>Histórico y horizonte de tres meses · ventas sin impuestos</p></div><span className="top-label">EXPERIMENTAL</span></div>
    <p className="experimental-warning" role="note">Pronóstico histórico experimental; no representa ventas actuales ni garantiza resultados futuros</p>{content}</section>;
}
