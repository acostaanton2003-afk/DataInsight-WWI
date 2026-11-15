"""Validación local RAW -> VALIDATED/cuarentena; sin modificar RAW ni SQL Server."""

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from itertools import islice
from pathlib import Path

from extraer_raw import TABLES

ROOT = Path(__file__).resolve().parents[1]
BATCH_SIZE = 25
TOLERANCE = Decimal('0.01')  # Provisional: no equivale a validar TaxRate.
FIELD_LIMIT = 16 * 1024 * 1024
LOCAL_TIMEZONE = timezone(timedelta(hours=-6), 'America/Tegucigalpa')
SUPPORTED = {'int', 'bit', 'decimal', 'nvarchar', 'date', 'datetime2', 'varbinary', 'geography'}
META = ['__raw_file', '__raw_record', '__raw_line', '__errors_json', '__raw_fields_json']
NUMBER = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?\Z')
INTEGER = re.compile(r'[+-]?[0-9]+\Z')


def batches(reader):
    while batch := list(islice(reader, BATCH_SIZE)):
        yield batch


def read_records(path, columns):
    """Número lógico (sin cabecera), línea física inicial y valores originales."""
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream, quoting=csv.QUOTE_NOTNULL, strict=True)
        if next(reader, None) != columns:
            raise ValueError(f'{path.name}: cabecera ausente o distinta del esquema local')
        record = 0
        while True:
            start_line = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                return
            except csv.Error as error:
                raise csv.Error(f'{path.name}: registro {record + 1}, línea {start_line}: {error}') from error
            record += 1
            yield record, start_line, row


def parse_value(value, column):
    """Interpretar para comprobar; nunca devolver estos valores al CSV de salida."""
    kind = column['type']
    if kind == 'int':
        if not INTEGER.fullmatch(value):
            raise ValueError('entero inválido')
        number = int(value)
        if not -(2**31) <= number < 2**31:
            raise ValueError('fuera del rango int de SQL Server')
        return number
    if kind == 'decimal':
        if not NUMBER.fullmatch(value):
            raise ValueError('decimal inválido; no se admiten NaN, infinito ni notación científica')
        integer, _, fraction = value.lstrip('+-').partition('.')
        if len(integer.lstrip('0')) > column['precision'] - column['scale'] or len(fraction) > column['scale']:
            raise ValueError('precisión/escala decimal excedida')
        return Decimal(value)
    if kind == 'bit':
        if value not in ('True', 'False', '0', '1'):
            raise ValueError('bit inválido')
        return value in ('True', '1')
    if kind == 'date':
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            raise ValueError('fecha ISO inválida')
        return date.fromisoformat(value)
    if kind == 'datetime2':
        match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]+))?', value)
        if not match or len(match[3] or '') > column['scale']:
            raise ValueError('datetime2 ISO o escala inválida')
        # Solo comprobar calendario y reloj: conservar fracción de siete dígitos en CSV.
        datetime.fromisoformat(match[1] + 'T' + match[2])
        return value
    if kind == 'nvarchar':
        if column['max_length'] != -1 and len(value.encode('utf-16-le')) > column['max_length']:
            raise ValueError('longitud nvarchar excedida')
        return value
    if kind in ('varbinary', 'geography'):
        if not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})*', value):
            raise ValueError('representación hexadecimal inválida')
        if kind == 'varbinary' and column['max_length'] != -1 and (len(value) - 2) // 2 > column['max_length']:
            raise ValueError('longitud binaria excedida')
        return value
    raise ValueError(f'tipo de esquema no soportado: {kind}')


