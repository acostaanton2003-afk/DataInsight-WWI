"""Reglas dimensionales con datos ficticios; sin DWH ni SQL Server."""

import importlib.util
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('model', ROOT / 'database/data-warehouse/validar_modelo_local.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class DimensionalModelTests(unittest.TestCase):
    def setUp(self):
        self.connection = model.analytical_connection()
        self.addCleanup(self.connection.close)
        self.connection.executemany('INSERT INTO src_customers VALUES (?,?)', [(1,2),(2,2)])
        self.connection.execute('INSERT INTO src_products VALUES (9)')
        self.connection.executemany('INSERT INTO src_orders VALUES (?,?,?,?)', [(10,1,'2016-01-01',None),(11,1,'2016-01-01',None)])
        self.connection.execute("INSERT INTO src_invoices VALUES (20,1,2,10,'2016-01-02',0)")
        # Dos lineas del mismo producto y factura: nunca deduplicar ese par.
        self.connection.executemany('INSERT INTO src_lines VALUES (?,?,?,?,?,?,?,?)',
            [(30,20,9,7,2,'10.00','3.00','23.00'), (31,20,9,7,1,'10.00','1.50','11.50')])

    def test_same_invoice_product_keeps_two_lines_and_single_invoice(self):
        results = model.query_results(self.connection)
        self.assertTrue(all(model.assess(results).values()))
        self.assertEqual(results['ventas_enlazadas'][0]['lineas'], 2)
        self.assertEqual(results['ventas_enlazadas'][0]['facturas'], 1)
        self.assertEqual(Decimal(results['ventas_enlazadas'][0]['ventas_sin_impuestos']), Decimal('30'))
        self.assertEqual(results['pedidos'][0]['total'], 2)
        self.assertEqual(results['pedidos'][0]['sin_factura'], 1)

    def test_commercial_customer_is_not_bill_to(self):
        results = model.query_results(self.connection)
        self.assertEqual(results['top_clientes'][0]['customer_id'], 1)
        self.assertEqual(results['cobertura_cabeceras'][0]['cliente_distinto_facturacion'], 1)

    def test_duplicate_parent_exposes_multiplication(self):
        self.connection.execute('INSERT INTO src_products VALUES (9)')
        controls = model.assess(model.query_results(self.connection))
        self.assertFalse(controls['claves_unicas_y_no_nulas'])
        self.assertFalse(controls['grano_conservado'])
        self.assertFalse(controls['importes_conservados_en_enlaces'])

    def test_orphan_is_not_hidden_by_inner_join(self):
        self.connection.execute('UPDATE src_lines SET stock_item_id=999 WHERE invoice_line_id=31')
        controls = model.assess(model.query_results(self.connection))
        self.assertFalse(controls['relaciones_disponibles_sin_huerfanos'])
        self.assertFalse(controls['grano_conservado'])

    def test_null_optional_order_is_not_orphan(self):
        self.connection.execute('UPDATE src_invoices SET order_id=NULL')
        results = model.query_results(self.connection)
        self.assertTrue(model.assess(results)['relaciones_disponibles_sin_huerfanos'])
        self.assertEqual(results['pedidos'][0]['sin_factura'], 2)

    def test_decimal_and_provisional_tolerance(self):
        self.assertEqual(model.line_base(3, '0.10'), '0.30')
        self.assertEqual(model.monetary_invalid(3,'0.10','0.10','0.41'), 0)
        self.assertEqual(model.monetary_invalid(3,'0.10','0.10','0.42'), 1)
        self.assertEqual(model.monetary_invalid(3,None,'0.10','0.40'), 1)
        aggregate = model.DecimalSum()
        aggregate.step('9999999999999999.99')
        aggregate.step('0.01')
        self.assertEqual(aggregate.finalize(), '10000000000000000.00')

    def test_missing_money_does_not_become_zero(self):
        self.connection.execute('UPDATE src_lines SET unit_price=NULL WHERE invoice_line_id=30')
        controls = model.assess(model.query_results(self.connection))
        self.assertFalse(controls['formula_monetaria_completa_y_en_tolerancia'])
        self.assertFalse(controls['importes_conservados_en_enlaces'])

    def test_source_mapping_only_uses_existing_columns(self):
        metadata = json.loads((ROOT / 'etl/esquema_raw.json').read_text(encoding='utf-8'))['tables']
        for source, columns in model.SOURCES.values():
            names = {c['name'] for c in metadata[source]}
            self.assertTrue({original for _, original, _ in columns} <= names)

    def test_sample_manifest_cannot_certify_complete_relationships(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'extraction_manifest.json').write_text(json.dumps({'modo':'muestra','estado':'completado'}), encoding='utf-8')
            with self.assertRaises(ValueError):
                model.verify(directory)


if __name__ == '__main__':
    unittest.main()
