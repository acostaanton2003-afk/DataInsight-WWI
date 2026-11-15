"""Carga controlada READY -> dwh. Dry-run predeterminado; escrituras solo con --execute."""

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

from preparar_ready import (ROOT, COLUMNS, TOLERANCE, stable_key, date_key, digest,
                            add_amounts, totals_dict, check_reference, dump_json)
from probar_conexion_supabase import load_configuration, open_connection
from validar_raw import read_records, batches

sys.path.insert(0,str(ROOT/'database/data-warehouse'))
from verificar_ready_ddl import ddl_contract, inspect, write_projection

ORDER = ('DimFecha','DimCliente','DimProducto','FactVentas','FactPedidos')
TABLES = dict(zip(ORDER,('dim_fecha','dim_cliente','dim_producto','fact_ventas','fact_pedidos')))
BUSINESS = {'DimFecha':'fecha','DimCliente':'customer_id','DimProducto':'stock_item_id','FactVentas':'invoice_line_id','FactPedidos':'order_id'}
FK = {'FactVentas':{'fecha_factura_key':'DimFecha','cliente_key':'DimCliente','producto_key':'DimProducto'},
      'FactPedidos':{'fecha_pedido_key':'DimFecha','fecha_entrega_prevista_key':'DimFecha','cliente_key':'DimCliente'}}


class LoadError(ValueError):
    """Codigo fijo seguro: nunca mensajes del driver ni valores de registros."""


def canonical(value,column):
    if value is None:
        return None
    kind=column['type']
    if kind in ('bigint','integer','smallint'):
        return int(value)
    if kind.startswith('numeric'):
        if isinstance(value,float):
            raise LoadError('importe_float_no_admitido')
        number=Decimal(value)
        if not number.is_finite():
            raise LoadError('importe_no_finito')
        with localcontext() as context:
            context.prec=50
            return '0' if number==0 else format(number.normalize(),'f')
    if kind=='boolean':
        if value not in (True,False,'true','false'):
            raise LoadError('boolean_invalido')
        return value is True or value=='true'
    if kind=='date':
        return value.isoformat() if isinstance(value,date) else date.fromisoformat(value).isoformat()
    return str(value)


def payload(row,columns):
    if len(row)!=len(columns):
        raise LoadError('numero_columnas_incorrecto')
    return json.dumps([canonical(value,column) for value,column in zip(row,columns)],ensure_ascii=True,separators=(',',':'))


def adapted(values,columns):
    result=[]
    for value,column in zip(values,columns):
        if value is not None and column['type'].startswith('numeric'):
            value=Decimal(value)
        elif value is not None and column['type']=='date':
            value=date.fromisoformat(value)
        result.append(value)
    return tuple(result)


