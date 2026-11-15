"""Configuración compartida de SQL Server mediante variables de entorno."""

import os

import pyodbc


DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
ODBC_URL = "https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server"


def setting(name, default):
    value = os.environ.get(name, default).strip()
    if not value:
        raise ValueError(f"La variable {name} no puede estar vacía.")
    return value


def odbc_value(value):
    return "{" + value.replace("}", "}}") + "}"


def conectar():
    """Abrir conexión; quien llama es responsable de cerrarla."""
    available = pyodbc.drivers()
    supported = [driver for driver in DRIVERS if driver in available]
    if not supported:
        raise ValueError(
            "No hay ODBC Driver 17 ni 18 for SQL Server visible para este Python. "
            "Instala Microsoft ODBC Driver 18 para Windows compatible con tu Python. "
            f"Descarga oficial: {ODBC_URL}"
        )
    requested = os.environ.get("SQLSERVER_ODBC_DRIVER", "").strip()
    if requested and requested not in supported:
        raise ValueError(
            f"SQLSERVER_ODBC_DRIVER debe ser uno disponible: {', '.join(supported)}. "
            "Déjala vacía para selección automática."
        )
    driver = requested or supported[0]
    server = setting("SQLSERVER_HOST", r"ANTON\SQLEXPRESS")
    database = setting("SQLSERVER_DATABASE", "WideWorldImporters")
    encrypt = setting("SQLSERVER_ENCRYPT", "yes").lower()
    trust = setting("SQLSERVER_TRUST_SERVER_CERTIFICATE", "no").lower()
    if encrypt not in ("yes", "no") or trust not in ("yes", "no"):
        raise ValueError("ENCRYPT y TRUST_SERVER_CERTIFICATE deben valer yes o no.")
    connection_string = (
        f"DRIVER={odbc_value(driver)};SERVER={odbc_value(server)};"
        f"DATABASE={odbc_value(database)};Trusted_Connection=yes;"
        f"Encrypt={encrypt};TrustServerCertificate={trust};"
    )
    print(f"Controlador: {driver}")
    print(f"Destino: {server} / {database} (autenticación integrada de Windows)")
    connection = pyodbc.connect(connection_string, timeout=10, autocommit=True)
    try:
        connection.timeout = 30
    except Exception:
        connection.close()
        raise
    return connection


def mensaje_error_sql(error):
    state = str(error.args[0]) if error.args else "desconocido"
    return (
        f"Error SQL Server (SQLSTATE {state}). Revisa instancia, servicio, permisos "
        "de Windows y TLS. Consulta documentation/05_conexion_sqlserver.md."
    )
