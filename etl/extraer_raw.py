"""Muestras técnicas de 100 filas por tabla hacia CSV RAW; solo lectura."""

import csv
import os
import struct
import sys
import tempfile
from contextlib import closing
from datetime import date, datetime, time
from pathlib import Path


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BATCH_SIZE = 25
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


def extraer_tabla(connection, query, destination):
    """Publicar un CSV completo por tabla; conservar el anterior ante un fallo."""
    temporary = None
    count = 0
    try:
        with closing(connection.cursor()) as cursor:
            cursor.arraysize = BATCH_SIZE
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
                    rows = cursor.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    for row in rows:
                        writer.writerow([valor_csv(value) for value in row])
                    count += len(rows)
            # Temporal y destino en el mismo directorio; archivo cerrado en Windows.
        os.replace(temporary, destination)
        temporary = None
        return count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    if sys.version_info < (3, 12):
        print("La extracción RAW requiere Python 3.12 o superior para CSV con NULL distinguibles.", file=sys.stderr)
        return 1
    try:
        import pyodbc
        from conexion_sqlserver import conectar, mensaje_error_sql
    except ImportError:
        print(
            "Falta pyodbc. Desde la raíz ejecuta: "
            r".\.venv\Scripts\python.exe -m pip install -r .\etl\requirements.txt",
            file=sys.stderr,
        )
        return 1

    try:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with closing(conectar()) as connection:
            # SQL_SS_UDT (-151), por ejemplo geography: conservar los bytes del driver.
            connection.add_output_converter(-151, lambda value: value)
            # SQL_TYPE_TIMESTAMP (93): evitar perder la séptima cifra de datetime2.
            connection.add_output_converter(93, timestamp_original)
            for table, filename, query in TABLES:
                destination = RAW_DIR / filename
                try:
                    count = extraer_tabla(connection, query, destination)
                except (pyodbc.Error, OSError, csv.Error, ValueError, struct.error) as error:
                    detail = mensaje_error_sql(error) if isinstance(error, pyodbc.Error) else str(error)
                    print(f"ERROR {table} -> {destination}: {detail}", file=sys.stderr)
                    print("Extracción detenida; las tablas anteriores pueden haberse publicado. "
                          "El destino de la tabla fallida no se reemplaza.", file=sys.stderr)
                    return 1
                print(f"OK {table}: {count} filas -> {destination}")
        print("Muestra RAW finalizada. No representa una extracción completa.")
        return 0
    except ValueError as error:
        print(f"ERROR de configuración: {error}", file=sys.stderr)
    except pyodbc.Error as error:
        print(f"ERROR: {mensaje_error_sql(error)}", file=sys.stderr)
    except OSError as error:
        print(f"ERROR de archivos RAW: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
