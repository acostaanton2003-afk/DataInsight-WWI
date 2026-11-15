"""READY: datos inventados, sin SQL Server ni servicios externos."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'etl'))
import preparar_ready as ready


class ReadyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.validated = self.root / 'validated' / 'v-ficticio'
        self.raw_dir = self.root / 'raw' / 'raw-ficticio'
        self.outputs = self.root / 'ready'
        self.validated.mkdir(parents=True)
        self.raw_dir.mkdir(parents=True)
        self.schema = ready.load_schema()['tables']
        self.data = {
            'Sales.Customers': [self.row('Sales.Customers',CustomerID='1',BillToCustomerID='2'), self.row('Sales.Customers',CustomerID='2',BillToCustomerID='2')],
            'Warehouse.StockItems': [self.row('Warehouse.StockItems',StockItemID='9'), self.row('Warehouse.StockItems',StockItemID='10')],
            'Sales.Orders': [self.row('Sales.Orders',OrderID='10',CustomerID='1',ExpectedDeliveryDate='2016-01-04'), self.row('Sales.Orders',OrderID='11',CustomerID='2',ExpectedDeliveryDate='2016-01-05')],
            'Sales.Invoices': [self.row('Sales.Invoices',InvoiceID='20',CustomerID='1',BillToCustomerID='2',OrderID='10',InvoiceDate='2016-01-02')],
            'Sales.InvoiceLines': [self.row('Sales.InvoiceLines',InvoiceLineID='30',InvoiceID='20',StockItemID='9',Quantity='3',UnitPrice='10.10',TaxAmount='3.00',ExtendedPrice='33.30'), self.row('Sales.InvoiceLines',InvoiceLineID='31',InvoiceID='20',StockItemID='9',Quantity='1',UnitPrice='0.10',TaxAmount='0.02',ExtendedPrice='0.12')],
        }
        self.persist()

    def row(self,table,**changes):
        result = {}
        for column in self.schema[table]:
            result[column['name']] = None if column['nullable'] else {
                'int':'1','decimal':'1.00' if column['scale']==2 else '1.000',
                'bit':'False','date':'2016-01-01','datetime2':'2016-01-01T00:00:00.1234567',
                'nvarchar':'prueba','varbinary':'0x00','geography':'0x00',
            }[column['type']]
        result.update(changes)
        return result

    def persist(self,mode='completo'):
        manifest = {'run_id':'raw-ficticio','estado':'completado','modo':mode,'tablas':{}}
        quality = {'run_id':self.validated.name,'estado':'completado','raw_run_id':'raw-ficticio','raw_modo':mode,'raw_dir':str(self.raw_dir),'tablas':{}}
        for table,rows in self.data.items():
            path = self.validated / (table+'.csv')
            columns = [column['name'] for column in self.schema[table]]
            with path.open('w',encoding='utf-8-sig',newline='') as stream:
                writer = csv.writer(stream,quoting=csv.QUOTE_NOTNULL)
                writer.writerow(columns)
                writer.writerows([[row[c] for c in columns] for row in rows])
            manifest['tablas'][table] = {'estado':'completado','filas_extraidas':len(rows)}
            quality['tablas'][table] = {'validated_file':str(path),'rechazadas':0,'leidas':len(rows),'validas':len(rows),'balance_correcto':True}
        (self.raw_dir / 'extraction_manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        reports = self.root / 'reports'
        reports.mkdir(exist_ok=True)
        (reports / (self.validated.name+'.json')).write_text(json.dumps(quality),encoding='utf-8')

    def run_ready(self,profiles=None):
        return ready.prepare(self.validated,ready_root=self.outputs,profiles=profiles if profiles is not None else {})

    def assert_failed(self):
        with self.assertRaises(ready.ReadyError):
            self.run_ready()
        self.assertFalse([p for p in self.outputs.iterdir() if p.is_dir() and p.name!='failures'])
        report = json.loads(next((self.outputs / 'failures').glob('*.json')).read_text(encoding='utf-8'))
        self.assertEqual(report['estado'],'fallido')
        self.assertTrue(report['errores'])
        return report

    def test_stable_injective_keys_and_unknown_reservation(self):
        for entity in ready.NAMESPACES:
            values = [ready.stable_key(entity,k) for k in (-2**31,-1,0,1,2**31-1)]
            self.assertEqual(len(set(values)),5)
            self.assertTrue(all(0<value<2**63 for value in values))
        self.assertNotEqual(ready.stable_key('cliente',1),ready.stable_key('producto',1))
        with self.assertRaises(ready.ReadyError):
            ready.stable_key('cliente',None)

    def test_complete_small_run_and_decimal_measures(self):
        report,path = self.run_ready()
        self.assertEqual(report['metricas'],{'fact_ventas_rows':2,'fact_pedidos_rows':2,'facturas_distintas':1,'pedidos_sin_factura':1,'meses':1,'ventas_sin_impuestos':'30.40','impuestos':'3.02','ventas_con_impuestos':'33.42'})
        self.assertEqual({k:v['filas'] for k,v in report['tablas'].items()},{'DimCliente':3,'DimProducto':3,'DimFecha':6,'FactVentas':2,'FactPedidos':2})
        sales = list(ready.output_rows(path,'FactVentas'))
        self.assertTrue(all(row['cliente_key']==str(ready.stable_key('cliente',1)) for row in sales))
        self.assertTrue(all(row['bill_to_customer_id_factura']=='2' for row in sales))
        self.assertEqual(report['desconocidos_asignados'],{'clientes':0,'productos':0,'fechas':0})
        self.assertEqual(next(ready.output_rows(path,'DimCliente'))['customer_name'],'Desconocido')

    def test_repeated_runs_keep_previous_files_and_same_csv_hashes(self):
        before = {p.name:ready.digest(p) for p in self.validated.glob('*.csv')}
        first,a = self.run_ready()
        second,b = self.run_ready()
        self.assertNotEqual(a,b)
        self.assertEqual({k:v['sha256'] for k,v in first['tablas'].items()},{k:v['sha256'] for k,v in second['tablas'].items()})
        self.assertEqual(before,{p.name:ready.digest(p) for p in self.validated.glob('*.csv')})

    def test_keys_do_not_depend_on_input_order(self):
        _,first = self.run_ready()
        original = {entity:{row[ready.COLUMNS[entity][1]]:row[ready.COLUMNS[entity][0]] for row in ready.output_rows(first,entity)} for entity in ('DimCliente','DimProducto','FactVentas','FactPedidos')}
        for rows in self.data.values():
            rows.reverse()
        self.persist()
        _,second = self.run_ready()
        permuted = {entity:{row[ready.COLUMNS[entity][1]]:row[ready.COLUMNS[entity][0]] for row in ready.output_rows(second,entity)} for entity in original}
        self.assertEqual(original,permuted)

    def test_duplicate_line_is_rejected_not_deduplicated(self):
        self.data['Sales.InvoiceLines'].append(dict(self.data['Sales.InvoiceLines'][0]))
        self.persist()
        self.assert_failed()

    def test_duplicate_customer_is_rejected(self):
        self.data['Sales.Customers'].append(dict(self.data['Sales.Customers'][0]))
        self.persist()
        self.assert_failed()

    def test_invalid_date_and_no_fake_unknown_date(self):
        self.data['Sales.Invoices'][0]['InvoiceDate']='2016-02-30'
        self.persist()
        self.assert_failed()
        self.assertEqual(ready.date_key('2016-02-29'),20160229)

    def test_missing_reference_produces_diagnostic_without_ready(self):
        self.data['Sales.InvoiceLines'][0]['StockItemID']='999'
        self.persist()
        report = self.assert_failed()
        self.assertEqual(report['relaciones']['InvoiceLines.StockItemID'],1)
        self.assertEqual(report['ejemplos_referencias_ausentes'][0]['InvoiceLineID'],30)

    def test_missing_header_customer_is_not_mapped_to_zero(self):
        self.data['Sales.Invoices'][0]['CustomerID']='999'
        self.persist()
        report = self.assert_failed()
        self.assertEqual(report['relaciones']['Invoices.CustomerID'],1)

    def test_monetary_difference_is_rejected(self):
        self.data['Sales.InvoiceLines'][0]['ExtendedPrice']='33.32'
        self.persist()
        self.assert_failed()

    def test_sample_is_rejected(self):
        self.persist(mode='muestra')
        self.assert_failed()

    def test_reference_values_are_scoped_not_universal(self):
        expected = {'fact_ventas_rows':2,'meses':1,'ventas_sin_impuestos':'30.40'}
        profile = {'raw-ficticio':{'metricas':expected,'validated_sha256':{table:ready.digest(self.validated / (table+'.csv')) for table in self.data}}}
        report,_ = self.run_ready(profiles=profile)
        self.assertEqual(report['referencia_aplicada'],'raw-ficticio')
        expected['fact_ventas_rows']=3
        with self.assertRaises(ready.ReadyError):
            self.run_ready(profiles=profile)

    def test_output_tampering_is_detected_before_publication(self):
        original = ready.verify_outputs
        def corrupt(output,*args):
            path = output / 'FactVentas.csv'
            path.write_bytes(path.read_bytes().replace(b'30.30',b'30.31'))
            return original(output,*args)
        with patch.object(ready,'verify_outputs',side_effect=corrupt):
            self.assert_failed()

    def test_optional_order_null_and_multiple_invoices_do_not_duplicate_orders(self):
        self.data['Sales.Invoices'].append(self.row('Sales.Invoices',InvoiceID='21',CustomerID='1',BillToCustomerID='2',OrderID='10',InvoiceDate='2016-01-02',IsCreditNote='True'))
        self.data['Sales.InvoiceLines'][1]['InvoiceID']='21'
        self.persist()
        report,path = self.run_ready()
        orders = list(ready.output_rows(path,'FactPedidos'))
        self.assertEqual(orders[0]['cantidad_facturas'],'2')
        self.assertEqual(report['metricas']['fact_pedidos_rows'],2)
        self.assertEqual(report['metricas']['ventas_sin_impuestos'],'30.30')
        self.data['Sales.Invoices'][1]['OrderID']=None
        self.persist()
        _,path = self.run_ready()
        self.assertIsNone(list(ready.output_rows(path,'FactVentas'))[1]['order_id'])

    def test_failed_publication_leaves_no_successful_run(self):
        replace = ready.os.replace
        def fail(source,destination):
            if Path(source).name=='output':
                raise OSError('fallo de publicación ficticio')
            return replace(source,destination)
        with patch.object(ready.os,'replace',side_effect=fail):
            self.assert_failed()


    def test_ready_headers_match_approved_logical_ddl(self):
        import re
        ddl = (ready.ROOT / 'database/data-warehouse/01_modelo_logico.sql').read_text(encoding='utf-8')
        names = {'DimFecha':'dim_fecha','DimCliente':'dim_cliente','DimProducto':'dim_producto','FactVentas':'fact_ventas','FactPedidos':'fact_seguimiento_pedidos'}
        for entity,table in names.items():
            block = re.search(r'CREATE TABLE dwh\.'+table+r' \((.*?)\n\);',ddl,re.DOTALL)[1]
            columns = re.findall(r'^    ([a-z_]+) (?:integer|bigint|date|text|smallint|boolean|numeric)\b',block,re.MULTILINE)
            self.assertEqual(ready.COLUMNS[entity],columns)

if __name__ == '__main__':
    unittest.main()
