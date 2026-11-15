"""Prueba de solo lectura de Supabase PostgreSQL; no modifica datos ni esquemas."""

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / '.env'
TABLES = ('dim_fecha','dim_cliente','dim_producto','fact_ventas','fact_pedidos')
IDENTITY_SQL = 'SELECT CURRENT_USER, CURRENT_DATABASE(), VERSION();'
TABLES_SQL = '''SELECT COUNT(*) FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname=%s AND c.relname=ANY(%s) AND c.relkind IN ('r','p');'''
NAMES = ('HOST','PORT','NAME','USER','PASSWORD','SSLMODE')


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Configuration:
    host: str = field(repr=False)
    port: int = field(repr=False)
    dbname: str = field(repr=False)
    user: str = field(repr=False)
    password: str = field(repr=False)
    sslmode: str = field(repr=False)


def load_configuration(path=ENV_PATH):
    """Leer solo .env raíz, sin copiar valores a os.environ ni interpolar secretos."""
    from dotenv import dotenv_values
    path = Path(path)
    if not path.is_file():
        raise ConfigurationError('archivo_no_disponible')
    # python-dotenv puede avisar por líneas ajenas a esta configuración.
    # Silenciar su logger durante la lectura para mantener salida estrictamente segura.
    logger = logging.getLogger('dotenv.main')
    silent = lambda record: False
    logger.addFilter(silent)
    try:
        values = dotenv_values(path,encoding='utf-8-sig',interpolate=False)
    finally:
        logger.removeFilter(silent)
    selected = {name:values.get('SUPABASE_DB_'+name) for name in NAMES}
    if any(not isinstance(value,str) or value=='' for value in selected.values()):
        raise ConfigurationError('variables_incompletas')
    password = selected['PASSWORD']  # No strip ni interpolación: conservar caracteres.
    clean = {name:value.strip() for name,value in selected.items() if name!='PASSWORD'}
    if any(not value for value in clean.values()) or any('\x00' in value for value in selected.values()):
        raise ConfigurationError('variables_invalidas')
    if not clean['PORT'].isascii() or not clean['PORT'].isdigit() or not 1<=int(clean['PORT'])<=65535:
        raise ConfigurationError('puerto_invalido')
    if clean['SSLMODE'] not in ('require','verify-ca','verify-full'):
        raise ConfigurationError('ssl_obligatorio')
    if '://' in clean['HOST'] or '@' in clean['HOST'] or any(c.isspace() for c in clean['HOST']):
        raise ConfigurationError('host_invalido')
    return Configuration(clean['HOST'],int(clean['PORT']),clean['NAME'],clean['USER'],password,clean['SSLMODE'])


def safe_label(value):
    return re.sub(r'[\x00-\x1f\x7f]','?',str(value))


def open_connection(config,connect=None):
    """Conexión segura compartida; el llamador controla transacción y cierre."""
    if connect is None:
        import psycopg
        connect = psycopg.connect
    return connect(host=config.host,port=config.port,dbname=config.dbname,user=config.user,
                   password=config.password,sslmode=config.sslmode,connect_timeout=10,
                   prepare_threshold=None,autocommit=False)

def probe(config,connect):
    """Parámetros separados, SSL obligatorio y transacción explícitamente de lectura."""
    result = {'estado':'conexion_fallida','usuario':'no disponible','base':'no disponible','tablas':'no disponible'}
    try:
        with open_connection(config,connect) as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute(IDENTITY_SQL)
                user,database,version = cursor.fetchone()
                result.update(usuario=safe_label(user),base=safe_label(database))
                cursor.execute(TABLES_SQL,('dwh',list(TABLES)))
                count = int(cursor.fetchone()[0])
                result['tablas'] = count
                if not re.match(r'^PostgreSQL\s+17(?:\.|\s)',version):
                    result['estado'] = 'conectado_version_no_compatible'
                elif count!=len(TABLES):
                    result['estado'] = 'conectado_tablas_incompletas'
                else:
                    result['estado'] = 'conexion_correcta'
        return result,0 if result['estado']=='conexion_correcta' else 2
    except Exception:
        # Nunca imprimir str(error), repr(error), DSN, config, traceback ni VERSION().
        result['estado'] = 'consulta_fallida' if result['usuario']!='no disponible' else 'conexion_fallida'
        return result,1


def show(result):
    print(f"Estado: {result['estado']}")
    print(f"Usuario: {result['usuario']}")
    print(f"Base de datos: {result['base']}")
    print(f"Tablas encontradas: {result['tablas']}")


def main(env_path=ENV_PATH,connect=None):
    result = {'estado':'configuracion_invalida','usuario':'no disponible','base':'no disponible','tablas':'no disponible'}
    try:
        config = load_configuration(env_path)
        if connect is None:
            import psycopg
            connect = psycopg.connect
        result,code = probe(config,connect)
    except ImportError:
        result['estado'],code = 'dependencias_incompletas',1
    except Exception:
        # También protege errores de lectura/parser sin revelar contenido de .env.
        code = 1
    show(result)
    return code


if __name__ == '__main__':
    sys.exit(main())
