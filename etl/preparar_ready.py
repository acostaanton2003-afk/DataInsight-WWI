"""Transformación local VALIDATED -> READY; no conecta bases de datos externas."""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from extraer_raw import TABLES
from validar_raw import FIELD_LIMIT, TOLERANCE, batches, load_schema, parse_value, read_records

ROOT = Path(__file__).resolve().parents[1]
NAMESPACES = {'cliente': 1, 'producto': 2, 'venta': 3, 'pedido': 4}
COLUMNS = {
    'DimFecha': 'fecha_key fecha anio mes trimestre dia'.split(),
    'DimCliente': 'cliente_key customer_id customer_name bill_to_customer_id_actual customer_category_id buying_group_id account_opened_date payment_days is_on_credit_hold delivery_postal_code raw_run_id'.split(),
    'DimProducto': 'producto_key stock_item_id stock_item_name brand size barcode supplier_id color_id unit_package_id outer_package_id quantity_per_outer is_chiller_stock raw_run_id'.split(),
    'FactVentas': 'venta_key invoice_line_id fecha_factura_key cliente_key producto_key invoice_id order_id bill_to_customer_id_factura package_type_id is_credit_note quantity unit_price tax_rate tax_amount extended_price ventas_sin_impuestos raw_run_id'.split(),
    'FactPedidos': 'pedido_key order_id fecha_pedido_key fecha_entrega_prevista_key cliente_key backorder_order_id cantidad_facturas tiene_factura raw_run_id'.split(),
}
CLIENT_FIELDS = 'CustomerID CustomerName BillToCustomerID CustomerCategoryID BuyingGroupID AccountOpenedDate PaymentDays IsOnCreditHold DeliveryPostalCode'.split()
PRODUCT_FIELDS = 'StockItemID StockItemName Brand Size Barcode SupplierID ColorID UnitPackageID OuterPackageID QuantityPerOuter IsChillerStock'.split()
ORDER_FIELDS = 'OrderID CustomerID OrderDate ExpectedDeliveryDate BackorderOrderID'.split()
INVOICE_FIELDS = 'InvoiceID CustomerID BillToCustomerID OrderID InvoiceDate IsCreditNote'.split()
LINE_FIELDS = 'InvoiceLineID InvoiceID StockItemID PackageTypeID Quantity UnitPrice TaxRate TaxAmount ExtendedPrice'.split()


class ReadyError(ValueError):
    pass


def stable_key(entity, business_id):
    if not isinstance(business_id, int) or isinstance(business_id, bool) or not -(2**31) <= business_id < 2**31:
        raise ReadyError('La clave de negocio debe ser int32 no nula.')
    return (NAMESPACES[entity] << 32) | (business_id + 2**31)


