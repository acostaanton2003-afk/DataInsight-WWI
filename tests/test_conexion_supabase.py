"""Configuración y errores de Supabase con archivo .env ficticio y driver simulado."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'etl'))
import probar_conexion_supabase as probe

PASSWORD = 'ficticio @:/#${TOKEN} backslash\\literal'


class FakeCursor:
    def __init__(self,connection):
        self.connection=connection
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def execute(self,sql,params=None):
        assert self.connection.read_only is True
        assert sql.lstrip().startswith('SELECT')
        self.connection.queries.append((sql,params))
        if self.connection.fail_query and len(self.connection.queries)==2:
            raise RuntimeError('driver secreto: '+PASSWORD)
    def fetchone(self):
        return ('tester','postgres',self.connection.version) if len(self.connection.queries)==1 else (self.connection.count,)


class FakeConnection:
    def __init__(self,count=5,version='PostgreSQL 17.6 compilación ficticia',fail_query=False,fail_close=False):
        self.count=count
        self.version=version
        self.fail_query=fail_query
        self.fail_close=fail_close
        self.read_only=None
        self.queries=[]
    def __enter__(self):
        return self
    def __exit__(self,*args):
        if self.fail_close:
            raise RuntimeError('error secreto al cerrar '+PASSWORD)
    def cursor(self):
        return FakeCursor(self)


class SupabaseConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'.env'
        self.values={'HOST':'pooler.example.invalid','PORT':'5432','NAME':'postgres','USER':'postgres.ficticio','PASSWORD':PASSWORD,'SSLMODE':'require'}
        self.persist()
    def persist(self,extra=''):
        self.path.write_text('SQLSERVER_HOST=servidor-ficticio\n'+'\n'.join("SUPABASE_DB_"+k+"='"+v+"'" for k,v in self.values.items())+'\n'+extra,encoding='utf-8-sig')
    def captured(self,**kwargs):
        stdout,stderr=io.StringIO(),io.StringIO()
        with redirect_stdout(stdout),redirect_stderr(stderr):
            code=probe.main(self.path,**kwargs)
        self.assertNotIn(PASSWORD,stdout.getvalue()+stderr.getvalue())
        self.assertNotIn(self.values['HOST'],stdout.getvalue()+stderr.getvalue())
        self.assertEqual(stderr.getvalue(),'')
        self.assertEqual(len(stdout.getvalue().splitlines()),4)
        return code,stdout.getvalue()

    def test_loads_root_file_without_changing_any_environment_variable(self):
        with patch.dict(os.environ,{'SQLSERVER_HOST':'previo','SUPABASE_DB_PASSWORD':'otro','TOKEN':'no interpolar'}):
            before=dict(os.environ)
            config=probe.load_configuration(self.path)
            self.assertEqual(config.password,PASSWORD)
            self.assertEqual(config.host,self.values['HOST'])
            self.assertEqual(dict(os.environ),before)
            self.assertNotIn(PASSWORD,repr(config))

    def test_separate_parameters_ssl_timeout_readonly_and_no_prepares(self):
        connection=FakeConnection()
        recorded={}
        def connect(**kwargs):
            recorded.update(kwargs)
            return connection
        code,output=self.captured(connect=connect)
        self.assertEqual(code,0)
        self.assertIn('conexion_correcta',output)
        self.assertIn('Usuario: tester',output)
        self.assertNotIn('compilación',output)
        self.assertEqual(recorded['password'],PASSWORD)
        self.assertEqual(recorded['connect_timeout'],10)
        self.assertEqual(recorded['sslmode'],'require')
        self.assertIsNone(recorded['prepare_threshold'])
        self.assertFalse(recorded['autocommit'])
        self.assertNotIn('conninfo',recorded)
        self.assertEqual(len(connection.queries),2)
        self.assertEqual(connection.queries[1][1],('dwh',list(probe.TABLES)))

    def test_missing_file_or_required_fields(self):
        self.path.unlink()
        with self.assertRaises(probe.ConfigurationError):
            probe.load_configuration(self.path)
        self.persist()
        self.values['PASSWORD']=''
        self.persist()
        code,output=self.captured(connect=lambda **kwargs:self.fail('No conectar con campos faltantes'))
        self.assertEqual(code,1)
        self.assertIn('configuracion_invalida',output)

    def test_rejects_invalid_ports(self):
        for value in ('0','65536','5432.0','puerto','５４３２'):
            with self.subTest(value=value):
                self.values['PORT']=value
                self.persist()
                with self.assertRaises(probe.ConfigurationError):
                    probe.load_configuration(self.path)

    def test_enforces_encryption_without_downgrade(self):
        for value in ('disable','allow','prefer',''):
            self.values['SSLMODE']=value
            self.persist()
            with self.assertRaises(probe.ConfigurationError):
                probe.load_configuration(self.path)
        for value in ('require','verify-ca','verify-full'):
            self.values['SSLMODE']=value
            self.persist()
            self.assertEqual(probe.load_configuration(self.path).sslmode,value)

    def test_rejects_url_in_host(self):
        self.values['HOST']='postgresql://user:secret@example.invalid/db'
        self.persist()
        with self.assertRaises(probe.ConfigurationError):
            probe.load_configuration(self.path)

    def test_driver_errors_never_print_exception_or_credentials(self):
        def connect(**kwargs):
            raise RuntimeError('postgresql://name:'+PASSWORD+'@host/database')
        code,output=self.captured(connect=connect)
        self.assertEqual(code,1)
        self.assertIn('conexion_fallida',output)
        self.assertNotIn('postgresql://',output)

    def test_query_errors_are_sanitized(self):
        code,output=self.captured(connect=lambda **kwargs:FakeConnection(fail_query=True))
        self.assertEqual(code,1)
        self.assertIn('consulta_fallida',output)
        self.assertIn('Base de datos: postgres',output)

    def test_close_errors_are_also_sanitized(self):
        code,output=self.captured(connect=lambda **kwargs:FakeConnection(fail_close=True))
        self.assertEqual(code,1)
        self.assertIn('consulta_fallida',output)

    def test_incomplete_tables_do_not_trigger_ddl(self):
        connection=FakeConnection(count=3)
        code,output=self.captured(connect=lambda **kwargs:connection)
        self.assertEqual(code,2)
        self.assertIn('conectado_tablas_incompletas',output)
        self.assertIn('Tablas encontradas: 3',output)
        self.assertEqual(len(connection.queries),2)

    def test_other_postgresql_version_is_reported_without_dumping_version(self):
        code,output=self.captured(connect=lambda **kwargs:FakeConnection(version='PostgreSQL 18.0 secreto-version'))
        self.assertEqual(code,2)
        self.assertIn('conectado_version_no_compatible',output)
        self.assertNotIn('secreto-version',output)

    def test_missing_dependency_has_safe_status(self):
        with patch.dict(sys.modules,{'psycopg':None}):
            code,output=self.captured()
        self.assertEqual(code,1)
        self.assertIn('dependencias_incompletas',output)

    def test_parser_warnings_cannot_add_lines_to_output(self):
        self.persist(extra='linea mal formada " secreta no imprimir\n')
        code,output=self.captured(connect=lambda **kwargs:FakeConnection())
        self.assertEqual(code,0)
        self.assertNotIn('formada',output)

    def test_control_characters_in_metadata_do_not_inject_log_lines(self):
        self.assertEqual(probe.safe_label('usuario\ncontrol\t'),'usuario?control?')


if __name__=='__main__':
    unittest.main()
