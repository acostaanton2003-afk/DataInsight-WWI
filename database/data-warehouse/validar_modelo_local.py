"""Comprobaciones analíticas del diseño sobre CSV completos; nunca ejecuta el DDL."""

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'etl'))
from validar_raw import FIELD_LIMIT, batches, read_records

# tabla SQL local -> tabla fuente, columnas fuente/tipo. Sin atributos inferidos.
SOURCES = {
    'src_orders': ('Sales.Orders', [('order_id','OrderID','INTEGER'), ('customer_id','CustomerID','INTEGER'), ('order_date','OrderDate','TEXT'), ('backorder_order_id','BackorderOrderID','INTEGER')]),
    'src_invoices': ('Sales.Invoices', [('invoice_id','InvoiceID','INTEGER'), ('customer_id','CustomerID','INTEGER'), ('bill_to_customer_id','BillToCustomerID','INTEGER'), ('order_id','OrderID','INTEGER'), ('invoice_date','InvoiceDate','TEXT'), ('is_credit_note','IsCreditNote','INTEGER')]),
    'src_lines': ('Sales.InvoiceLines', [('invoice_line_id','InvoiceLineID','INTEGER'), ('invoice_id','InvoiceID','INTEGER'), ('stock_item_id','StockItemID','INTEGER'), ('package_type_id','PackageTypeID','INTEGER'), ('quantity','Quantity','INTEGER'), ('unit_price','UnitPrice','TEXT'), ('tax_amount','TaxAmount','TEXT'), ('extended_price','ExtendedPrice','TEXT')]),
    'src_customers': ('Sales.Customers', [('customer_id','CustomerID','INTEGER'), ('bill_to_customer_id','BillToCustomerID','INTEGER')]),
    'src_products': ('Warehouse.StockItems', [('stock_item_id','StockItemID','INTEGER')]),
}


def line_base(quantity, price):
    if quantity is None or price is None:
        return None
    with localcontext() as context:
        context.prec = 50
        return str(Decimal(quantity) * Decimal(price))


def monetary_invalid(quantity, price, tax, extended):
    if any(value is None for value in (quantity, price, tax, extended)):
        return 1
    with localcontext() as context:
        context.prec = 50
        return int(abs(Decimal(extended) - (Decimal(line_base(quantity, price)) + Decimal(tax))) > Decimal('0.01'))


class DecimalSum:
    def __init__(self):
        self.total = Decimal(0)
        self.incomplete = False
    def step(self, value):
        if value is None:
            self.incomplete = True
        else:
            with localcontext() as context:
                context.prec = 50
                self.total += Decimal(value)
    def finalize(self):
        return None if self.incomplete else format(self.total, 'f')


def analytical_connection():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.create_function('line_base', 2, line_base)
    connection.create_function('monetary_invalid', 4, monetary_invalid)
    connection.create_aggregate('decimal_sum', 1, DecimalSum)
    for table, (_, columns) in SOURCES.items():
        definition = ', '.join(f'{name} {kind}' for name, _, kind in columns)
        connection.execute(f'CREATE TABLE {table} ({definition})')
        # No UNIQUE: queremos detectar duplicados, no ocultarlos al importar.
        for name, _, kind in columns:
            if kind == 'INTEGER' and name.endswith('_id'):
                connection.execute(f'CREATE INDEX ix_{table}_{name} ON {table}({name})')
    return connection


def query_results(connection):
    sql = (Path(__file__).parent / '02_validacion_extraccion.sql').read_text(encoding='utf-8')
    parts = re.split(r'^-- name: ([a-z_]+)\s*$', sql, flags=re.MULTILINE)
    results = {}
    for index in range(1, len(parts), 2):
        results[parts[index]] = [dict(row) for row in connection.execute(parts[index + 1])]
    customers = results.pop('top_clientes_completo')
    customer_sum, month_sum = DecimalSum(), DecimalSum()
    for row in customers:
        customer_sum.step(row['ventas_sin_impuestos'])
    for row in results['meses']:
        month_sum.step(row['ventas_sin_impuestos'])
    results['conciliacion_agrupaciones'] = {
        'clientes': customer_sum.finalize(), 'meses': month_sum.finalize(),
        'lineas_meses': sum(row['lineas'] for row in results['meses']),
        'numero_meses': len(results['meses']),
    }
    results['top_clientes'] = sorted(customers, key=lambda row: (row['ventas_sin_impuestos'] is None, -Decimal(row['ventas_sin_impuestos']) if row['ventas_sin_impuestos'] is not None else Decimal(0), row['customer_id']))[:10]
    return results



