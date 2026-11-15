"""Extracción RAW en modos muestra/completo; solo lectura y lotes acotados."""

import argparse
import csv
import json
import os
import struct
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import date, datetime, time, timezone
from time import perf_counter
from pathlib import Path


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BATCH_SIZE = 500
# Lista cerrada: no se reciben nombres de tabla, claves ni SQL del usuario.
TABLES = (
    ("Sales.Invoices", "Sales.Invoices.csv",
     "SELECT TOP (100) * FROM Sales.Invoices ORDER BY InvoiceID;"),
    ("Sales.InvoiceLines", "Sales.InvoiceLines.csv",
     "SELECT TOP (100) * FROM Sales.InvoiceLines ORDER BY InvoiceLineID;"),
    ("Sales.Customers", "Sales.Customers.csv",
     "SELECT TOP (100) * FROM Sales.Customers ORDER BY CustomerID;"),
    ("Warehouse.StockItems", "Warehouse.StockItems.csv",
     "SELECT TOP (100) * FROM Warehouse.StockItems ORDER BY StockItemID;"),
    ("Sales.Orders", "Sales.Orders.csv",
     "SELECT TOP (100) * FROM Sales.Orders ORDER BY OrderID;"),
)


def timestamp_original(value):
    """SQL_TIMESTAMP_STRUCT: conservar fracciones sin truncarlas a microsegundos."""
    if value is None:
        return None
    year, month, day, hour, minute, second, nanos = struct.unpack("<6hI", value)
    return (
        f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"
        + (f".{nanos:09d}".rstrip("0") if nanos else "")
    )


