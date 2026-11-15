"""Comprueba localmente contrato DDL y tipos CSV READY, sin conectar PostgreSQL."""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / 'etl'))
from preparar_ready import COLUMNS
from validar_raw import FIELD_LIMIT, batches, read_records

TABLES = {'DimFecha':'dim_fecha','DimCliente':'dim_cliente','DimProducto':'dim_producto',
          'FactVentas':'fact_ventas','FactPedidos':'fact_pedidos'}
DDL = Path(__file__).with_name('03_creacion_tablas_dwh.sql')


def ddl_contract(sql=None):
    sql = DDL.read_text(encoding='utf-8') if sql is None else sql
    sql = re.sub(r'--[^\n]*','',sql)
    result = {}
    for entity,table in TABLES.items():
        match = re.search(r'CREATE TABLE dwh\.'+table+r'\s*\((.*?)\n\);',sql,re.DOTALL)
        if not match:
            raise ValueError(f'Falta tabla DDL: {table}')
        columns = []
        for line in match[1].splitlines():
            column = re.match(r'\s{4}([a-z_]+)\s+(bigint|integer|smallint|date|text|boolean|numeric\(\d+,\d+\))(.*)',line)
            if column:
                name,kind,options = column.groups()
                columns.append({'name':name,'type':kind,'not_null':'NOT NULL' in options or 'PRIMARY KEY' in options,
                                'identity':'AS IDENTITY' in options,
                                'generated':'GENERATED ALWAYS AS' in options and 'AS IDENTITY' not in options})
        if [c['name'] for c in columns] != COLUMNS[entity]:
            raise ValueError(f'{table}: columnas distintas de READY')
        result[entity] = columns
    return result


def check_value(value,column):
    if value is None:
        if column['not_null']:
            raise ValueError('NULL en columna NOT NULL')
        return
    kind = column['type']
    if kind in ('smallint','integer','bigint'):
        if not re.fullmatch(r'[+-]?[0-9]+',value):
            raise ValueError('entero inválido')
        bits = {'smallint':16,'integer':32,'bigint':64}[kind]
        if not -(2**(bits-1)) <= int(value) < 2**(bits-1):
            raise ValueError(f'fuera de rango {kind}')
    elif kind.startswith('numeric'):
        if not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?',value):
            raise ValueError('decimal no finito o inválido')
        precision,scale = map(int,re.findall(r'\d+',kind))
        whole,_,fraction = value.lstrip('+-').partition('.')
        if len(whole.lstrip('0')) > precision-scale or len(fraction)>scale or not Decimal(value).is_finite():
            raise ValueError('precisión/escala excedida; PostgreSQL podría redondear o fallar')
    elif kind == 'date':
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
            raise ValueError('date no ISO')
        date.fromisoformat(value)
    elif kind == 'boolean' and value not in ('true','false'):
        raise ValueError('boolean debe ser true/false en READY')
    elif kind == 'text' and '\x00' in value:
        raise ValueError('PostgreSQL text no admite byte nulo')


def write_projection(columns):
    """Contrato de futura escritura; no lee, transforma ni carga CSV."""
    return {'columnas_escritura':[c['name'] for c in columns if not c['generated']],
            'posiciones_csv_base_0':[i for i,c in enumerate(columns) if not c['generated']]}


def check_generated(entity,row):
    """READY materializa estos valores; PostgreSQL debe recalcularlos exactamente."""
    if entity == 'FactVentas':
        from decimal import localcontext
        if row['ventas_sin_impuestos'] is None:
            raise ValueError('ventas_sin_impuestos materializada no puede ser NULL')
        with localcontext() as context:
            context.prec = 50
            if Decimal(row['ventas_sin_impuestos']) != Decimal(row['quantity'])*Decimal(row['unit_price']):
                raise ValueError('ventas_sin_impuestos difiere de la expresion generada')
    elif entity == 'FactPedidos':
        if row['tiene_factura'] != ('true' if int(row['cantidad_facturas'])>0 else 'false'):
            raise ValueError('tiene_factura difiere de la expresion generada')

def inspect(ready_dir):
    ready_dir = Path(ready_dir).resolve()
    report = json.loads((ready_dir / 'reconciliacion.json').read_text(encoding='utf-8-sig'))
    if report.get('estado') != 'completado':
        raise ValueError('READY no completado')
    contract = ddl_contract()
    csv.field_size_limit(FIELD_LIMIT)
    results = {}
    for entity,columns in contract.items():
        path = ready_dir / (entity+'.csv')
        before = path.stat()
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream,'sha256').hexdigest()
        if sha != report['tablas'][entity]['sha256']:
            raise ValueError(f'{entity}: hash distinto de conciliación')
        count = 0
        for batch in batches(read_records(path,[c['name'] for c in columns])):
            for number,_,row in batch:
                if len(row) != len(columns):
                    raise ValueError(f'{entity}: número de columnas incorrecto')
                for value,column in zip(row,columns):
                    try:
                        check_value(value,column)
                    except ValueError as error:
                        raise ValueError(f'{entity}, registro {number}, {column["name"]}: {error}') from error
                check_generated(entity,dict(zip([c['name'] for c in columns],row)))
                count += 1
        after = path.stat()
        if (before.st_mtime_ns,before.st_size) != (after.st_mtime_ns,after.st_size):
            raise ValueError(f'{entity}: cambió durante la inspección')
        if count != report['tablas'][entity]['filas']:
            raise ValueError(f'{entity}: conteo distinto de conciliación')
        results[entity] = {'tabla':'dwh.'+TABLES[entity],'filas':count,'columnas':len(columns),'tipos_compatibles':True,
                           'columnas_generadas_excluir_de_carga':[c['name'] for c in columns if c['generated']]}
        results[entity].update(write_projection(columns))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready-dir',type=Path,required=True)
    args = parser.parse_args()
    if sys.version_info < (3,13):
        parser.error('Se requiere Python 3.13+ para CSV NULL')
    try:
        print(json.dumps(inspect(args.ready_dir),ensure_ascii=True,indent=2))
        return 0
    except (OSError,ValueError,KeyError,csv.Error) as error:
        print(f'ERROR: {error}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
