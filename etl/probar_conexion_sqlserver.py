"""Prueba de lectura de WideWorldImporters con autenticación de Windows."""

import sys
from contextlib import closing


def main():
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
        with closing(conectar()) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT @@VERSION;")
                version = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT_BIG(*) FROM Sales.Invoices;")
                invoices = cursor.fetchone()[0]
        print("Conexión verificada.")
        print(f"Versión de SQL Server:\n{version}")
        print(f"COUNT_BIG(*) de Sales.Invoices: {invoices}")
        return 0
    except ValueError as error:
        print(f"Configuración: {error}", file=sys.stderr)
        return 1
    except pyodbc.Error as error:
        print(mensaje_error_sql(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