def assess(results):
    grain = results['conservacion_grano']
    source = results['importes_originales'][0]
    joined = results['importes_enlazados_todos'][0]
    measures = ('lineas', 'ventas_sin_impuestos', 'impuestos', 'ventas_con_impuestos')
    return {
        'claves_unicas_y_no_nulas': all(r['claves_nulas'] == 0 and r['repeticiones'] == 0 for r in results['pk_integridad']),
        'relaciones_disponibles_sin_huerfanos': all((r['huerfanas'] or 0) == 0 and ('nullable' in r['relacion'] or (r['nulos'] or 0) == 0) for r in results['relaciones']),
        'conteo_facturas_reproducible_desde_lineas': results['cobertura_cabeceras'][0]['sin_lineas'] == 0 and results['ventas_enlazadas'][0]['facturas'] == results['cobertura_cabeceras'][0]['ordinarias'],
        'agrupaciones_conservadas': results['ventas_enlazadas'][0]['ventas_sin_impuestos'] is not None and results['conciliacion_agrupaciones']['clientes'] == results['conciliacion_agrupaciones']['meses'] == results['ventas_enlazadas'][0]['ventas_sin_impuestos'] and results['conciliacion_agrupaciones']['lineas_meses'] == results['ventas_enlazadas'][0]['lineas'],
        'grano_conservado': len({(r['filas'], r['claves']) for r in grain}) == 1 and all(r['filas'] == r['claves'] for r in grain),
        'importes_conservados_en_enlaces': all(source[key] is not None and source[key] == joined[key] for key in measures),
        'formula_monetaria_completa_y_en_tolerancia': source['diferencias_o_incompletas'] == 0,
    }
def verify(raw_dir):
    raw_dir = Path(raw_dir).resolve()
    manifest = json.loads((raw_dir / 'extraction_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('modo') != 'completo' or manifest.get('estado') != 'completado':
        raise ValueError('Se requiere una extracción completa y terminada, nunca una muestra.')
    schema = json.loads((ROOT / 'etl/esquema_raw.json').read_text(encoding='utf-8'))['tables']
    csv.field_size_limit(FIELD_LIMIT)
    provenance = {}
    with closing(analytical_connection()) as connection:
        for local_table, (source, selected) in SOURCES.items():
            path = raw_dir / (source + '.csv')
            with path.open('rb') as stream:
                before = hashlib.file_digest(stream, 'sha256').hexdigest()
            columns = [column['name'] for column in schema[source]]
            positions = [(columns.index(original), kind) for _, original, kind in selected]
            count = 0
            for batch in batches(read_records(path, columns)):
                values = []
                for _, _, row in batch:
                    if len(row) != len(columns):
                        raise ValueError(f'{source}: fila con estructura inválida')
                    picked = []
                    for position, kind in positions:
                        value = row[position]
                        if value is not None and kind == 'INTEGER':
                            value = int(value == 'True') if value in ('True','False') else int(value)
                        picked.append(value)
                    values.append(picked)
                placeholders = ','.join('?' for _ in selected)
                connection.executemany(f'INSERT INTO {local_table} VALUES ({placeholders})', values)
                count += len(values)
            entry = manifest['tablas'][source]
            if entry['estado'] != 'completado' or count != entry['filas_extraidas']:
                raise ValueError(f'{source}: conteo distinto del manifiesto')
            with path.open('rb') as stream:
                after = hashlib.file_digest(stream, 'sha256').hexdigest()
            if before != after:
                raise ValueError(f'{source}: cambió durante la comprobación')
            provenance[source] = {'filas': count, 'sha256': after}
        connection.commit()
        connection.execute('PRAGMA query_only=ON')
        results = query_results(connection)
    return {'raw_run_id': manifest['run_id'], 'raw_dir': str(raw_dir),
            'alcance': 'análisis en memoria de la extracción; no es una carga ni validación del DWH físico',
            'entradas': provenance, 'controles': assess(results), 'resultados': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info < (3, 13):
        parser.error('Se requiere Python 3.13+ para NULL de CSV.')
    try:
        report = verify(args.raw_dir)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0 if all(report['controles'].values()) else 2
    except (OSError, ValueError, KeyError, csv.Error, sqlite3.Error) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
