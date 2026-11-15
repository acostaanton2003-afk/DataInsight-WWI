"""Consultas analíticas SELECT sobre granos independientes del DWH."""
from psycopg.rows import dict_row

from backend.app.database import read_connection

KPIS_SQL = """
WITH ventas AS MATERIALIZED (
    SELECT COALESCE(SUM(ventas_sin_impuestos),0) AS ventas_sin_impuestos,
           COALESCE(SUM(tax_amount),0) AS impuestos,
           COALESCE(SUM(extended_price),0) AS total_facturado,
           COUNT(DISTINCT invoice_id) AS cantidad_facturas
    FROM dwh.fact_ventas WHERE is_credit_note=false
), pedidos AS MATERIALIZED (
    SELECT COUNT(*) AS cantidad_pedidos FROM dwh.fact_pedidos
), clientes AS MATERIALIZED (
    SELECT COUNT(*) AS cantidad_clientes FROM dwh.dim_cliente WHERE cliente_key<>0
)
SELECT ventas.*,pedidos.cantidad_pedidos,clientes.cantidad_clientes
FROM ventas CROSS JOIN pedidos CROSS JOIN clientes
"""
MONTHLY_SQL = """
SELECT d.anio,d.mes,COALESCE(SUM(v.ventas_sin_impuestos),0) AS importe,
       COUNT(DISTINCT v.invoice_id) AS cantidad_facturas
FROM dwh.fact_ventas v
LEFT JOIN dwh.dim_fecha d ON d.fecha_key=v.fecha_factura_key
WHERE v.is_credit_note=false
GROUP BY d.anio,d.mes
ORDER BY d.anio ASC NULLS LAST,d.mes ASC NULLS LAST
"""
PRODUCTS_SQL = """
SELECT v.producto_key,p.stock_item_id,
       COALESCE(p.stock_item_name,'Desconocido') AS stock_item_name,
       SUM(v.ventas_sin_impuestos) AS ventas_sin_impuestos
FROM dwh.fact_ventas v
LEFT JOIN dwh.dim_producto p ON p.producto_key=v.producto_key
WHERE v.is_credit_note=false
GROUP BY v.producto_key,p.stock_item_id,p.stock_item_name
ORDER BY ventas_sin_impuestos DESC,p.stock_item_id ASC NULLS LAST,v.producto_key ASC
LIMIT %s
"""
CUSTOMERS_SQL = """
SELECT v.cliente_key,c.customer_id,
       COALESCE(c.customer_name,'Desconocido') AS customer_name,
       SUM(v.ventas_sin_impuestos) AS ventas_sin_impuestos
FROM dwh.fact_ventas v
LEFT JOIN dwh.dim_cliente c ON c.cliente_key=v.cliente_key
WHERE v.is_credit_note=false
GROUP BY v.cliente_key,c.customer_id,c.customer_name
ORDER BY ventas_sin_impuestos DESC,c.customer_id ASC NULLS LAST,v.cliente_key ASC
LIMIT %s
"""


class AnalyticsRepository:
    def __init__(self,settings):
        self.settings=settings

    def _query(self,query,params=()):
        with read_connection(self.settings) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query,params)
                # Solo agregados acotados: 1 KPI, meses y hasta 50 puestos.
                rows=[]
                while batch := cursor.fetchmany(100):
                    rows.extend(batch)
                return rows

    def kpis(self):
        return self._query(KPIS_SQL)[0]

    def monthly(self):
        return self._query(MONTHLY_SQL)

    def products(self,limit):
        return self._query(PRODUCTS_SQL,(limit,))

    def customers(self,limit):
        return self._query(CUSTOMERS_SQL,(limit,))
