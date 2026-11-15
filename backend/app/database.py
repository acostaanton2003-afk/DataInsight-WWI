"""Conexiones breves de lectura. Sin conexion al importar ni al iniciar health."""
from contextlib import contextmanager

import psycopg

from backend.app.config import ReadOnlyDatabaseSettings

TABLES = ('dim_fecha','dim_cliente','dim_producto','fact_ventas','fact_pedidos')
REFERENCE_COUNTS = (1249,664,228,228265,73595)


class DatabaseReadError(RuntimeError):
    """Error publico sin detalles del controlador o credenciales."""


@contextmanager
def read_connection(settings: ReadOnlyDatabaseSettings, *, connect=None):
    settings.validate_for_connection()
    factory = connect or psycopg.connect
    try:
        with factory(host=settings.host,port=settings.port,dbname=settings.name,
                     user=settings.user,password=settings.password,sslmode=settings.sslmode,
                     connect_timeout=10,prepare_threshold=None,autocommit=False,
                     options='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=5000') as connection:
            connection.read_only = True
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname = current_user")
                role = cursor.fetchone()
                if not role or role[0] != 'wwi_backend_reader' or any(role[1:]):
                    raise DatabaseReadError('El rol efectivo no cumple el perfil lector.')
            yield connection
    except (psycopg.Error, DatabaseReadError):
        raise DatabaseReadError('No se pudo completar la consulta de lectura; revise configuracion, permisos y RLS.') from None


def probe(settings, *, connect=None):
    """Verifica visibilidad real; solo devuelve identidad y conteos, nunca filas."""
    from psycopg import sql
    with read_connection(settings,connect=connect) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_user, current_database()')
            user, database = cursor.fetchone()
            counts = {}
            for table in TABLES:
                cursor.execute('SELECT row_security_active(%s::regclass)', ('dwh.'+table,))
                if cursor.fetchone() != (True,):
                    raise DatabaseReadError('RLS no esta activo para el rol lector.')
                cursor.execute(sql.SQL('SELECT count(*) FROM dwh.{}').format(sql.Identifier(table)))
                counts[table] = cursor.fetchone()[0]
            if tuple(counts.values()) != REFERENCE_COUNTS:
                raise DatabaseReadError('Visibilidad incompleta o referencia de conteos desactualizada; revisar RLS y conciliacion.')
    return {'status':'ok','user':user,'database':database,'counts':counts}


def main():
    from backend.app.config import load_settings
    try:
        result = probe(load_settings().database)
    except (ValueError,DatabaseReadError):
        print('Conexion no verificada. Revise BACKEND_DB_*, SSL, permisos y politicas RLS; no se muestran detalles sensibles.')
        return 1
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
