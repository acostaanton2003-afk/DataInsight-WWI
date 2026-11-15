"""Serie real pequeña, auditada y sin credenciales administrativas."""
import calendar
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd


class ForecastError(ValueError):
    pass


SOURCE_SQL = """
SELECT d.anio,d.mes,SUM(v.ventas_sin_impuestos) AS importe,
       COUNT(DISTINCT v.invoice_id) AS cantidad_facturas,
       MIN(d.fecha) AS primera_fecha,MAX(d.fecha) AS ultima_fecha,
       COUNT(DISTINCT d.fecha) AS dias_con_ventas
FROM dwh.fact_ventas v
LEFT JOIN dwh.dim_fecha d ON d.fecha_key=v.fecha_factura_key
WHERE v.is_credit_note=false
GROUP BY d.anio,d.mes ORDER BY d.anio,d.mes
"""


def read_months(settings=None):
    # Importación diferida: pruebas y modelos no necesitan red ni .env.
    from backend.app.config import load_settings
    from backend.app.database import read_connection, DatabaseReadError
    from psycopg.rows import dict_row
    try:
        settings = settings or load_settings().database
        with read_connection(settings) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(SOURCE_SQL)
                rows=[]
                while batch := cursor.fetchmany(64):
                    rows.extend(batch)
                return rows
    except (DatabaseReadError,ValueError):
        raise ForecastError('No se pudo leer la serie con el rol lector BACKEND_DB_*.') from None


def validate_series(rows,expected_months=41):
    if not rows or len(rows)!=expected_months:
        raise ForecastError('Cantidad de meses distinta de la referencia esperada.')
    records=[]; periods=[]
    for row in rows:
        try:
            year,month=row['anio'],row['mes']
            if type(year) is not int or type(month) is not int or not 1<=year<=9999 or not 1<=month<=12:
                raise ValueError
            period=pd.Period(f'{year:04d}-{month:02d}',freq='M')
            raw=row['importe']
            if not isinstance(raw,(str,Decimal)) or not re.fullmatch(r'-?\d+\.\d{2}',str(raw)):
                raise ValueError
            amount=Decimal(raw)
            if not amount.is_finite():raise ValueError
            first,last=row['primera_fecha'],row['ultima_fecha']
            if type(first) is not date or type(last) is not date or first>last:
                raise ValueError
            if (first.year,first.month)!=(year,month) or (last.year,last.month)!=(year,month):
                raise ValueError
            invoices,days=row['cantidad_facturas'],row['dias_con_ventas']
            if type(invoices) is not int or invoices<1 or type(days) is not int or not 1<=days<=calendar.monthrange(year,month)[1]:
                raise ValueError
        except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError):
            raise ForecastError('Fila mensual inválida: fecha, importe o cobertura.') from None
        periods.append(period)
        records.append(dict(mes=str(period),importe=amount,cantidad_facturas=invoices,
            primera_fecha=first.isoformat(),ultima_fecha=last.isoformat(),dias_con_ventas=days))
    if periods != list(pd.period_range(periods[0],periods[-1],freq='M')):
        raise ForecastError('La serie debe estar ordenada, sin duplicados ni huecos mensuales.')
    frame=pd.DataFrame(records,index=pd.PeriodIndex(periods,freq='M',name='periodo'))
    return frame


def select_complete(frame,complete_through=None,coverage_note=''):
    final=frame.index[-1]
    if complete_through is None:
        cutoff=final-1
        reason='Último mes excluido preventivamente: cierre no declarado.'
    else:
        if not re.fullmatch(r'\d{4}-\d{2}',complete_through) or not coverage_note.strip():
            raise ForecastError('Declarar --complete-through YYYY-MM y --coverage-note no vacía.')
        try:cutoff=pd.Period(complete_through,freq='M')
        except ValueError:raise ForecastError('Mes de cierre inválido.') from None
        if not frame.index[0]<=cutoff<=final:
            raise ForecastError('El cierre debe estar dentro de la serie observada.')
        reason=coverage_note.strip()
    if complete_through is not None and cutoff==final and frame.iloc[-1].ultima_fecha!=final.end_time.date().isoformat():
        raise ForecastError('Último mes posiblemente parcial: no tiene facturación hasta el cierre calendario. Excluirlo; no extrapolar ni completar automáticamente.')
    usable=frame.loc[:cutoff].copy()
    excluded=[str(p) for p in frame.index if p>cutoff]
    last=frame.iloc[-1]
    metadata=dict(observed_months=len(frame),usable_months=len(usable),excluded_months=excluded,
        complete_through=str(cutoff),coverage_note=reason,
        observed_first=str(frame.index[0]),observed_last=str(final),
        final_first_invoice_date=last.primera_fecha,final_last_invoice_date=last.ultima_fecha,
        final_days_with_sales=int(last.dias_con_ventas),
        final_calendar_end=final.end_time.date().isoformat(),
        final_has_invoice_on_calendar_end=last.ultima_fecha==final.end_time.date().isoformat(),
        limitation='Fechas de facturación no certifican completitud. Días sin ventas no se imputan; meses omitidos no se rellenan.')
    return usable,metadata


def input_hash(frame):
    rows=[{**row,'importe':str(row['importe'])} for row in frame.to_dict('records')]
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')).hexdigest()
