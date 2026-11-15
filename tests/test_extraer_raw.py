"""Pruebas unitarias de extracción: conexión ficticia, sin SQL Server."""

import csv
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'etl'))
import extraer_raw as raw


class FakeCursor:
    description = [(name,) for name in ('ID', 'Nulo', 'Vacio', 'Texto', 'Fecha', 'Binario')]
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.position = 0
    def execute(self, query):
        self.connection.queries.append(query)
        self.table = next(table for table, _, _ in raw.TABLES if f'FROM {table}' in query)
        if 'COUNT_BIG(*)' in query:
            self.count_query = True
        else:
            self.count_query = False
            rows = self.connection.rows
            self.rows = rows[:100] if 'TOP (100)' in query else rows
    def fetchone(self):
        if self.connection.counts:
            return (self.connection.counts.pop(0),)
        return (len(self.connection.rows),)
    def fetchmany(self, size):
        self.connection.batch_sizes.append(size)
        if self.connection.fail_fetch and self.position > 0:
            raise OSError('lectura ficticia fallida')
        batch = self.rows[self.position:self.position + size]
        self.position += len(batch)
        return batch
    def close(self):
        pass


class FakeConnection:
    def __init__(self, size=103, counts=None, fail_fetch=False):
        self.rows = [(i, None, '', 'ñ, "ficticio"\nsalto', date(2016, 1, 1), b'\x00\xff') for i in range(size)]
        self.counts = list(counts or [])
        self.fail_fetch = fail_fetch
        self.queries = []
        self.batch_sizes = []
    def cursor(self):
        return FakeCursor(self)
    def add_output_converter(self, *args):
        pass


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stdout = redirect_stdout(StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def test_default_sample_and_batch_size(self):
        args = raw.parse_args([])
        self.assertEqual((args.modo, args.batch_size), ('muestra', 500))
        with redirect_stdout(StringIO()), redirect_stderr_for_test():
            with self.assertRaises(SystemExit):
                raw.parse_args(['--batch-size', '0'])

    def test_sample_and_full_counts_and_csv_roundtrip(self):
        for mode, expected in [('muestra', 100), ('completo', 103)]:
            with self.subTest(mode=mode):
                connection = FakeConnection()
                report, directory = raw.run_extraction(connection, mode, 7, self.root)
                self.assertEqual(report['estado'], 'completado')
                self.assertTrue(all(size == 7 for size in connection.batch_sizes))
                for table, filename, _ in raw.TABLES:
                    result = report['tablas'][table]
                    self.assertEqual(result['filas_extraidas'], expected)
                    self.assertEqual(result['conteo_fuente_antes'], 103)
                    self.assertEqual(result['conteo_fuente_despues'], 103)
                    with (directory / filename).open(encoding='utf-8-sig', newline='') as stream:
                        records = list(csv.reader(stream, quoting=csv.QUOTE_NOTNULL))
                    self.assertEqual(len(records) - 1, expected)
                    self.assertEqual(records[1][1:], [None, '', 'ñ, "ficticio"\nsalto', '2016-01-01', '0x00ff'])
                selects = [q for q in connection.queries if 'COUNT_BIG' not in q]
                self.assertTrue(all(('TOP (100)' in q) == (mode == 'muestra') for q in selects))
                self.assertFalse(list(directory.glob('*.tmp')))

    def test_sample_smaller_than_100_is_not_a_failure(self):
        report, _ = raw.run_extraction(FakeConnection(3), raw_root=self.root)
        self.assertTrue(all(r['filas_esperadas'] == 3 for r in report['tablas'].values()))

    def test_empty_tables(self):
        report, _ = raw.run_extraction(FakeConnection(0), 'completo', raw_root=self.root)
        self.assertTrue(all(r['filas_extraidas'] == 0 for r in report['tablas'].values()))

    def test_runs_preserve_previous_files(self):
        legacy = self.root / 'Sales.Orders.csv'
        legacy.write_text('muestra ficticia anterior', encoding='utf-8')
        _, first = raw.run_extraction(FakeConnection(2), raw_root=self.root)
        before = (first / 'Sales.Orders.csv').read_bytes()
        _, second = raw.run_extraction(FakeConnection(3), raw_root=self.root)
        self.assertNotEqual(first, second)
        self.assertEqual((first / 'Sales.Orders.csv').read_bytes(), before)
        self.assertEqual(legacy.read_text(encoding='utf-8'), 'muestra ficticia anterior')

    def check_failure(self, connection, mode='completo'):
        with self.assertRaises((ValueError, OSError)):
            raw.run_extraction(connection, mode, 7, self.root)
        directory = next(p for p in self.root.iterdir() if p.is_dir())
        report = json.loads((directory / 'extraction_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(report['estado'], 'fallido')
        self.assertEqual(report['tablas']['Sales.Invoices']['estado'], 'fallido')
        self.assertFalse((directory / 'Sales.Invoices.csv').exists())
        self.assertFalse(list(directory.glob('*.tmp')))

    def test_count_mismatch_prevents_final_file(self):
        self.check_failure(FakeConnection(counts=[104]))

    def test_changed_source_count_prevents_final_file(self):
        self.check_failure(FakeConnection(counts=[103, 104]))

    def test_fetch_error_removes_temporary(self):
        self.check_failure(FakeConnection(fail_fetch=True))

    def test_sql_only_from_allowlist(self):
        with self.assertRaises(ValueError):
            raw.queries('Sales.Orders; DROP TABLE x', 'completo')
        with self.assertRaises(ValueError):
            raw.queries('Sales.Orders', 'otro')


def redirect_stderr_for_test():
    from contextlib import redirect_stderr
    return redirect_stderr(StringIO())


if __name__ == '__main__':
    unittest.main()