def row_errors(table, row, schema, duplicate=False, today=None):
    errors, warnings, parsed = [], [], {}
    def error(rule, column, detail):
        errors.append({'rule': rule, 'column': column, 'detail': detail})
    if len(row) != len(schema):
        error('CSV_COLUMNAS', None, f'esperadas {len(schema)}, recibidas {len(row)}')
        return errors, warnings
    for value, column in zip(row, schema):
        name = column['name']
        if value is None:
            if column['primary_key']:
                error('PK_NULA', name, 'clave primaria NULL')
            elif not column['nullable']:
                error('OBLIGATORIO_NULO', name, 'columna NOT NULL')
            continue
        try:
            parsed[name] = parse_value(value, column)
        except (ValueError, ArithmeticError) as problem:
            rule = 'FECHA_INVALIDA' if column['type'] in ('date', 'datetime2') else 'TIPO_INVALIDO'
            error(rule, name, str(problem))
    if duplicate:
        error('PK_DUPLICADA', next(c['name'] for c in schema if c['primary_key']), 'todas las apariciones se rechazan')
    if table == 'Sales.InvoiceLines':
        monetary = ('Quantity', 'UnitPrice', 'TaxAmount', 'ExtendedPrice')
        missing = [name for name in monetary if row[[c['name'] for c in schema].index(name)] is None]
        if missing:
            error('MONETARIO_INCOMPLETO', ','.join(missing), 'no se puede comprobar la fórmula; no sustituir NULL por cero')
        elif all(name in parsed for name in monetary):
            with localcontext() as context:
                context.prec = 50
                difference = abs(parsed['ExtendedPrice'] - (parsed['Quantity'] * parsed['UnitPrice'] + parsed['TaxAmount']))
            if difference > TOLERANCE:
                error('DIFERENCIA_MONETARIA', 'ExtendedPrice', f'diferencia absoluta {difference} > {TOLERANCE} provisional')
    # Q06: perfilar, no inventar políticas de signo para créditos o gratuidades.
    for name in ('Quantity', 'QuantityPerOuter', 'UnitPrice', 'RecommendedRetailPrice', 'TaxAmount', 'ExtendedPrice', 'LineProfit'):
        if name in parsed and isinstance(parsed[name], (int, Decimal)):
            if parsed[name] < 0:
                warnings.append(f'{name}:NEGATIVO')
            elif parsed[name] == 0:
                warnings.append(f'{name}:CERO')
    for name in ('OrderDate', 'InvoiceDate'):
        if name in parsed and parsed[name] > (today or datetime.now(LOCAL_TIMEZONE).date()):
            warnings.append(f'{name}:FECHA_FUTURA')
    return errors, warnings


def validate_table(table, source, schema, valid_path, rejected_path, index_path):
    columns = [column['name'] for column in schema]
    pk = next(i for i, column in enumerate(schema) if column['primary_key'])
    report = {'leidas': 0, 'validas': 0, 'rechazadas': 0, 'errores': {}, 'advertencias': {}}
    errors_count, warnings_count = Counter(), Counter()
    with closing(sqlite3.connect(index_path)) as index:
        index.execute('PRAGMA cache_size = -2048')  # Caché de 2 MiB, claves en disco.
        index.execute('CREATE TABLE claves (valor INTEGER PRIMARY KEY, veces INTEGER NOT NULL)')
        for batch in batches(read_records(source, columns)):
            for _, _, row in batch:
                if len(row) == len(columns) and row[pk] is not None:
                    try:
                        key = parse_value(row[pk], schema[pk])
                    except (ValueError, ArithmeticError):
                        continue
                    index.execute('INSERT INTO claves VALUES (?,1) ON CONFLICT(valor) DO UPDATE SET veces=veces+1', (key,))
            index.commit()
        with valid_path.open('w', encoding='utf-8-sig', newline='') as good, rejected_path.open('w', encoding='utf-8-sig', newline='') as bad:
            valid_writer = csv.writer(good, quoting=csv.QUOTE_NOTNULL)
            bad_writer = csv.writer(bad, quoting=csv.QUOTE_NOTNULL)
            valid_writer.writerow(columns)
            bad_writer.writerow(columns + META)
            today = datetime.now(LOCAL_TIMEZONE).date()
            for batch in batches(read_records(source, columns)):
                for record, line, row in batch:
                    duplicate = False
                    if len(row) == len(columns) and row[pk] is not None:
                        try:
                            key = parse_value(row[pk], schema[pk])
                            duplicate = index.execute('SELECT veces FROM claves WHERE valor=?', (key,)).fetchone()[0] > 1
                        except (ValueError, ArithmeticError):
                            pass
                    errors, warnings = row_errors(table, row, schema, duplicate, today)
                    report['leidas'] += 1
                    warnings_count.update(warnings)
                    if errors:
                        report['rechazadas'] += 1
                        # Una fila por rechazo; cada regla cuenta como máximo una vez por fila.
                        errors_count.update({item['rule'] for item in errors})
                        padded = (row + [None] * len(columns))[:len(columns)]
                        bad_writer.writerow(padded + [source.name, record, line, json.dumps(errors, ensure_ascii=False), json.dumps(row, ensure_ascii=False)])
                    else:
                        report['validas'] += 1
                        valid_writer.writerow(row)
    report['errores'] = dict(sorted(errors_count.items()))
    report['advertencias'] = dict(sorted(warnings_count.items()))
    report['balance_correcto'] = report['validas'] + report['rechazadas'] == report['leidas']
    if not report['balance_correcto']:
        raise RuntimeError(f'{table}: balance de filas incorrecto')
    return report


