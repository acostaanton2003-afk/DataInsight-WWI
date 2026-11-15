"""Contrato y seguridad del DDL: pruebas locales sin PostgreSQL ni Supabase."""

import csv
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('physical',ROOT/'database/data-warehouse/verificar_ready_ddl.py')
physical = importlib.util.module_from_spec(spec)
spec.loader.exec_module(physical)


class PhysicalDDLTests(unittest.TestCase):
    def setUp(self):
        self.sql = physical.DDL.read_text(encoding='utf-8')
        self.clean = re.sub(r'--[^\n]*','',self.sql)
        self.contract = physical.ddl_contract()

    def test_only_five_tables_in_existing_dwh(self):
        created = re.findall(r'CREATE TABLE ([a-z_.]+)',self.clean)
        self.assertEqual(set(created),{'dwh.'+table for table in physical.TABLES.values()})
        self.assertEqual(len(created),5)
        self.assertNotRegex(self.clean,r'CREATE SCHEMA|CREATE TABLE public\.')
        self.assertNotIn('fact_seguimiento_pedidos',self.clean)

    def test_columns_types_and_keys_match_logical_model_and_ready(self):
        logical = (ROOT/'database/data-warehouse/01_modelo_logico.sql').read_text(encoding='utf-8').replace('fact_seguimiento_pedidos','fact_pedidos')
        historical = physical.ddl_contract(logical)
        # Unica evolucion fisica deliberada: eliminar identidades en las cuatro claves.
        for columns in historical.values():
            for column in columns:
                column['identity'] = False
        self.assertEqual(self.contract,historical)
        self.assertEqual(sum(map(len,self.contract.values())),56)

    def test_grain_and_degenerate_identifiers(self):
        for entity,column in [('FactVentas','invoice_line_id'),('FactPedidos','order_id')]:
            table = physical.TABLES[entity]
            body = re.search(r'CREATE TABLE dwh\.'+table+r'\s*\((.*?)\n\);',self.clean,re.DOTALL)[1]
            self.assertRegex(body,column+r' integer NOT NULL UNIQUE')
        sales = re.search(r'CREATE TABLE dwh.fact_ventas\s*\((.*?)\n\);',self.clean,re.DOTALL)[1]
        self.assertRegex(sales,r'order_id integer,')
        self.assertNotRegex(sales,r'invoice_id integer[^\n]*UNIQUE')
        self.assertNotRegex(sales,r'order_id[^\n]*REFERENCES')
        self.assertEqual(len(re.findall(r'REFERENCES dwh\.',self.clean)),6)

    def test_generated_columns_and_decimal_precision(self):
        sales = {c['name']:c for c in self.contract['FactVentas']}
        self.assertEqual(sales['ventas_sin_impuestos']['type'],'numeric(28,2)')
        self.assertTrue(sales['ventas_sin_impuestos']['generated'])
        self.assertRegex(self.clean,r'\(quantity::numeric \* unit_price\) STORED')
        self.assertRegex(self.clean,r'GENERATED ALWAYS AS \(cantidad_facturas > 0\) STORED')
        self.assertEqual(sales['tax_rate']['type'],'numeric(18,3)')
        for column in ('unit_price','tax_amount','extended_price'):
            self.assertEqual(sales[column]['type'],'numeric(18,2)')
        self.assertTrue(next(c for c in self.contract['FactPedidos'] if c['name']=='tiene_factura')['generated'])
        self.assertEqual(sum(c['identity'] for cols in self.contract.values() for c in cols),0)

    def test_unknown_zero_allowed_but_not_defaulted_or_inserted(self):
        for name in ('fecha_key = 0','cliente_key = 0','producto_key = 0'):
            self.assertIn(name,self.clean)
        self.assertNotRegex(self.clean,r'\bDEFAULT\s+0\b|\bINSERT\s+INTO\b')

    def test_fk_indexes_cover_leading_columns(self):
        indexes = re.findall(r'CREATE INDEX (\w+) ON dwh\.(\w+) \(([^)]+)\)',self.clean)
        self.assertEqual(len(indexes),8)
        leading = {(table,columns.split(',')[0].strip()) for _,table,columns in indexes}
        needed = {('fact_ventas',c) for c in ('fecha_factura_key','cliente_key','producto_key')}
        needed |= {('fact_pedidos',c) for c in ('fecha_pedido_key','fecha_entrega_prevista_key','cliente_key')}
        self.assertTrue(needed <= leading)

    def test_existing_relations_fail_closed_and_transactional(self):
        self.assertTrue(self.clean.lstrip().startswith('BEGIN;'))
        self.assertTrue(self.clean.rstrip().endswith('COMMIT;'))
        self.assertIn("current_setting('server_version_num')",self.clean)
        self.assertIn("c.relkind IN ('r','p','v','m','f','S')",self.clean)
        self.assertIn('RAISE EXCEPTION',self.clean)
        self.assertLess(self.clean.index('$preflight$;'),self.clean.index('CREATE TABLE'))
        self.assertNotIn('IF NOT EXISTS',self.clean)

    def test_api_privileges_revoked_and_rls_enabled(self):
        self.assertIn('REVOKE ALL ON SCHEMA dwh FROM PUBLIC, anon, authenticated;',self.clean)
        self.assertIn('REVOKE ALL ON ALL TABLES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;',self.clean)
        self.assertIn('REVOKE ALL ON ALL SEQUENCES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;',self.clean)
        self.assertEqual(len(re.findall(r'ALTER TABLE dwh\.\w+ ENABLE ROW LEVEL SECURITY;',self.clean)),5)
        self.assertNotRegex(self.clean,r'\bGRANT\s+\w+\s+ON\b|CREATE POLICY|FORCE ROW LEVEL SECURITY')
        self.assertIn('has_schema_privilege',self.clean)
        self.assertIn('has_table_privilege',self.clean)
        self.assertIn('has_sequence_privilege',self.clean)
        self.assertNotRegex(self.clean,r'REVOKE[^;]*FROM\s+(?:postgres|service_role|supabase_admin)\b')

    def test_defaults_are_scoped_and_global_grants_are_not_hidden(self):
        statements = re.findall(r'ALTER DEFAULT PRIVILEGES[^;]+;',self.clean)
        self.assertEqual(len(statements),2)
        self.assertTrue(all('IN SCHEMA dwh' in stmt for stmt in statements))
        self.assertIn('d.defaclnamespace=0',self.clean)
        self.assertIn("d.defaclobjtype IN ('r','S')",self.clean)
        self.assertNotRegex(self.clean,r'ALTER ROLE|ALTER DATABASE|NOTIFY pgrst')

    def test_no_destructive_or_data_loading_statements(self):
        self.assertNotRegex(self.clean,r'\bDROP\s+(?:TABLE|SCHEMA)\b|\bTRUNCATE\s+(?:TABLE\s+)?dwh\.|\bDELETE\s+FROM\b|\bCOPY\s+dwh\.')
        verification = (physical.DDL.parent/'04_verificacion_dwh.sql').read_text(encoding='utf-8')
        verification = re.sub(r'--[^\n]*','',verification)
        for statement in verification.split(';'):
            if statement.strip():
                self.assertTrue(statement.lstrip().startswith('SELECT'),statement)

    def test_csv_type_checks_are_exact_and_preserve_unknown_nulls(self):
        for kind,value in [('bigint','6442450945'),('numeric(18,2)','9999999999999999.99'),('date','2016-02-29'),('boolean','false')]:
            physical.check_value(value,{'type':kind,'not_null':True})
        physical.check_value(None,{'type':'date','not_null':False})
        for kind,value in [('integer','2147483648'),('numeric(18,2)','10000000000000000.00'),('numeric(18,2)','1.001'),('numeric(18,2)','NaN'),('date','2016-02-30'),('boolean','yes'),('text','a\x00b')]:
            with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):
                physical.check_value(value,{'type':kind,'not_null':True})
        with self.assertRaises(ValueError):
            physical.check_value(None,{'type':'text','not_null':True})

    def test_local_inspector_with_only_fictitious_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {'estado':'completado','tablas':{}}
            for entity,columns in self.contract.items():
                path = root/(entity+'.csv')
                row = []
                for column in columns:
                    kind = column['type']
                    row.append('2016-01-01' if kind=='date' else 'false' if kind=='boolean' else 'ficticio' if kind=='text' else '1')
                if entity=='FactPedidos':

                    row[[c['name'] for c in columns].index('tiene_factura')]='true'
                with path.open('w',encoding='utf-8-sig',newline='') as stream:
                    writer=csv.writer(stream,quoting=csv.QUOTE_NOTNULL)
                    writer.writerow([c['name'] for c in columns])
                    writer.writerow(row)
                import hashlib
                report['tablas'][entity]={'filas':1,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            (root/'reconciliacion.json').write_text(json.dumps(report),encoding='utf-8')
            results = physical.inspect(root)
            self.assertTrue(all(r['tipos_compatibles'] for r in results.values()))
            self.assertEqual(results['FactVentas']['columnas_generadas_excluir_de_carga'],['ventas_sin_impuestos'])
            with (root/'DimFecha.csv').open('a',encoding='utf-8') as stream:
                stream.write('dato modificado ficticio')
            with self.assertRaisesRegex(ValueError,'hash distinto'):
                physical.inspect(root)


    def test_keys_are_supplied_not_generated_or_defaulted(self):
        for name in ('cliente_key','producto_key','venta_key','pedido_key'):
            self.assertRegex(self.clean,name+r' bigint PRIMARY KEY')
        self.assertNotRegex(self.clean,r'AS IDENTITY|\bSERIAL\b|\bnextval\s*\(|CREATE SEQUENCE')
        self.assertIn('REVOKE ALL ON ALL SEQUENCES IN SCHEMA dwh',self.clean)

    def test_owner_preflight_is_exact_not_just_schema_access(self):
        self.assertIn('schema_owner IS DISTINCT FROM executor_oid',self.clean)
        self.assertIn('rolname = current_user',self.clean)
        self.assertIn('pg_get_userbyid(schema_owner),current_user,session_user',self.clean)
        self.assertIn('has_any_column_privilege',self.clean)
        checks=(physical.DDL.parent/'04_verificacion_dwh.sql').read_text(encoding='utf-8')
        self.assertIn('propietario_exacto',checks)
        self.assertIn('permiso_en_columnas',checks)
        self.assertIn("c.relkind='S'",checks)

    def test_load_projection_excludes_values_not_just_destination_names(self):
        for entity,expected_count in [('FactVentas',16),('FactPedidos',8)]:
            plan=physical.write_projection(self.contract[entity])
            self.assertEqual(len(plan['columnas_escritura']),expected_count)
            projected=[physical.COLUMNS[entity][i] for i in plan['posiciones_csv_base_0']]
            self.assertEqual(projected,plan['columnas_escritura'])
        self.assertEqual(sum(len(physical.write_projection(cols)['columnas_escritura']) for cols in self.contract.values()),54)

    def test_materialized_ready_values_must_match_generated_expressions(self):
        physical.check_generated('FactVentas',{'quantity':'3','unit_price':'0.10','ventas_sin_impuestos':'0.30'})
        physical.check_generated('FactPedidos',{'cantidad_facturas':'0','tiene_factura':'false'})
        with self.assertRaises(ValueError):
            physical.check_generated('FactVentas',{'quantity':'3','unit_price':'0.10','ventas_sin_impuestos':None})
        with self.assertRaises(ValueError):
            physical.check_generated('FactVentas',{'quantity':'3','unit_price':'0.10','ventas_sin_impuestos':'0.31'})
        with self.assertRaises(ValueError):
            physical.check_generated('FactPedidos',{'cantidad_facturas':'2','tiene_factura':'false'})

if __name__ == '__main__':
    unittest.main()
