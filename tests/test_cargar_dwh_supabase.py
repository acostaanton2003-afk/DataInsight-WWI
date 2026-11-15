"""Carga DWH con READY ficticio y destino simulado, sin conexiones reales."""

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'etl'))
import cargar_dwh_supabase as loader
import test_preparar_ready as fixtures


class FakeRemote:
    def __init__(self,execute,store,fail_copy=None,fail_verify=False,fail_schema=False,fail_commit=False):
        self.execute=execute
        self.store=store
        self.fail_copy=fail_copy
        self.fail_verify=fail_verify
        self.fail_schema=fail_schema
        self.fail_commit=fail_commit
        self.copied=[]
        self.commits=0
        self.rollbacks=0
        self.closed=False
    def begin(self):
        self.before=copy.deepcopy(self.store)
    def validate_schema(self,contract):
        if self.fail_schema:
            raise loader.LoadError('esquema_simulado_incompatible')
    def counts(self):
        return {entity:len(self.store[entity]) for entity in loader.ORDER}
    def rows(self,entity,columns,batch_size):
        yield from sorted(self.store[entity],key=lambda row:row[0])
    def copy(self,plan,entity,batch_size):
        assert self.execute
        self.copied.append(entity)
        if entity==self.fail_copy:
            raise RuntimeError('password_ficticio_no_divulgar')
        columns=plan.contract[entity]
        names=[c['name'] for c in columns]
        for cached in plan.rows(entity,batch_size):
            row=list(loader.adapted(cached,columns))
            if entity=='FactVentas':
                row[names.index('ventas_sin_impuestos')]=row[names.index('quantity')]*row[names.index('unit_price')]
            elif entity=='FactPedidos':
                row[names.index('tiene_factura')]=row[names.index('cantidad_facturas')]>0
            self.store[entity].append(tuple(row))
    def verify(self,plan):
        if self.fail_verify:
            raise RuntimeError('detalle_sensible_ficticio')
        assert self.counts()==plan.counts
    def commit(self):
        if self.fail_commit:
            raise RuntimeError('resultado_commit_ficticio_incierto')
        self.commits+=1
    def rollback(self):
        self.rollbacks+=1
        self.store.clear()
        self.store.update(copy.deepcopy(self.before))
    def close(self):
        self.closed=True


class DWHLoadTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ReadyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        _,self.ready=self.fixture.run_ready()
        self.root=self.fixture.root
        self.store={entity:[] for entity in loader.ORDER}
        self.remotes=[]
    def factory(self,**flags):
        def create(execute):
            remote=FakeRemote(execute,self.store,**flags)
            self.remotes.append(remote)
            return remote
        return create
    def run_load(self,execute=False,**flags):
        return loader.run(self.ready,execute=execute,report_root=self.root/'reports_load',remote_factory=self.factory(**flags))

    def test_dry_run_is_default_and_never_copies_or_commits(self):
        self.assertFalse(loader.parse_args(['--ready-dir',str(self.ready)]).execute)
        self.assertTrue(loader.parse_args(['--ready-dir',str(self.ready),'--execute']).execute)
        report,_,code=self.run_load()
        self.assertEqual(code,0)
        self.assertEqual(report['estado'],'dry_run_apto_para_carga')
        self.assertEqual(self.remotes[0].copied,[])
        self.assertEqual(self.remotes[0].commits,0)
        self.assertEqual(self.remotes[0].rollbacks,1)
        self.assertTrue(self.remotes[0].closed)
        self.assertTrue(all(not rows for rows in self.store.values()))

    def test_execute_load_order_and_generated_columns(self):
        report,_,code=self.run_load(execute=True)
        self.assertEqual(code,0)
        self.assertEqual(report['estado'],'carga_confirmada')
        self.assertEqual(self.remotes[0].copied,list(loader.ORDER))
        self.assertEqual(self.remotes[0].commits,1)
        self.assertEqual(sum(map(len,self.store.values())),16)

    def test_second_execution_identical_is_noop(self):
        self.run_load(execute=True)
        before=copy.deepcopy(self.store)
        report,_,code=self.run_load(execute=True)
        self.assertEqual(code,0)
        self.assertEqual(report['estado'],'sin_cambios_ya_cargado')
        self.assertEqual(self.store,before)
        self.assertEqual(self.remotes[-1].copied,[])

    def test_dry_run_recognizes_identical_destination(self):
        self.run_load(execute=True)
        report,_,code=self.run_load()
        self.assertEqual(code,0)
        self.assertEqual(report['estado'],'dry_run_ya_cargado_identico')
        self.assertEqual(self.remotes[-1].commits,0)

    def test_equal_counts_but_changed_attribute_are_not_overwritten(self):
        self.run_load(execute=True)
        row=list(self.store['DimCliente'][1])
        row[2]='nombre distinto ficticio'
        self.store['DimCliente'][1]=tuple(row)
        before=copy.deepcopy(self.store)
        report,_,code=self.run_load(execute=True)
        self.assertEqual(code,1)
        self.assertEqual(report['error'],'destino_con_datos_diferentes')
        self.assertEqual(self.store,before)
        self.assertEqual(self.remotes[-1].copied,[])

    def test_partial_destination_is_rejected_without_deleting(self):
        self.store['DimFecha']=[(0,None,None,None,None,None)]
        before=copy.deepcopy(self.store)
        report,_,code=self.run_load(execute=True)
        self.assertEqual(code,1)
        self.assertEqual(report['error'],'destino_parcial_o_conteos_distintos')
        self.assertEqual(self.store,before)
        self.assertEqual(self.remotes[0].copied,[])

    def test_copy_failure_rolls_back_every_table_and_hides_driver_message(self):
        report,path,code=self.run_load(execute=True,fail_copy='DimProducto')
        self.assertEqual(code,1)
        self.assertTrue(all(not rows for rows in self.store.values()))
        self.assertEqual(self.remotes[0].commits,0)
        self.assertEqual(self.remotes[0].rollbacks,1)
        self.assertNotIn('password_ficticio',path.read_text(encoding='utf-8'))
        self.assertEqual(report['error'],'error_remoto_copia')

    def test_failed_postchecks_rollback_all_inserts(self):
        report,_,code=self.run_load(execute=True,fail_verify=True)
        self.assertEqual(code,1)
        self.assertTrue(all(not rows for rows in self.store.values()))
        self.assertEqual(report['error'],'error_remoto_conciliacion')

    def test_uncertain_commit_does_not_claim_safe_rollback(self):
        report,_,code=self.run_load(execute=True,fail_commit=True)
        self.assertEqual(code,1)
        self.assertIn('commit_desconocido',report['error'])

    def test_incompatible_schema_does_not_copy(self):
        report,_,code=self.run_load(execute=True,fail_schema=True)
        self.assertEqual(code,1)
        self.assertEqual(report['error'],'esquema_simulado_incompatible')
        self.assertEqual(self.remotes[0].copied,[])

    def test_missing_or_changed_ready_never_connects(self):
        with (self.ready/'FactVentas.csv').open('a',encoding='utf-8') as stream:
            stream.write('cambio ficticio')
        report,_,code=self.run_load()
        self.assertEqual(code,1)
        self.assertEqual(self.remotes,[])
        self.assertEqual(report['error'],'error_prevalidacion_local')

    def test_duplicate_primary_keys_and_false_totals_are_rejected(self):
        path=self.ready/'FactVentas.csv'
        with path.open(encoding='utf-8-sig') as stream:
            text=stream.read()
        lines=text.splitlines(keepends=True)
        path.write_text(''.join(lines+[lines[-1]]),encoding='utf-8-sig',newline='')
        manifest_path=self.ready/'reconciliacion.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['tablas']['FactVentas']['sha256']=loader.digest(path)
        manifest['tablas']['FactVentas']['filas']+=1
        manifest_path.write_text(json.dumps(manifest),encoding='utf-8')
        report,_,code=self.run_load()
        self.assertEqual(code,1)
        self.assertEqual(report['error'],'clave_primaria_o_negocio_duplicada')
        self.assertEqual(self.remotes,[])

    def test_local_reference_error_does_not_connect(self):
        path=self.ready/'reconciliacion.json'
        manifest=json.loads(path.read_text(encoding='utf-8'))
        manifest['metricas']['ventas_sin_impuestos']='999.99'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        _,_,code=self.run_load()
        self.assertEqual(code,1)
        self.assertEqual(self.remotes,[])

    def test_copy_projection_sends_54_typed_fields_without_generated_values(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            with loader.closing(loader.LocalPlan(self.ready,temporary)) as plan:
                copied={}
                class CopyWriter:
                    def __enter__(self): return self
                    def __exit__(self,*args): pass
                    def write_row(self,row): copied['rows'].append(row)
                class Cursor:
                    def __enter__(self): return self
                    def __exit__(self,*args): pass
                    def copy(self,sql):
                        copied.update(sql=sql,rows=[])
                        return CopyWriter()
                remote=object.__new__(loader.PostgreSQL)
                class Connection:
                    def cursor(self): return Cursor()
                remote.connection=Connection()
                loader.PostgreSQL.copy(remote,plan,'FactVentas',500)
                self.assertNotIn('ventas_sin_impuestos',copied['sql'])
                self.assertEqual(len(copied['rows'][0]),16)
                self.assertIsInstance(copied['rows'][0][11],Decimal)
                loader.PostgreSQL.copy(remote,plan,'FactPedidos',500)
                self.assertNotIn('tiene_factura',copied['sql'])
                self.assertEqual(len(copied['rows'][0]),8)
                self.assertEqual(sum(len(loader.write_projection(c)['columnas_escritura']) for c in plan.contract.values()),54)

    def test_only_sql_write_operation_is_whitelisted_copy_no_ddl(self):
        source=(loader.ROOT/'etl/cargar_dwh_supabase.py').read_text(encoding='utf-8')
        self.assertNotIn('TRUNCATE ',source)
        self.assertNotIn('DELETE FROM dwh.',source)
        self.assertNotIn('ON CONFLICT',source)
        self.assertNotIn('ALTER TABLE',source)
        self.assertNotIn('CREATE TABLE dwh.',source)


    def test_report_write_failure_after_commit_preserves_honest_status(self):
        original=loader.dump_json
        calls=0
        def fail_final(path,value):
            nonlocal calls
            calls+=1
            if calls==2:
                raise OSError('archivo de reporte no disponible')
            return original(path,value)
        with patch.object(loader,'dump_json',side_effect=fail_final):
            report,_,code=self.run_load(execute=True)
        self.assertEqual(code,1)
        self.assertTrue(report['commit_confirmado'])
        self.assertEqual(report['estado'],'commit_confirmado_reporte_local_no_guardado')
        self.assertTrue(all(self.store.values()))

    def test_aggregation_mismatch_prevents_connection(self):
        path=self.ready/'reconciliacion.json'
        manifest=json.loads(path.read_text(encoding='utf-8'))
        first=next(iter(manifest['conciliacion_por_cliente']))
        manifest['conciliacion_por_cliente'][first][0]='123456.00'
        path.write_text(json.dumps(manifest),encoding='utf-8')
        report,_,code=self.run_load()
        self.assertEqual(code,1)
        self.assertEqual(self.remotes,[])
        self.assertEqual(report['error'],'conciliacion_agrupada_incorrecta')

    def test_actual_schema_checker_accepts_contract_and_rejects_identity_or_rls(self):
        contract=loader.ddl_contract()
        def metadata(unsafe=None):
            tables=[(loader.TABLES[e],'r',True,False,False,False) for e in loader.ORDER]
            if unsafe=='rls':
                tables[0]=(tables[0][0],'r',True,True,False,False)
            columns=[]
            constraints=[]
            check_names={'DimFecha':'fecha_conocida_o_desconocida','DimCliente':'cliente_desconocido','DimProducto':'producto_desconocido','FactPedidos':'fact_pedidos_cantidad_facturas_check'}
            for entity,specs in contract.items():
                table=loader.TABLES[entity]
                for spec in specs:
                    expression={'ventas_sin_impuestos':'((quantity)::numeric * unit_price)','tiene_factura':'(cantidad_facturas > 0)'}.get(spec['name'])
                    identity='d' if unsafe=='identity' and spec['name']=='cliente_key' else ''
                    columns.append((table,spec['name'],spec['type'],spec['not_null'],identity,'s' if spec['generated'] else '',expression))
                for kind,key in [('p',specs[0]['name']),('u',loader.BUSINESS[entity])]:
                    constraints.append((table,kind,'nombre',True,False,[key],None,None,[], ' ',' ',True))
                if entity in check_names:
                    constraints.append((table,'c',check_names[entity],True,False,[],None,None,[],' ',' ',True))
                for fk,parent in loader.FK.get(entity,{}).items():
                    constraints.append((table,'f','nombre',True,False,[fk],'dwh',loader.TABLES[parent],[loader.COLUMNS[parent][0]],'a','a',True))
            class Cursor:
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def execute(self,sql,params=None):
                    if 'server_version_num' in sql: self.values=[(17,)]
                    elif 'row_security_active' in sql: self.values=tables
                    elif 'pg_constraint k JOIN' in sql: self.values=constraints
                    elif 'pg_attribute a ON' in sql: self.values=columns
                    else: raise AssertionError('consulta no esperada')
                def fetchone(self): return self.values[0]
                def __iter__(self): return iter(self.values)
            class Connection:
                def cursor(self): return Cursor()
            return Connection()
        remote=object.__new__(loader.PostgreSQL)
        remote.connection=metadata()
        remote.validate_schema(contract)
        for issue in ('identity','rls'):
            remote.connection=metadata(issue)
            with self.assertRaises(loader.LoadError):
                remote.validate_schema(contract)

if __name__=='__main__':
    unittest.main()