def load_schema():
    with (ROOT / 'etl' / 'esquema_raw.json').open(encoding='utf-8') as stream:
        metadata = json.load(stream)
    for table, _, _ in TABLES:
        schema = metadata['tables'][table]
        if sum(bool(c['primary_key']) for c in schema) != 1 or any(c['type'] not in SUPPORTED for c in schema):
            raise ValueError(f'{table}: esquema no soportado')
    return metadata


def run_validation(data_dir=ROOT / 'data'):
    csv.field_size_limit(FIELD_LIMIT)
    metadata = load_schema()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    report = {'run_id': run_id, 'estado': 'completado', 'tolerancia_provisional': str(TOLERANCE),
              'fecha_evaluacion_local': datetime.now(LOCAL_TIMEZONE).date().isoformat(),
              'zona_horaria': 'America/Tegucigalpa (UTC-06:00)',
              'esquema_capturado_utc': metadata['captured_at_utc'],
              'claves_foraneas': 'NO_EVALUADAS: muestras independientes; definidas en etl/esquema_raw.json', 'tablas': {}}
    published = []
    with tempfile.TemporaryDirectory(prefix='.validacion-', dir=data_dir) as temporary:
        stage = Path(temporary)
        for area in ('snapshot', 'validated', 'quarantine'):
            (stage / area).mkdir()
        for table, filename, _ in TABLES:
            original = data_dir / 'raw' / filename
            snapshot = stage / 'snapshot' / filename
            before = original.stat()
            shutil.copyfile(original, snapshot)
            after = original.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f'{filename}: RAW cambió durante la copia; repetir ejecución')
            with snapshot.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result = validate_table(table, snapshot, metadata['tables'][table],
                                    stage / 'validated' / filename, stage / 'quarantine' / filename,
                                    stage / (table + '.sqlite'))
            result['raw_sha256'] = digest
            result['raw_file'] = str(original)
            result['validated_file'] = str(data_dir / 'validated' / run_id / filename)
            result['quarantine_file'] = str(data_dir / 'quarantine' / run_id / filename)
            report['tablas'][table] = result
        report_file = stage / 'quality.json'
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        # Publicar solo después de procesar las cinco tablas. El reporte se publica al final.
        try:
            for area in ('validated', 'quarantine'):
                parent = data_dir / area
                parent.mkdir(exist_ok=True)
                destination = parent / run_id
                os.replace(stage / area, destination)
                published.append(destination)
            report_dir = data_dir / 'reports'
            report_dir.mkdir(exist_ok=True)
            destination = report_dir / (run_id + '.json')
            os.replace(report_file, destination)
        except OSError:
            for folder in reversed(published):
                # Eliminar solo directorios de esta ejecución dentro de las zonas previstas.
                if folder.parent in (data_dir / 'validated', data_dir / 'quarantine') and folder.name == run_id:
                    shutil.rmtree(folder)
            raise
    return report, destination


def main():
    if sys.version_info < (3, 13):
        print('ERROR: se requiere Python 3.13+ para leer NULL con QUOTE_NOTNULL.', file=sys.stderr)
        return 1
    try:
        report, path = run_validation()
        for table, result in report['tablas'].items():
            print(f"{table}: leídas={result['leidas']}, válidas={result['validas']}, rechazadas={result['rechazadas']}, balance={result['balance_correcto']}")
            print(f"  Errores: {json.dumps(result['errores'], ensure_ascii=True)}")
            print(f"  Advertencias: {json.dumps(result['advertencias'], ensure_ascii=True)}")
        print(f'Reporte: {path}')
        return 2 if any(r['rechazadas'] for r in report['tablas'].values()) else 0
    except (OSError, UnicodeError, csv.Error, ValueError, sqlite3.Error, RuntimeError) as error:
        print(f'ERROR de validación: {error}. No se publica un reporte de ejecución completa.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