class LocalPlan:
    """Indice técnico desechable en disco, no una capa staging del DWH."""
    def __init__(self,source,work):
        self.source=Path(source).resolve()
        self.work=Path(work)
        self.snapshot=self.work/'ready'
        self.snapshot.mkdir()
        manifest_path=self.source/'reconciliacion.json'
        manifest_hash=digest(manifest_path)
        shutil.copyfile(manifest_path,self.snapshot/'reconciliacion.json')
        if digest(self.snapshot/'reconciliacion.json')!=manifest_hash:
            raise LoadError('manifiesto_cambio')
        self.manifest=json.loads((self.snapshot/'reconciliacion.json').read_text(encoding='utf-8-sig'))
        if self.manifest.get('estado')!='completado' or not self.manifest.get('raw_run_id'):
            raise LoadError('ready_no_completado')
        for name in ('referencias_completas','claves_unicas_y_estables','conciliacion_fila_a_fila','totales','por_cliente','por_mes'):
            if self.manifest.get('controles',{}).get(name) is not True:
                raise LoadError('ready_sin_certificacion')
        for entity in ORDER:
            original=self.source/(entity+'.csv')
            before=digest(original)
            shutil.copyfile(original,self.snapshot/original.name)
            if before!=digest(self.snapshot/original.name) or before!=digest(original):
                raise LoadError('ready_cambio_durante_copia')
        if digest(manifest_path)!=manifest_hash:
            raise LoadError('manifiesto_cambio')
        self.inspection=inspect(self.snapshot)
        self.contract=ddl_contract()
        self.db=sqlite3.connect(self.work/'comprobaciones.sqlite')
        self.db.execute('PRAGMA cache_size=-2048')
        self.db.execute('PRAGMA journal_mode=OFF')
        self.db.execute('PRAGMA synchronous=OFF')
        self.db.executescript('''CREATE TABLE expected(entity TEXT,pk INTEGER,business TEXT,payload TEXT NOT NULL,
          PRIMARY KEY(entity,pk),UNIQUE(entity,business));
          CREATE TABLE compared(entity TEXT,pk INTEGER,PRIMARY KEY(entity,pk));
          CREATE TABLE invoices(id INTEGER PRIMARY KEY,order_id INTEGER,credit INTEGER,customer INTEGER,day INTEGER,billto INTEGER);
          CREATE INDEX invoice_order ON invoices(order_id);''')
        self.counts={}
        try:
            for entity in ORDER:
                count=0
                columns=self.contract[entity]
                names=[c['name'] for c in columns]
                for batch in batches(read_records(self.snapshot/(entity+'.csv'),names)):
                    for _,_,row in batch:
                        encoded=payload(row,columns)
                        values=json.loads(encoded)
                        business=values[names.index(BUSINESS[entity])]
                        try:
                            self.db.execute('INSERT INTO expected VALUES (?,?,?,?)',(entity,values[0],None if business is None else str(business),encoded))
                        except sqlite3.IntegrityError:
                            raise LoadError('clave_primaria_o_negocio_duplicada') from None
                        count+=1
                self.counts[entity]=count
                if count!=self.manifest['tablas'][entity]['filas']:
                    raise LoadError('conteo_ready_incorrecto')
            self.metrics,self.clients,self.months=self.validate_model()
            check_reference(self.metrics,self.manifest['metricas'])
            profiles=json.loads((ROOT/'etl/referencias_ready.json').read_text(encoding='utf-8'))
            reference=profiles.get(self.manifest['raw_run_id'])
            if reference:
                check_reference(self.metrics,reference['metricas'])
            self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def rows(self,entity,batch_size=500):
        cursor=self.db.execute('SELECT payload FROM expected WHERE entity=? ORDER BY pk',(entity,))
        while batch:=cursor.fetchmany(batch_size):
            for (encoded,) in batch:
                yield json.loads(encoded)

    def row_dicts(self,entity):
        for row in self.rows(entity):
            yield dict(zip(COLUMNS[entity],row))

    def has_business(self,entity,key):
        return self.db.execute('SELECT 1 FROM expected WHERE entity=? AND business=?',(entity,str(key))).fetchone() is not None

    def validate_model(self):
        dims={entity:{row[COLUMNS[entity][0]]:row for row in self.row_dicts(entity)} for entity in ORDER[:3]}
        for entity,namespace in (('DimCliente','cliente'),('DimProducto','producto')):
            for key,row in dims[entity].items():
                values=list(row.values())
                if key==0:
                    if values != [0,None,'Desconocido']+[None]*(len(values)-3):
                        raise LoadError('miembro_desconocido_incorrecto')
                elif values[1] is None or key!=stable_key(namespace,values[1]):
                    raise LoadError('clave_sustituta_incorrecta')
                elif row['raw_run_id']!=self.manifest['raw_run_id']:
                    raise LoadError('procedencia_incorrecta')
            if 0 not in dims[entity]:
                raise LoadError('falta_miembro_desconocido')
        dates=dims['DimFecha']
        for key,row in dates.items():
            if key==0:
                if list(row.values())!=[0,None,None,None,None,None]:
                    raise LoadError('fecha_desconocida_incorrecta')
            else:
                day=date.fromisoformat(row['fecha'])
                if key!=date_key(row['fecha']) or [row[c] for c in ('anio','mes','trimestre','dia')]!=[day.year,day.month,(day.month-1)//3+1,day.day]:
                    raise LoadError('calendario_incorrecto')
        if 0 not in dates:
            raise LoadError('falta_fecha_desconocida')
        clients=defaultdict(lambda:[Decimal(0)]*3)
        months=defaultdict(lambda:[Decimal(0)]*3)
        total=defaultdict(lambda:[Decimal(0)]*3)
        unknown={'clientes':0,'productos':0,'fechas':0}
        for entity in ('FactVentas','FactPedidos'):
            namespace='venta' if entity=='FactVentas' else 'pedido'
            for row in self.row_dicts(entity):
                if row[COLUMNS[entity][0]]!=stable_key(namespace,row[BUSINESS[entity]]) or row['raw_run_id']!=self.manifest['raw_run_id']:
                    raise LoadError('clave_o_procedencia_de_hecho_incorrecta')
                for fk,parent in FK[entity].items():
                    if row[fk] not in dims[parent]:
                        raise LoadError('referencia_dimensional_ausente')
                    if row[fk]==0:
                        unknown[{'DimCliente':'clientes','DimProducto':'productos','DimFecha':'fechas'}[parent]]+=1
                if entity=='FactVentas':
                    with localcontext() as context:
                        context.prec=50
                        base=Decimal(row['ventas_sin_impuestos'])
                        amounts=(base,Decimal(row['tax_amount']),Decimal(row['extended_price']))
                        if base!=Decimal(row['quantity'])*Decimal(row['unit_price']) or abs(amounts[2]-amounts[0]-amounts[1])>TOLERANCE:
                            raise LoadError('conciliacion_de_linea_incorrecta')
                    invoice=(row['invoice_id'],row['order_id'],int(row['is_credit_note']),row['cliente_key'],row['fecha_factura_key'],row['bill_to_customer_id_factura'])
                    previous=self.db.execute('SELECT * FROM invoices WHERE id=?',(invoice[0],)).fetchone()
                    if previous and previous!=invoice:
                        raise LoadError('cabecera_de_factura_inconsistente')
                    if not previous:
                        self.db.execute('INSERT INTO invoices VALUES (?,?,?,?,?,?)',invoice)
                    if not self.has_business('DimCliente',row['bill_to_customer_id_factura']):
                        raise LoadError('cliente_facturacion_ausente')
                    if row['order_id'] is not None and not self.has_business('FactPedidos',row['order_id']):
                        raise LoadError('pedido_de_factura_ausente')
                    if not row['is_credit_note']:
                        client=dims['DimCliente'][row['cliente_key']]['customer_id']
                        day=dates[row['fecha_factura_key']]['fecha']
                        if day is None:
                            raise LoadError('fecha_factura_sin_calendario')
                        add_amounts(total,'total',amounts)
                        add_amounts(clients,str(client),amounts)
                        add_amounts(months,day[:7],amounts)
                else:
                    number=self.db.execute('SELECT COUNT(*) FROM invoices WHERE order_id=?',(row['order_id'],)).fetchone()[0]
                    if row['cantidad_facturas']!=number or row['tiene_factura']!=(number>0):
                        raise LoadError('seguimiento_pedidos_incorrecto')
                    if row['backorder_order_id'] is not None and not self.has_business('FactPedidos',row['backorder_order_id']):
                        raise LoadError('backorder_ausente')
        for row in dims['DimCliente'].values():
            if row['cliente_key'] and not self.has_business('DimCliente',row['bill_to_customer_id_actual']):
                raise LoadError('bill_to_maestro_ausente')
        if unknown!=self.manifest['desconocidos_asignados']:
            raise LoadError('asignaciones_desconocidas_no_conciliadas')
        if totals_dict(clients)!=self.manifest['conciliacion_por_cliente'] or totals_dict(months)!=self.manifest['conciliacion_por_mes']:
            # Las cifras pueden tener distintas escalas textuales, no distinto valor.
            def numeric_groups(groups):
                return {str(k):tuple(Decimal(v) for v in values) for k,values in groups.items()}
            if numeric_groups(totals_dict(clients))!=numeric_groups(self.manifest['conciliacion_por_cliente']) or numeric_groups(totals_dict(months))!=numeric_groups(self.manifest['conciliacion_por_mes']):
                raise LoadError('conciliacion_agrupada_incorrecta')
        sums=total.get('total',[Decimal(0)]*3)
        without=sum(not row['tiene_factura'] for row in self.row_dicts('FactPedidos'))
        metrics={'fact_ventas_rows':self.counts['FactVentas'],'fact_pedidos_rows':self.counts['FactPedidos'],
                 'facturas_distintas':self.db.execute('SELECT COUNT(*) FROM invoices WHERE credit=0').fetchone()[0],
                 'pedidos_sin_factura':without,'meses':len(months),
                 'ventas_sin_impuestos':str(sums[0]),'impuestos':str(sums[1]),'ventas_con_impuestos':str(sums[2])}
        return metrics,clients,months


def destination_state(counts,expected):
    if all(value==0 for value in counts.values()):
        return 'vacio'
    if counts==expected:
        return 'comparar_contenido'
    raise LoadError('destino_parcial_o_conteos_distintos')


def compare_rows(plan,remote,batch_size):
    for entity in ORDER:
        number=0
        for row in remote.rows(entity,plan.contract[entity],batch_size):
            encoded=payload(row,plan.contract[entity])
            key=json.loads(encoded)[0]
            original=plan.db.execute('SELECT payload FROM expected WHERE entity=? AND pk=?',(entity,key)).fetchone()
            if original is None or original[0]!=encoded:
                raise LoadError('destino_con_datos_diferentes')
            try:
                plan.db.execute('INSERT INTO compared VALUES (?,?)',(entity,key))
            except sqlite3.IntegrityError:
                raise LoadError('clave_duplicada_en_destino') from None
            number+=1
        if number!=plan.counts[entity]:
            raise LoadError('destino_con_filas_faltantes')


class PostgreSQL:
    def __init__(self,execute):
        import psycopg
        self.connection=open_connection(load_configuration())
        try:
            self.connection.read_only=not execute
            self.connection.isolation_level=psycopg.IsolationLevel.READ_COMMITTED if execute else psycopg.IsolationLevel.REPEATABLE_READ
        except BaseException:
            self.connection.close()
            raise
        self.execute=execute
    def begin(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT set_config('statement_timeout','120000',true),set_config('lock_timeout','5000',true)")
            if self.execute:
                cursor.execute('LOCK TABLE '+','.join('dwh.'+TABLES[e] for e in ORDER)+' IN SHARE ROW EXCLUSIVE MODE NOWAIT')
    def validate_schema(self,contract):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::integer/10000")
            if cursor.fetchone()[0]!=17:
                raise LoadError('version_postgresql_incompatible')
            cursor.execute('''SELECT c.relname,c.relkind,c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user),
                row_security_active(c.oid),c.relhassubclass,
                EXISTS(SELECT 1 FROM pg_trigger t WHERE t.tgrelid=c.oid AND NOT t.tgisinternal AND t.tgenabled<>'D')
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=%s AND c.relname=ANY(%s)''',('dwh',list(TABLES.values())))
            tables={row[0]:row[1:] for row in cursor}
            if set(tables)!=set(TABLES.values()) or any(row!=('r',True,False,False,False) for row in tables.values()):
                raise LoadError('tablas_propiedad_rls_o_triggers_incompatibles')
            cursor.execute('''SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,
                pg_get_expr(d.adbin,d.adrelid)
                FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
                LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
                WHERE n.nspname=%s AND c.relname=ANY(%s) ORDER BY c.relname,a.attnum''',('dwh',list(TABLES.values())))
            actual=defaultdict(list)
            for table,*values in cursor:
                actual[table].append(values)
            expressions={'ventas_sin_impuestos':'quantity::numeric*unit_price','tiene_factura':'cantidad_facturas>0'}
            for entity,columns in contract.items():
                entries=actual[TABLES[entity]]
                if len(entries)!=len(columns):
                    raise LoadError('columnas_fisicas_incompatibles')
                for column,entry in zip(columns,entries):
                    name,kind,notnull,identity,generated,expression=entry
                    if (name,kind,notnull,identity,generated)!=(column['name'],column['type'],column['not_null'],'','s' if column['generated'] else ''):
                        raise LoadError('tipo_nulabilidad_o_generacion_incompatibles')
                    if column['generated']:
                        normalized=re.sub(r'[\s()]','',expression or '')
                        if normalized!=expressions[name]:
                            raise LoadError('expresion_generada_incompatible')
                    elif expression is not None:
                        raise LoadError('default_inesperado')
            cursor.execute('''SELECT c.relname,k.contype,k.conname,k.convalidated,k.condeferrable,
                ARRAY(SELECT a.attname::text FROM unnest(k.conkey) WITH ORDINALITY x(num,pos) JOIN pg_attribute a ON a.attrelid=k.conrelid AND a.attnum=x.num ORDER BY x.pos),
                rn.nspname,rc.relname,
                ARRAY(SELECT a.attname::text FROM unnest(k.confkey) WITH ORDINALITY x(num,pos) JOIN pg_attribute a ON a.attrelid=k.confrelid AND a.attnum=x.num ORDER BY x.pos),
                k.confdeltype,k.confupdtype,COALESCE(i.indisvalid,true)
                FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                LEFT JOIN pg_class rc ON rc.oid=k.confrelid LEFT JOIN pg_namespace rn ON rn.oid=rc.relnamespace
                LEFT JOIN pg_index i ON i.indexrelid=k.conindid
                WHERE n.nspname=%s AND c.relname=ANY(%s)''',('dwh',list(TABLES.values())))
            constraints=defaultdict(list)
            for row in cursor:
                constraints[row[0]].append(row[1:])
            checks={'dim_fecha':{'fecha_conocida_o_desconocida'},'dim_cliente':{'cliente_desconocido'},'dim_producto':{'producto_desconocido'},'fact_ventas':set(),'fact_pedidos':{'fact_pedidos_cantidad_facturas_check'}}
            for entity,columns in contract.items():
                rows=constraints[TABLES[entity]]
                expected_fk={(key,TABLES[parent],COLUMNS[parent][0]) for key,parent in FK.get(entity,{}).items()}
                p=[tuple(row[4]) for row in rows if row[0]=='p']
                u=[tuple(row[4]) for row in rows if row[0]=='u']
                f={(row[4][0],row[6],row[7][0]) for row in rows if row[0]=='f' and len(row[4])==len(row[7])==1 and row[5]=='dwh' and row[8]==row[9]=='a'}
                c={row[1] for row in rows if row[0]=='c'}
                if p!=[(columns[0]['name'],)] or u!=[(BUSINESS[entity],)] or f!=expected_fk or c!=checks[TABLES[entity]] or len(rows)!=2+len(expected_fk)+len(c) or any(not row[2] or row[3] or not row[10] for row in rows):
                    raise LoadError('restricciones_fisicas_incompatibles')
    def counts(self):
        with self.connection.cursor() as cursor:
            result={}
            for entity in ORDER:
                cursor.execute('SELECT COUNT(*) FROM dwh.'+TABLES[entity])
                result[entity]=cursor.fetchone()[0]
            return result
    def rows(self,entity,columns,batch_size):
        # Cursor de servidor: no descarga una tabla completa en RAM.
        with self.connection.cursor(name='lectura_'+TABLES[entity]) as cursor:
            cursor.execute('SELECT '+','.join(c['name'] for c in columns)+' FROM dwh.'+TABLES[entity]+' ORDER BY '+columns[0]['name'])
            while batch:=cursor.fetchmany(batch_size):
                yield from batch
    def copy(self,plan,entity,batch_size):
        columns=plan.contract[entity]
        projection=write_projection(columns)
        names=projection['columnas_escritura']
        indices=projection['posiciones_csv_base_0']
        with self.connection.cursor() as cursor:
            with cursor.copy('COPY dwh.'+TABLES[entity]+' ('+','.join(names)+') FROM STDIN') as writer:
                for row in plan.rows(entity,batch_size):
                    values=adapted(row,columns)
                    writer.write_row(tuple(values[i] for i in indices))
    def verify(self,plan):
        with self.connection.cursor() as cursor:
            if self.counts()!=plan.counts:
                raise LoadError('conteos_destino_no_conciliados')
            for entity,relations in FK.items():
                for column,parent in relations.items():
                    cursor.execute('SELECT COUNT(*) FROM dwh.'+TABLES[entity]+' f WHERE NOT EXISTS(SELECT 1 FROM dwh.'+TABLES[parent]+' d WHERE d.'+COLUMNS[parent][0]+'=f.'+column+')')
                    if cursor.fetchone()[0]:
                        raise LoadError('destino_con_referencias_huerfanas')
            cursor.execute('''SELECT COALESCE(SUM(ventas_sin_impuestos),0),COALESCE(SUM(tax_amount),0),COALESCE(SUM(extended_price),0),
                COUNT(DISTINCT invoice_id),COUNT(DISTINCT fecha_factura_key/100)
                FROM dwh.fact_ventas WHERE NOT is_credit_note''')
            base,tax,extended,invoices,months=cursor.fetchone()
            cursor.execute('SELECT COUNT(*) FROM dwh.fact_pedidos WHERE NOT tiene_factura')
            without=cursor.fetchone()[0]
            check_reference({'ventas_sin_impuestos':str(base),'impuestos':str(tax),'ventas_con_impuestos':str(extended),
                             'facturas_distintas':invoices,'meses':months,'pedidos_sin_factura':without},
                            {k:v for k,v in plan.metrics.items() if k not in ('fact_ventas_rows','fact_pedidos_rows')})
            cursor.execute('SELECT COUNT(*) FROM dwh.fact_ventas WHERE abs(extended_price-ventas_sin_impuestos-tax_amount)>%s',(TOLERANCE,))
            if cursor.fetchone()[0]:
                raise LoadError('destino_fuera_tolerancia_monetaria')
            cursor.execute('''SELECT c.customer_id,SUM(f.ventas_sin_impuestos),SUM(f.tax_amount),SUM(f.extended_price)
                FROM dwh.fact_ventas f JOIN dwh.dim_cliente c USING(cliente_key) WHERE NOT is_credit_note GROUP BY c.customer_id''')
            client={str(row[0]):list(row[1:]) for row in cursor}
            cursor.execute('''SELECT to_char(d.fecha,'YYYY-MM'),SUM(f.ventas_sin_impuestos),SUM(f.tax_amount),SUM(f.extended_price)
                FROM dwh.fact_ventas f JOIN dwh.dim_fecha d ON d.fecha_key=f.fecha_factura_key WHERE NOT is_credit_note GROUP BY to_char(d.fecha,'YYYY-MM')''')
            month={row[0]:list(row[1:]) for row in cursor}
            if client!=dict(plan.clients) or month!=dict(plan.months):
                raise LoadError('destino_no_concilia_cliente_o_mes')
    def commit(self): self.connection.commit()
    def rollback(self): self.connection.rollback()
    def close(self): self.connection.close()


def apply(plan,remote,execute=False,batch_size=500,progress=None):
    committed=False
    phase='inicio'
    try:
        remote.begin()
        phase='esquema'
        remote.validate_schema(plan.contract)
        counts=remote.counts()
        state=destination_state(counts,plan.counts)
        if state=='comparar_contenido':
            phase='comparacion'
            compare_rows(plan,remote,batch_size)
            remote.verify(plan)
            status='sin_cambios_ya_cargado' if execute else 'dry_run_ya_cargado_identico'
        elif not execute:
            status='dry_run_apto_para_carga'
        else:
            phase='copia'
            for entity in ORDER:
                remote.copy(plan,entity,batch_size)
                if progress:
                    progress(entity)
            phase='conciliacion'
            compare_rows(plan,remote,batch_size)
            remote.verify(plan)
            status='carga_confirmada'
        if execute:
            phase='commit'
            remote.commit()
            committed=True
        else:
            remote.rollback()
        return {'estado':status,'conteos_destino_previos':counts,'commit_confirmado':committed,'metricas_esperadas':plan.metrics}
    except Exception as error:
        try:
            remote.rollback()
        except Exception:
            pass
        if phase=='commit':
            raise LoadError('resultado_commit_desconocido_revisar_con_dry_run') from None
        if isinstance(error,LoadError):
            raise
        raise LoadError('error_remoto_'+phase) from None
    finally:
        try:
            remote.close()
        except Exception:
            pass


def run(ready_dir,execute=False,batch_size=500,report_root=ROOT/'data/load_reports',remote_factory=None):
    if sys.version_info<(3,13):
        raise LoadError('python_313_requerido')
    if batch_size<1:
        raise LoadError('lote_invalido')
    report_root=Path(report_root).resolve()
    report_root.mkdir(parents=True,exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex
    path=report_root/(run_id+'.json')
    report={'run_id':run_id,'modo':'execute' if execute else 'dry-run','estado':'iniciado','ready_dir':str(Path(ready_dir).resolve()),
            'inicio_utc':datetime.now(timezone.utc).isoformat(),'commit_confirmado':False}
    dump_json(path,report)
    phase='prevalidacion_local'
    try:
        with tempfile.TemporaryDirectory(prefix='.carga-',dir=report_root) as temporary:
            with closing(LocalPlan(ready_dir,temporary)) as plan:
                report.update(ready_run_id=plan.manifest['run_id'],raw_run_id=plan.manifest['raw_run_id'],
                              conteos_ready=plan.counts,campos_fisicos=56,campos_escritura=54,
                              hashes_ready={e:plan.manifest['tablas'][e]['sha256'] for e in ORDER})
                phase='conexion'
                remote=(remote_factory or PostgreSQL)(execute)
                phase='transaccion'
                report.update(apply(plan,remote,execute,batch_size))
        code=0
    except Exception as error:
        report['estado']='fallido'
        report['error']=str(error) if isinstance(error,LoadError) else 'error_'+phase
        code=1
    report['fin_utc']=datetime.now(timezone.utc).isoformat()
    try:
        dump_json(path,report)
    except OSError:
        report['estado']='commit_confirmado_reporte_local_no_guardado' if report['commit_confirmado'] else 'reporte_local_no_guardado'
        report.setdefault('error','reporte_local_no_guardado')
        code=1
    return report,path,code


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ready-dir',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',dest='execute',action='store_false')
    mode.add_argument('--execute',dest='execute',action='store_true')
    parser.set_defaults(execute=False)
    parser.add_argument('--batch-size',type=int,default=500)
    args=parser.parse_args(argv)
    if args.batch_size<1:
        parser.error('--batch-size debe ser positivo')
    return args


def main(argv=None):
    args=parse_args(argv)
    try:
        report,path,code=run(args.ready_dir,args.execute,args.batch_size)
        print('Estado: '+report['estado'])
        for entity,count in report.get('conteos_ready',{}).items():
            print(f'{TABLES[entity]}: READY={count}; destino previo={report.get("conteos_destino_previos",{}).get(entity,"no verificado")}')
        if code:
            print('Resultado: '+report['error'])
        print('Reporte: '+str(path))
        return code
    except Exception:
        print('Estado: fallo_local_sin_confirmacion_de_carga',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