def valor_csv(value):
    """Serialización técnica, sin reglas ni transformaciones de negocio."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "0x" + bytes(value).hex()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return value


def extraer_tabla(connection, query, destination, batch_size=BATCH_SIZE, expected=None, check_source=None, progress=None):
    """Publicar un CSV completo por tabla; conservar el anterior ante un fallo."""
    temporary = None
    count = 0
    try:
        with closing(connection.cursor()) as cursor:
            cursor.arraysize = batch_size
            cursor.execute(query)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="",
                dir=destination.parent, prefix=destination.name + ".", suffix=".tmp",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                # Python >= 3.12: NULL vacío sin comillas, texto vacío como "".
                writer = csv.writer(output, quoting=csv.QUOTE_NOTNULL)
                writer.writerow([column[0] for column in cursor.description])
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    for row in rows:
                        writer.writerow([valor_csv(value) for value in row])
                    count += len(rows)
                    if progress is not None:
                        progress(count)
            # Temporal y destino en el mismo directorio; archivo cerrado en Windows.
        if expected is not None and count != expected:
            raise ValueError(f'Conteo diferente: extraídas={count}, esperadas={expected}')
        if check_source is not None:
            check_source()
        os.replace(temporary, destination)
        temporary = None
        return count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)



def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('El lote debe ser un entero mayor que cero.')
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modo', choices=('muestra', 'completo'), default='muestra')
    parser.add_argument('--batch-size', type=positive_int, default=BATCH_SIZE, help='Filas por fetchmany (500 por defecto).')
    return parser.parse_args(argv)


def queries(table, mode):
    # Solo construir SQL desde la lista cerrada definida en este módulo.
    if mode not in ('muestra', 'completo'):
        raise ValueError('Modo no permitido')
    for allowed, _, sample in TABLES:
        if table == allowed:
            query = sample if mode == 'muestra' else sample.replace('TOP (100) ', '', 1)
            return query, f'SELECT COUNT_BIG(*) FROM {allowed};'
    raise ValueError('Tabla no permitida')


def source_count(connection, query):
    with closing(connection.cursor()) as cursor:
        cursor.execute(query)
        return int(cursor.fetchone()[0])


def save_manifest(path, manifest):
    temporary = path.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def error_detail(error):
    # Las excepciones ODBC pueden contener datos de conexión: conservar solo SQLSTATE.
    if error.args and isinstance(error.args[0], str) and len(error.args[0]) == 5:
        return f'{type(error).__name__}: SQLSTATE {error.args[0]}'
    if isinstance(error, (ValueError, OSError, csv.Error, struct.error)):
        return str(error)
    return type(error).__name__


def run_extraction(connection, mode='muestra', batch_size=BATCH_SIZE, raw_root=RAW_DIR):
    if mode not in ('muestra', 'completo') or batch_size <= 0:
        raise ValueError('Modo o tamaño de lote inválido')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    directory = Path(raw_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest_path = directory / 'extraction_manifest.json'
    manifest = {'run_id': run_id, 'modo': mode, 'batch_size': batch_size,
                'estado': 'en_proceso', 'inicio_utc': datetime.now(timezone.utc).isoformat(),
                'consistencia': 'READ COMMITTED por consulta; sin instantánea transaccional común', 'tablas': {}}
    save_manifest(manifest_path, manifest)
    print(f'RAW run_id={run_id} -> {directory}', flush=True)
    try:
        connection.add_output_converter(-151, lambda value: value)
        connection.add_output_converter(93, timestamp_original)
        for table, filename, _ in TABLES:
            started = perf_counter()
            result = {'filas_extraidas': 0, 'conteo_fuente_antes': None, 'conteo_fuente_despues': None,
                      'filas_esperadas': None, 'duracion_segundos': None, 'error': None,
                      'ruta': str(directory / filename), 'estado': 'en_proceso'}
            manifest['tablas'][table] = result
            try:
                query, count_query = queries(table, mode)
                before = source_count(connection, count_query)
                expected = min(100, before) if mode == 'muestra' else before
                result.update(conteo_fuente_antes=before, filas_esperadas=expected)
                def progress(count):
                    result['filas_extraidas'] = count
                def check_source():
                    after = source_count(connection, count_query)
                    result['conteo_fuente_despues'] = after
                    if before != after:
                        raise ValueError(f'La fuente cambió de conteo: antes={before}, después={after}')
                extraer_tabla(connection, query, directory / filename, batch_size,
                              expected=expected, check_source=check_source, progress=progress)
                result['estado'] = 'completado'
            except Exception as error:
                result['estado'] = 'fallido'
                result['error'] = error_detail(error)
                raise
            finally:
                result['duracion_segundos'] = round(perf_counter() - started, 3)
                print(f"{table}: filas={result['filas_extraidas']}, fuente={result['conteo_fuente_antes']}, "
                      f"duración={result['duracion_segundos']}s, error={result['error']} -> {result['ruta']}", flush=True)
                save_manifest(manifest_path, manifest)
        manifest['estado'] = 'completado'
    except Exception as error:
        manifest['estado'] = 'fallido'
        manifest['error'] = error_detail(error)
        raise
    finally:
        manifest['fin_utc'] = datetime.now(timezone.utc).isoformat()
        save_manifest(manifest_path, manifest)
    return manifest, directory


def main(argv=None):
    args = parse_args(argv)
    if sys.version_info < (3, 12):
        print('ERROR: se requiere Python 3.12+ para CSV con NULL distinguibles.', file=sys.stderr)
        return 1
    try:
        from conexion_sqlserver import conectar
    except ImportError:
        print(r'Falta pyodbc: .\.venv\Scripts\python.exe -m pip install -r .\etl\requirements.txt', file=sys.stderr)
        return 1
    try:
        with closing(conectar()) as connection:
            # Explicitar el criterio de lectura sin modificar datos ni opciones de la base.
            with closing(connection.cursor()) as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED;')
            _, directory = run_extraction(connection, args.modo, args.batch_size)
        print(f'Extracción {args.modo} completada: {directory}')
        return 0
    except Exception as error:
        print(f'ERROR de extracción: {error_detail(error)}. No validar una ejecución incompleta.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