def date_key(value):
    parsed = date.fromisoformat(value)
    return parsed.year * 10000 + parsed.month * 100 + parsed.day


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def signature(row):
    return hashlib.sha256(json.dumps([text(value) for value in row], ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


def dump_json(path, value):
    temporary = path.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def csv_output(directory, entity):
    final = directory / (entity + '.csv')
    temporary = final.with_suffix('.csv.tmp')
    try:
        with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream, quoting=csv.QUOTE_NOTNULL)
            writer.writerow(COLUMNS[entity])
            def write(row):
                if len(row) != len(COLUMNS[entity]):
                    raise ReadyError(f'{entity}: columna de salida incorrecta')
                writer.writerow([text(value) for value in row])
            yield write
        os.replace(temporary, final)
    finally:
        temporary.unlink(missing_ok=True)


def source_rows(path, schema, fields):
    names = [column['name'] for column in schema]
    selected = [(names.index(name), next(c for c in schema if c['name'] == name)) for name in fields]
    for batch in batches(read_records(path, names)):
        for record, _, values in batch:
            if len(values) != len(names):
                raise ReadyError(f'{path.name}: registro {record}, estructura inválida')
            row = {}
            for position, column in selected:
                value = values[position]
                if value is None:
                    if not column['nullable']:
                        raise ReadyError(f'{path.name}: registro {record}, {column["name"]} NULL obligatorio')
                    row[column['name']] = None
                else:
                    row[column['name']] = parse_value(value, column)
            yield row


def output_rows(directory, entity):
    for batch in batches(read_records(directory / (entity + '.csv'), COLUMNS[entity])):
        for _, _, row in batch:
            if len(row) != len(COLUMNS[entity]):
                raise ReadyError(f'{entity}: estructura de salida inválida')
            yield dict(zip(COLUMNS[entity], row))


def unique_insert(connection, statement, values, table, key):
    try:
        connection.execute(statement, values)
    except sqlite3.IntegrityError as error:
        raise ReadyError(f'{table}: clave duplicada {key}') from error


def add_amounts(aggregate, key, amounts):
    with localcontext() as context:
        context.prec = 50
        target = aggregate[key]
        for index, value in enumerate(amounts):
            target[index] += value


def totals_dict(aggregate):
    return {str(key): [format(value, 'f') for value in amounts] for key, amounts in sorted(aggregate.items())}


def check_reference(metrics, expected):
    errors = []
    for name, value in expected.items():
        actual = metrics.get(name)
        if name in ('ventas_sin_impuestos', 'impuestos', 'ventas_con_impuestos'):
            equal = actual is not None and Decimal(str(actual)) == Decimal(str(value))
        else:
            equal = actual == value
        if not equal:
            errors.append(f'{name}: obtenido={actual}, referencia={value}')
    if errors:
        raise ReadyError('Conciliación de referencia incorrecta: ' + '; '.join(errors))


def provenance(validated_dir, quality_path, profiles):
    quality = json.loads(quality_path.read_text(encoding='utf-8-sig'))
    if quality.get('estado') != 'completado' or quality.get('raw_modo') != 'completo' or quality.get('run_id') != validated_dir.name:
        raise ReadyError('Se requiere VALIDATED de una extracción completa con reporte terminado y run_id coincidente.')
    raw_id = quality['raw_run_id']
    raw_manifest = json.loads((Path(quality['raw_dir']) / 'extraction_manifest.json').read_text(encoding='utf-8-sig'))
    if raw_manifest.get('estado') != 'completado' or raw_manifest.get('modo') != 'completo' or raw_manifest.get('run_id') != raw_id:
        raise ReadyError('Manifiesto RAW incompleto, de muestra o de otra ejecución.')
    for table, filename, _ in TABLES:
        if raw_manifest['tablas'][table].get('estado') != 'completado':
            raise ReadyError(f'{table}: estado RAW no completado')
        entry = quality['tablas'][table]
        if Path(entry['validated_file']).resolve() != validated_dir / filename:
            raise ReadyError(f'{table}: directorio distinto del reporte VALIDATED')
        if entry['rechazadas'] != 0 or not entry['balance_correcto'] or entry['leidas'] != entry['validas'] or entry['leidas'] != raw_manifest['tablas'][table]['filas_extraidas']:
            raise ReadyError(f'{table}: cobertura incompleta; esta etapa exige extracción íntegra sin cuarentena.')
    return quality, profiles.get(raw_id)


def prepare(validated_dir, quality_report=None, ready_root=ROOT / 'data/ready', profiles=None):
    if sys.version_info < (3, 13):
        raise ReadyError('Se requiere Python 3.13+ para leer NULL de CSV.')
    csv.field_size_limit(FIELD_LIMIT)
    validated_dir = Path(validated_dir).resolve()
    quality_path = Path(quality_report).resolve() if quality_report else validated_dir.parent.parent / 'reports' / (validated_dir.name + '.json')
    ready_root = Path(ready_root).resolve()
    ready_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    report = {'run_id': run_id, 'estado': 'en_proceso', 'validated_dir': str(validated_dir),
              'quality_report': str(quality_path), 'key_scheme': 'wwi-int32-namespaces-v1',
              'inicio_utc': datetime.now(timezone.utc).isoformat(), 'errores': [], 'relaciones': {}}
    try:
        if profiles is None:
            profiles = json.loads((ROOT / 'etl/referencias_ready.json').read_text(encoding='utf-8'))
        quality, reference = provenance(validated_dir, quality_path, profiles)
        raw_id = quality['raw_run_id']
        report.update(raw_run_id=raw_id, validated_run_id=quality['run_id'], referencia_aplicada=raw_id if reference else None)
        schema = load_schema()['tables']
        with tempfile.TemporaryDirectory(prefix='.ready-', dir=ready_root) as temporary:
            work = Path(temporary)
            snapshots, output = work / 'inputs', work / 'output'
            snapshots.mkdir()
            output.mkdir()
            report['entradas'] = {}
            for table, filename, _ in TABLES:
                original = validated_dir / filename
                before = digest(original)
                snapshot = snapshots / filename
                shutil.copyfile(original, snapshot)
                copied = digest(snapshot)
                if before != copied or digest(original) != copied:
                    raise ReadyError(f'{table}: cambió durante la copia')
                if reference and copied != reference['validated_sha256'][table]:
                    raise ReadyError(f'{table}: hash distinto de la extracción de referencia')
                report['entradas'][table] = {'sha256': copied, 'filas_esperadas': quality['tablas'][table]['validas']}
            with closing(sqlite3.connect(work / 'indices.sqlite')) as db:
                # Caché desechable local. Nunca son tablas del Data Warehouse.
                db.execute('PRAGMA cache_size=-2048')
                db.execute('PRAGMA journal_mode=OFF')
                db.execute('PRAGMA synchronous=OFF')
                db.executescript('''CREATE TABLE customers(id INTEGER PRIMARY KEY,bill_to INTEGER);
                    CREATE TABLE products(id INTEGER PRIMARY KEY);
                    CREATE TABLE orders(id INTEGER PRIMARY KEY,customer INTEGER,day TEXT,expected TEXT,backorder INTEGER);
                    CREATE TABLE invoices(id INTEGER PRIMARY KEY,customer INTEGER,bill_to INTEGER,order_id INTEGER,day TEXT,credit INTEGER);
                    CREATE INDEX invoice_order ON invoices(order_id);
                    CREATE TABLE line_keys(id INTEGER PRIMARY KEY,signature TEXT,invoice_id INTEGER,credit INTEGER);
                    CREATE INDEX line_invoice ON line_keys(invoice_id);
                    CREATE TABLE order_keys(id INTEGER PRIMARY KEY,signature TEXT);
                    CREATE TABLE seen_lines(id INTEGER PRIMARY KEY);
                    CREATE TABLE seen_orders(id INTEGER PRIMARY KEY); CREATE TABLE seen_invoices(id INTEGER PRIMARY KEY);
                    CREATE TABLE dates(id INTEGER PRIMARY KEY,day TEXT UNIQUE);''')
                customers, products = {}, {}
                dates = set()
                counts = {}
                for entity, table, fields, target, namespace in (
                    ('DimCliente','Sales.Customers',CLIENT_FIELDS,customers,'cliente'),
                    ('DimProducto','Warehouse.StockItems',PRODUCT_FIELDS,products,'producto')):
                    for row in source_rows(snapshots / (table + '.csv'), schema[table], fields):
                        key = row[fields[0]]
                        if key in target:
                            raise ReadyError(f'{table}: clave duplicada {key}')
                        values = [stable_key(namespace,key)] + [row[name] for name in fields] + [raw_id]
                        target[key] = values
                        if entity == 'DimCliente':
                            db.execute('INSERT INTO customers VALUES (?,?)', (key,row['BillToCustomerID']))
                        else:
                            db.execute('INSERT INTO products VALUES (?)', (key,))
                    counts[table] = len(target)
                for table, fields in (('Sales.Orders',ORDER_FIELDS),('Sales.Invoices',INVOICE_FIELDS)):
                    count = 0
                    for row in source_rows(snapshots / (table + '.csv'), schema[table], fields):
                        values = [row[name] for name in fields]
                        if table == 'Sales.Orders':
                            # Cache ordenada: id,cliente,fecha,fecha prevista,backorder.
                            values[2:4] = [value.isoformat() for value in values[2:4]]
                            unique_insert(db,'INSERT INTO orders VALUES (?,?,?,?,?)',values,table,row['OrderID'])
                            dates.update(values[2:4])
                        else:
                            # Cache: id,cliente,bill_to,order_id,fecha,credit.
                            values[4] = values[4].isoformat()
                            unique_insert(db,'INSERT INTO invoices VALUES (?,?,?,?,?,?)',values,table,row['InvoiceID'])
                            dates.add(values[4])
                        count += 1
                    counts[table] = count
                relationships = {
                    'Customers.BillToCustomerID': 'SELECT COUNT(*) FROM customers c WHERE NOT EXISTS(SELECT 1 FROM customers p WHERE p.id=c.bill_to)',
                    'Orders.CustomerID': 'SELECT COUNT(*) FROM orders o WHERE NOT EXISTS(SELECT 1 FROM customers c WHERE c.id=o.customer)',
                    'Orders.BackorderOrderID': 'SELECT COUNT(*) FROM orders o WHERE o.backorder IS NOT NULL AND NOT EXISTS(SELECT 1 FROM orders p WHERE p.id=o.backorder)',
                    'Invoices.CustomerID': 'SELECT COUNT(*) FROM invoices i WHERE NOT EXISTS(SELECT 1 FROM customers c WHERE c.id=i.customer)',
                    'Invoices.BillToCustomerID': 'SELECT COUNT(*) FROM invoices i WHERE NOT EXISTS(SELECT 1 FROM customers c WHERE c.id=i.bill_to)',
                    'Invoices.OrderID': 'SELECT COUNT(*) FROM invoices i WHERE i.order_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.id=i.order_id)',
                }
                for name, sql in relationships.items():
                    report['relaciones'][name] = db.execute(sql).fetchone()[0]
                if any(report['relaciones'].values()):
                    raise ReadyError('Referencias ausentes entre cabeceras/maestros; ver relaciones del reporte.')
                for entity, source in (('DimCliente',customers),('DimProducto',products)):
                    with csv_output(output,entity) as write:
                        unknown = [None] * len(COLUMNS[entity])
                        unknown[0], unknown[2] = 0, 'Desconocido'
                        write(unknown)
                        for key in sorted(source):
                            write(source[key])
                with csv_output(output,'DimFecha') as write:
                    write([0,None,None,None,None,None])
                    if dates:
                        current, last = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
                        while True:
                            key = date_key(current.isoformat())
                            db.execute('INSERT INTO dates VALUES (?,?)', (key,current.isoformat()))
                            write([key,current,current.year,current.month,(current.month-1)//3+1,current.day])
                            if current == last:
                                break
                            current += timedelta(days=1)
                source_client, source_month = defaultdict(lambda: [Decimal(0)]*3), defaultdict(lambda: [Decimal(0)]*3)
                source_total = defaultdict(lambda: [Decimal(0)]*3)
                counts['Sales.InvoiceLines'] = 0
                missing = {'InvoiceLines.InvoiceID': 0, 'InvoiceLines.StockItemID': 0}
                missing_examples = []
                with csv_output(output,'FactVentas') as write:
                    for row in source_rows(snapshots / 'Sales.InvoiceLines.csv', schema['Sales.InvoiceLines'], LINE_FIELDS):
                        line_id = row['InvoiceLineID']
                        invoice = db.execute('SELECT * FROM invoices WHERE id=?',(row['InvoiceID'],)).fetchone()
                        product = products.get(row['StockItemID'])
                        counts['Sales.InvoiceLines'] += 1
                        # Duplicados se detectan también si la línea tiene referencia ausente.
                        unique_insert(db,'INSERT INTO line_keys VALUES (?,?,?,?)',(line_id,None,row['InvoiceID'],invoice[5] if invoice else None),'InvoiceLines',line_id)
                        if invoice is None or product is None:
                            missing['InvoiceLines.InvoiceID'] += int(invoice is None)
                            missing['InvoiceLines.StockItemID'] += int(product is None)
                            if len(missing_examples) < 20:
                                missing_examples.append({'InvoiceLineID': line_id,'InvoiceID':row['InvoiceID'],'StockItemID':row['StockItemID']})
                            continue
                        if row['UnitPrice'] is None:
                            raise ReadyError(f'InvoiceLines {line_id}: UnitPrice NULL; no se sustituye por cero')
                        with localcontext() as context:
                            context.prec = 50
                            base = Decimal(row['Quantity']) * row['UnitPrice']
                            if abs(row['ExtendedPrice'] - base - row['TaxAmount']) > TOLERANCE:
                                raise ReadyError(f'InvoiceLines {line_id}: diferencia monetaria > {TOLERANCE} provisional')
                        amounts = (base,row['TaxAmount'],row['ExtendedPrice'])
                        values = [stable_key('venta',line_id),line_id,date_key(invoice[4]),stable_key('cliente',invoice[1]),product[0],
                                  invoice[0],invoice[3],invoice[2],row['PackageTypeID'],bool(invoice[5]),row['Quantity'],
                                  row['UnitPrice'],row['TaxRate'],row['TaxAmount'],row['ExtendedPrice'],base,raw_id]
                        db.execute('UPDATE line_keys SET signature=? WHERE id=?',(signature(values),line_id))
                        write(values)
                        if not invoice[5]:
                            add_amounts(source_total,'total',amounts)
                            add_amounts(source_client,invoice[1],amounts)
                            add_amounts(source_month,invoice[4][:7],amounts)
                report['relaciones'].update(missing)
                report['ejemplos_referencias_ausentes'] = missing_examples
                if any(missing.values()):
                    raise ReadyError('Líneas con referencias ausentes; no se asigna el miembro desconocido ni se publica READY.')
                for table, count in counts.items():
                    if count != quality['tablas'][table]['validas']:
                        raise ReadyError(f'{table}: conteo distinto de VALIDATED')
                if db.execute('SELECT COUNT(*) FROM invoices i WHERE NOT EXISTS(SELECT 1 FROM line_keys l WHERE l.invoice_id=i.id)').fetchone()[0]:
                    raise ReadyError('Existen facturas sin líneas; el modelo actual no puede conservar su conteo de cabeceras.')
                with csv_output(output,'FactPedidos') as write:
                    for row in db.execute('SELECT o.*,COUNT(i.id) FROM orders o LEFT JOIN invoices i ON i.order_id=o.id GROUP BY o.id ORDER BY o.id'):
                        oid, customer, day, expected, backorder, number = row
                        values = [stable_key('pedido',oid),oid,date_key(day),date_key(expected),stable_key('cliente',customer),backorder,number,number>0,raw_id]
                        db.execute('INSERT INTO order_keys VALUES (?,?)',(oid,signature(values)))
                        write(values)
                # Releer los cinco CSV publicados SOLO en el directorio privado de trabajo.
                result = verify_outputs(output,db,customers,products,raw_id,source_total,source_client,source_month)
                if result['fact_ventas_rows'] != counts['Sales.InvoiceLines'] or result['fact_pedidos_rows'] != counts['Sales.Orders']:
                    raise ReadyError('Los hechos no conservan los conteos de entrada')
                if reference:
                    check_reference(result,reference['metricas'])
                report.update(metricas=result, filas_entrada=counts,
                              conciliacion_por_cliente=totals_dict(source_client), conciliacion_por_mes=totals_dict(source_month))
                report['tablas'] = {entity:{'archivo':entity+'.csv','filas':sum(1 for _ in output_rows(output,entity)),
                                            'sha256':digest(output / (entity+'.csv'))} for entity in COLUMNS}
            for table, filename, _ in TABLES:
                if digest(validated_dir / filename) != report['entradas'][table]['sha256']:
                    raise ReadyError(f'{table}: entrada cambió durante la transformación')
            report.update(estado='completado', fin_utc=datetime.now(timezone.utc).isoformat(),
                          controles={'referencias_completas':True,'claves_unicas_y_estables':True,'conciliacion_fila_a_fila':True,
                                     'totales':True,'por_cliente':True,'por_mes':True,'referencia_historica':True if reference else 'no_aplica_run_sin_perfil'},
                          desconocidos_asignados={'clientes':0,'productos':0,'fechas':0})
            dump_json(output / 'reconciliacion.json',report)
            final = ready_root / run_id
            if final.exists():
                raise ReadyError('El directorio de ejecución ya existe; no se sobrescribe.')
            os.replace(output,final)
        return report,final
    except Exception as error:
        report.update(estado='fallido',fin_utc=datetime.now(timezone.utc).isoformat())
        report['errores'].append(str(error))
        failures = ready_root / 'failures'
        failures.mkdir(exist_ok=True)
        dump_json(failures / (run_id + '.json'),report)
        raise ReadyError(f'{error}. Reporte de fallo: {failures / (run_id + ".json")}') from error


def verify_outputs(output,db,customers,products,raw_id,source_total,source_client,source_month):
    for entity, expected in (('DimCliente',customers),('DimProducto',products)):
        seen = set()
        for row in output_rows(output,entity):
            values = [row[name] for name in COLUMNS[entity]]
            key = int(values[0])
            if key in seen:
                raise ReadyError(f'{entity}: clave duplicada de salida')
            seen.add(key)
            if key == 0:
                unknown = [None] * len(values)
                unknown[0],unknown[2] = '0','Desconocido'
                expected_values = unknown
            else:
                expected_values = [text(value) for value in expected[int(values[1])]]
            if values != expected_values:
                raise ReadyError(f'{entity}: atributo/clave no coincide con VALIDATED')
        if len(seen) != len(expected)+1 or 0 not in seen:
            raise ReadyError(f'{entity}: cobertura incompleta')
    seen_dates = set()
    for row in output_rows(output,'DimFecha'):
        key = int(row['fecha_key'])
        if key in seen_dates:
            raise ReadyError('DimFecha: clave duplicada')
        seen_dates.add(key)
        if key == 0:
            if any(row[c] is not None for c in COLUMNS['DimFecha'][1:]):
                raise ReadyError('DimFecha: desconocido incorrecto')
        else:
            day = date.fromisoformat(row['fecha'])
            if (key,row['fecha']) != db.execute('SELECT id,day FROM dates WHERE id=?',(key,)).fetchone() or [row[c] for c in COLUMNS['DimFecha'][2:]] != list(map(str,[day.year,day.month,(day.month-1)//3+1,day.day])):
                raise ReadyError('DimFecha: calendario incorrecto')
    if len(seen_dates) != db.execute('SELECT COUNT(*) FROM dates').fetchone()[0]+1 or 0 not in seen_dates:
        raise ReadyError('DimFecha: faltan fechas')
    target_total = defaultdict(lambda: [Decimal(0)]*3)
    target_client = defaultdict(lambda: [Decimal(0)]*3)
    target_month = defaultdict(lambda: [Decimal(0)]*3)
    sales_count = 0
    client_keys = {v[0] for v in customers.values()}
    product_keys = {v[0] for v in products.values()}
    for row in output_rows(output,'FactVentas'):
        identifier = int(row['invoice_line_id'])
        original = db.execute('SELECT signature FROM line_keys WHERE id=?',(identifier,)).fetchone()
        if original is None or original[0] != signature([row[name] for name in COLUMNS['FactVentas']]):
            raise ReadyError(f'FactVentas {identifier}: pérdida o alteración de una fila')
        unique_insert(db,'INSERT INTO seen_lines VALUES (?)',(identifier,),'FactVentas',identifier)
        invoice = db.execute('SELECT * FROM invoices WHERE id=?',(int(row['invoice_id']),)).fetchone()
        client = int(row['cliente_key'])
        if client != stable_key('cliente',invoice[1]) or client not in client_keys or int(row['producto_key']) not in product_keys or int(row['fecha_factura_key']) not in seen_dates:
            raise ReadyError('FactVentas: FK incorrecta o cliente distinto del comercial')
        amounts = tuple(Decimal(row[name]) for name in ('ventas_sin_impuestos','tax_amount','extended_price'))
        with localcontext() as context:
            context.prec = 50
            if amounts[0] != Decimal(row['quantity']) * Decimal(row['unit_price']) or abs(amounts[2]-amounts[0]-amounts[1]) > TOLERANCE:
                raise ReadyError('FactVentas: fórmula monetaria incorrecta')
        if row['is_credit_note'] == 'false':
            db.execute('INSERT OR IGNORE INTO seen_invoices VALUES (?)',(invoice[0],))
            add_amounts(target_total,'total',amounts)
            add_amounts(target_client,invoice[1],amounts)
            day = db.execute('SELECT day FROM dates WHERE id=?',(int(row['fecha_factura_key']),)).fetchone()[0]
            add_amounts(target_month,day[:7],amounts)
        sales_count += 1
    if source_total != target_total or source_client != target_client or source_month != target_month:
        raise ReadyError('No coinciden los importes generales, por cliente o por mes contra VALIDATED')
    orders_count, without_invoice = 0,0
    client_keys = {v[0] for v in customers.values()}
    for row in output_rows(output,'FactPedidos'):
        identifier = int(row['order_id'])
        original = db.execute('SELECT signature FROM order_keys WHERE id=?',(identifier,)).fetchone()
        if original is None or original[0] != signature([row[name] for name in COLUMNS['FactPedidos']]):
            raise ReadyError('FactPedidos: fila distinta de VALIDATED/Invoices')
        unique_insert(db,'INSERT INTO seen_orders VALUES (?)',(identifier,),'FactPedidos',identifier)
        if int(row['cliente_key']) not in client_keys or any(int(row[c]) not in seen_dates for c in ('fecha_pedido_key','fecha_entrega_prevista_key')):
            raise ReadyError('FactPedidos: FK dimensional incorrecta')
        number = int(row['cantidad_facturas'])
        if row['tiene_factura'] != text(number>0):
            raise ReadyError('FactPedidos: indicador de factura incorrecto')
        without_invoice += int(number==0)
        orders_count += 1
    if without_invoice != db.execute('SELECT COUNT(*) FROM orders o WHERE NOT EXISTS(SELECT 1 FROM invoices i WHERE i.order_id=o.id)').fetchone()[0]:
        raise ReadyError('FactPedidos: no coincide el total de pedidos sin factura')
    if db.execute('SELECT COUNT(*) FROM seen_invoices').fetchone()[0] != db.execute('SELECT COUNT(*) FROM invoices WHERE credit=0').fetchone()[0]:
        raise ReadyError('FactVentas: no conserva el conteo de facturas ordinarias')
    totals = target_total.get('total',[Decimal(0)]*3)
    return {'fact_ventas_rows':sales_count,'fact_pedidos_rows':orders_count,
            'facturas_distintas':db.execute('SELECT COUNT(*) FROM seen_invoices').fetchone()[0],
            'pedidos_sin_factura':without_invoice,'meses':len(target_month),
            'ventas_sin_impuestos':str(totals[0]),'impuestos':str(totals[1]),'ventas_con_impuestos':str(totals[2])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validated-dir',type=Path,required=True)
    parser.add_argument('--quality-report',type=Path,default=None)
    args = parser.parse_args(argv)
    try:
        report,directory = prepare(args.validated_dir,args.quality_report)
        print(f'READY completado: {directory}')
        for entity, result in report['tablas'].items():
            print(f'{entity}: {result["filas"]} filas')
        print(json.dumps(report['metricas'],ensure_ascii=True,indent=2))
        return 0
    except (ReadyError,OSError) as error:
        print(f'ERROR: {error}',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
