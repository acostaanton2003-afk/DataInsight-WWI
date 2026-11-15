"""Pruebas con filas inventadas; no leen data/raw ni conectan a SQL Server."""

import csv
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'etl'))
import validar_raw as raw


class RawQualityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.metadata = raw.load_schema()

    def row(self, table, **changes):
        result = {}
        for column in self.metadata['tables'][table]:
            kind = column['type']
            result[column['name']] = None if column['nullable'] else {
                'int': '1', 'decimal': '1.00' if column['scale'] == 2 else '1.000',
                'bit': 'False', 'date': '2016-01-01', 'datetime2': '2016-01-01T10:20:30.1234567',
                'nvarchar': 'prueba', 'varbinary': '0x00ff', 'geography': '0x00ff',
            }[kind]
        if table == 'Sales.InvoiceLines':
            result.update(Quantity='2', UnitPrice='10.00', TaxAmount='3.00', ExtendedPrice='23.00')
        result.update(changes)
        return [result[c['name']] for c in self.metadata['tables'][table]]

    def write_csv(self, path, table, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_NOTNULL)
            writer.writerow([c['name'] for c in self.metadata['tables'][table]])
            writer.writerows(rows)

    def validate(self, table, rows):
        directory = self.root / uuid.uuid4().hex
        directory.mkdir()
        source = directory / (table + '.csv')
        self.write_csv(source, table, rows)
        before = source.read_bytes()
        result = raw.validate_table(table, source, self.metadata['tables'][table],
                                    directory / 'good.csv', directory / 'bad.csv', directory / 'keys.sqlite')
        self.assertEqual(source.read_bytes(), before)
        self.assertTrue(result['balance_correcto'])
        self.assertEqual(result['validas'] + result['rechazadas'], result['leidas'])
        return result, directory

    def read(self, path):
        with path.open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.reader(stream, quoting=csv.QUOTE_NOTNULL, strict=True))

    def test_valid_rows_for_all_five_tables(self):
        for table, _, _ in raw.TABLES:
            with self.subTest(table=table):
                report, _ = self.validate(table, [self.row(table)])
                self.assertEqual((report['validas'], report['rechazadas']), (1, 0))

    def test_null_pk_and_mandatory_field(self):
        report, folder = self.validate('Sales.InvoiceLines', [self.row('Sales.InvoiceLines', InvoiceLineID=None, Description=None)])
        self.assertEqual(report['rechazadas'], 1)
        self.assertEqual(report['errores'], {'OBLIGATORIO_NULO': 1, 'PK_NULA': 1})
        rejected = self.read(folder / 'bad.csv')
        details = dict(zip(rejected[0], rejected[1]))
        self.assertEqual(details['__raw_record'], '1')
        self.assertEqual(details['__raw_line'], '2')
        self.assertEqual(len(json.loads(details['__errors_json'])), 2)

    def test_nullable_text_empty_unicode_and_original_precision(self):
        row = self.row('Sales.Orders', Comments=None, DeliveryInstructions='', InternalComments='ñ, "ficticio"\nsalto')
        report, folder = self.validate('Sales.Orders', [row])
        self.assertEqual(report['validas'], 1)
        self.assertEqual(self.read(folder / 'good.csv')[1], row)

    def test_all_duplicate_occurrences_across_batches_are_rejected(self):
        rows = [self.row('Sales.InvoiceLines', InvoiceLineID=str(i)) for i in range(1, 27)]
        rows[-1][0] = '01'  # Mismo entero, no se normaliza la salida.
        report, _ = self.validate('Sales.InvoiceLines', rows)
        self.assertEqual((report['leidas'], report['validas'], report['rechazadas']), (26, 24, 2))
        self.assertEqual(report['errores'], {'PK_DUPLICADA': 2})

    def test_monetary_tolerance_boundary(self):
        rows = [self.row('Sales.InvoiceLines', InvoiceLineID='1', ExtendedPrice='23.01'),
                self.row('Sales.InvoiceLines', InvoiceLineID='2', ExtendedPrice='22.99'),
                self.row('Sales.InvoiceLines', InvoiceLineID='3', ExtendedPrice='23.02')]
        report, _ = self.validate('Sales.InvoiceLines', rows)
        self.assertEqual((report['validas'], report['rechazadas']), (2, 1))
        self.assertEqual(report['errores'], {'DIFERENCIA_MONETARIA': 1})

    def test_nullable_price_cannot_certify_formula(self):
        report, _ = self.validate('Sales.InvoiceLines', [self.row('Sales.InvoiceLines', UnitPrice=None)])
        self.assertEqual(report['errores'], {'MONETARIO_INCOMPLETO': 1})

    def test_invalid_types_dates_precision_and_hex(self):
        examples = [('Sales.InvoiceLines', {'Quantity': 'dos'}),
                    ('Sales.InvoiceLines', {'TaxAmount': 'NaN'}),
                    ('Sales.InvoiceLines', {'UnitPrice': '10.001'}),
                    ('Sales.Orders', {'OrderDate': '2016-02-30'}),
                    ('Sales.Customers', {'DeliveryLocation': 'no-es-hex'}),
                    ('Sales.Invoices', {'IsCreditNote': 'talvez'}),
                    ('Sales.Orders', {'OrderID': '2147483648'})]
        for table, changes in examples:
            with self.subTest(changes=changes):
                report, _ = self.validate(table, [self.row(table, **changes)])
                self.assertEqual(report['rechazadas'], 1)

    def test_signs_are_profiled_not_invented_business_errors(self):
        report, _ = self.validate('Sales.InvoiceLines', [self.row('Sales.InvoiceLines', Quantity='-2', TaxAmount='0.00', ExtendedPrice='-20.00')])
        self.assertEqual(report['validas'], 1)
        self.assertEqual(report['advertencias']['Quantity:NEGATIVO'], 1)
        self.assertEqual(report['advertencias']['TaxAmount:CERO'], 1)

    def test_wrong_column_count_preserves_complete_original_row(self):
        row = self.row('Sales.Orders') + ['campo adicional ficticio']
        report, folder = self.validate('Sales.Orders', [row])
        self.assertEqual(report['errores'], {'CSV_COLUMNAS': 1})
        self.assertEqual(json.loads(self.read(folder / 'bad.csv')[1][-1]), row)

    def prepare_run(self):
        for table, filename, _ in raw.TABLES:
            self.write_csv(self.root / 'raw' / filename, table, [self.row(table)])

    def test_complete_run_report_and_no_fk_checks(self):
        self.prepare_run()
        report, path = raw.run_validation(self.root)
        self.assertTrue(path.is_file())
        self.assertIn('NO_EVALUADAS', report['claves_foraneas'])
        self.assertEqual(sum(r['validas'] for r in report['tablas'].values()), 5)
        self.assertFalse(list(self.root.glob('.validacion-*')))

    def test_malformed_csv_does_not_publish_or_touch_previous_outputs(self):
        self.prepare_run()
        previous = self.root / 'validated' / 'previous' / 'example.csv'
        previous.parent.mkdir(parents=True)
        previous.write_text('resultado anterior ficticio', encoding='utf-8')
        source = self.root / 'raw' / 'Sales.Orders.csv'
        with source.open('a', encoding='utf-8') as stream:
            stream.write('"comilla sin cerrar')
        with self.assertRaises(csv.Error):
            raw.run_validation(self.root)
        self.assertEqual(previous.read_text(encoding='utf-8'), 'resultado anterior ficticio')
        self.assertEqual(list((self.root / 'validated').iterdir()), [previous.parent])
        self.assertFalse((self.root / 'reports').exists())
        self.assertFalse(list(self.root.glob('.validacion-*')))

    def test_publication_failure_rolls_back_new_run(self):
        self.prepare_run()
        original_replace = raw.os.replace
        calls = 0
        def fail_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('fallo de publicación ficticio')
            return original_replace(source, destination)
        with patch.object(raw.os, 'replace', side_effect=fail_second):
            with self.assertRaises(OSError):
                raw.run_validation(self.root)
        self.assertFalse(list((self.root / 'validated').iterdir()))
        self.assertFalse((self.root / 'reports').exists())


    def test_explicit_raw_directory_keeps_legacy_default(self):
        self.prepare_run()
        chosen = self.root / 'raw' / 'run-ficticio'
        chosen.mkdir()
        for table, filename, _ in raw.TABLES:
            self.write_csv(chosen / filename, table, [self.row(table), self.row(table, **{next(c['name'] for c in self.metadata['tables'][table] if c['primary_key']): '2'})])
        explicit, _ = raw.run_validation(self.root, raw_dir=chosen)
        legacy, _ = raw.run_validation(self.root)
        self.assertEqual(explicit['raw_dir'], str(chosen.resolve()))
        self.assertEqual(sum(r['leidas'] for r in explicit['tablas'].values()), 10)
        self.assertEqual(sum(r['leidas'] for r in legacy['tablas'].values()), 5)
        self.assertEqual(raw.parse_args(['--raw-dir', str(chosen)]).raw_dir, chosen)
        self.assertIsNone(raw.parse_args([]).raw_dir)

    def test_failed_manifest_is_not_validated(self):
        self.prepare_run()
        (self.root / 'raw' / 'extraction_manifest.json').write_text(json.dumps({'estado': 'fallido'}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'no está completada'):
            raw.run_validation(self.root, raw_dir=self.root / 'raw')
        self.assertFalse((self.root / 'reports').exists())

    def test_completed_manifest_provenance_and_count_mismatch(self):
        self.prepare_run()
        manifest = {'estado': 'completado', 'modo': 'completo', 'run_id': 'ficticio',
                    'tablas': {table: {'estado': 'completado', 'filas_extraidas': 1} for table, _, _ in raw.TABLES}}
        path = self.root / 'raw' / 'extraction_manifest.json'
        path.write_text(json.dumps(manifest), encoding='utf-8')
        report, _ = raw.run_validation(self.root)
        self.assertEqual(report['raw_run_id'], 'ficticio')
        self.assertEqual(report['raw_modo'], 'completo')
        manifest['tablas']['Sales.Orders']['filas_extraidas'] = 2
        path.write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'filas distintas'):
            raw.run_validation(self.root)

    def test_missing_selected_directory_does_not_fall_back(self):
        self.prepare_run()
        with self.assertRaisesRegex(ValueError, 'Falta CSV RAW'):
            raw.run_validation(self.root, raw_dir=self.root / 'inexistente')

if __name__ == '__main__':
    unittest.main()
