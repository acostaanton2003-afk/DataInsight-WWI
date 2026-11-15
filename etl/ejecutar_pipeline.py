"""Orquestación manual completa; la última etapa siempre es dry-run, sin cargas."""
import argparse
import io
import json
import os
import re
import sys
import uuid
from contextlib import closing,contextmanager,redirect_stdout,redirect_stderr
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
from typing import Callable

from extraer_raw import TABLES,positive_int,save_manifest

ROOT=Path(__file__).resolve().parents[1]
STAGES=('extraccion_raw','validacion_raw','preparacion_ready','simulacion_dwh')
DRY_RUN_STATES={'dry_run_apto_para_carga','dry_run_ya_cargado_identico'}


class PipelineError(Exception):
    def __init__(self,code,exit_code=1):
        self.code=code
        self.exit_code=exit_code
        super().__init__(code)


@dataclass(frozen=True)
class Services:
    connect: Callable
    extract: Callable
    validate: Callable
    prepare: Callable
    load: Callable


def default_services():
    # Importar drivers solo al ejecutar, no para --help ni pruebas con mocks.
    from conexion_sqlserver import conectar
    from extraer_raw import run_extraction
    from validar_raw import run_validation
    from preparar_ready import prepare
    from cargar_dwh_supabase import run
    return Services(conectar,run_extraction,run_validation,prepare,run)


class DiscardOutput(io.TextIOBase):
    """No acumular logs de etapas ni exponer mensajes del driver."""
    def write(self,value):return len(value)
    def flush(self):pass


@contextmanager
def quiet_stage():
    with redirect_stdout(DiscardOutput()),redirect_stderr(DiscardOutput()):
        yield


def utc_now():return datetime.now(timezone.utc).isoformat()


@contextmanager
def pipeline_lock(path,run_id):
    """Creación exclusiva; no retirar automáticamente bloqueos potencialmente activos."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise PipelineError('pipeline_bloqueado',3) from None
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(pid=os.getpid(),pipeline_run_id=run_id,inicio_utc=utc_now())))
            stream.flush()
            # Mantener el descriptor hasta terminar; nadie debe borrar este archivo activo.
            yield
    finally:
        # Quitar solo el bloqueo de este proceso. Si fue sustituido, conservarlo.
        try:
            owner=json.loads(path.read_text(encoding='utf-8'))
            if owner.get('pipeline_run_id')==run_id and owner.get('pid')==os.getpid():path.unlink()
        except (OSError,ValueError):
            pass  # Un bloqueo residual requiere revisión manual; nunca adivinar su dueño.


def identifier(report):
    value=report.get('run_id')
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        raise PipelineError('identificador_etapa_invalido')
    return value


def execution_dir(value,parent,run_id):
    expected=Path(parent).resolve()/run_id
    actual=Path(value).resolve()
    if actual!=expected or not actual.is_dir():raise PipelineError('ruta_etapa_ajena')
    return actual


def report_file(value,parent,run_id):
    expected=Path(parent).resolve()/(run_id+'.json')
    actual=Path(value).resolve()
    if actual!=expected or not actual.is_file():raise PipelineError('reporte_etapa_ajeno')
    return actual


def run_pipeline(batch_size=500,data_dir=ROOT/'data',services=None):
    """Devuelve (reporte, ruta o None, código). Sin parámetro para escritura DWH."""
    if type(batch_size) is not int or batch_size<1:raise PipelineError('lote_invalido')
    if sys.version_info<(3,13):raise PipelineError('python_313_requerido')
    data_dir=Path(data_dir).resolve()
    pipeline_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex
    report=dict(pipeline_run_id=pipeline_id,modo='dry-run',extraccion='completo',batch_size=batch_size,
        estado='en_proceso',inicio_utc=utc_now(),etapas={name:{'estado':'pendiente'} for name in STAGES},error=None)
    path=None;started=perf_counter();exit_code=1
    try:
        with pipeline_lock(data_dir/'.pipeline.lock',pipeline_id):
            area=data_dir/'pipeline_runs'/pipeline_id
            area.mkdir(parents=True,exist_ok=False)
            path=area/'pipeline.json'
            save_manifest(path,report)
            def stage(name,action):
                entry=report['etapas'][name]
                entry.update(estado='en_proceso',inicio_utc=utc_now(),error=None)
                save_manifest(path,report)
                print('INICIO '+name,flush=True)
                start=perf_counter()
                try:
                    with quiet_stage():result=action(entry)
                    entry['estado']='completado'
                    return result
                except KeyboardInterrupt:
                    entry.update(estado='interrumpido',error='interrumpido_por_usuario')
                    raise
                except Exception as error:
                    entry.update(estado='fallido',error=error.code if isinstance(error,PipelineError) else 'error_'+name)
                    raise
                finally:
                    entry.update(fin_utc=utc_now(),duracion_segundos=round(perf_counter()-start,3))
                    save_manifest(path,report)
                    print(f"FIN {name}: {entry['estado']}; {entry['duracion_segundos']}s; error={entry['error']}",flush=True)
            try:
                def extraction(entry):
                    nonlocal services
                    if services is None:services=default_services()
                    entry['output_root']=str(area/'raw')
                    with closing(services.connect()) as connection:
                        # Misma configuración de sesión que extraer_raw.main; no cambia la base.
                        with closing(connection.cursor()) as cursor:
                            cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED;')
                        manifest,directory=services.extract(connection,mode='completo',batch_size=batch_size,raw_root=area/'raw')
                    raw_id=identifier(manifest)
                    directory=execution_dir(directory,area/'raw',raw_id)
                    if not (directory/'extraction_manifest.json').is_file() or manifest.get('estado')!='completado' or manifest.get('modo')!='completo' or manifest.get('error'):
                        raise PipelineError('extraccion_incompleta')
                    if set(manifest.get('tablas',{}))!={t for t,_,_ in TABLES} or any(manifest['tablas'][t].get('estado')!='completado' or manifest['tablas'][t].get('error') for t,_,_ in TABLES):
                        raise PipelineError('extraccion_incompleta')
                    entry.update(run_id=raw_id,directorio=str(directory),manifiesto=str(directory/'extraction_manifest.json'))
                    return manifest,directory
                raw,raw_dir=stage('extraccion_raw',extraction)

                def validation(entry):
                    quality,quality_path=services.validate(data_dir=area,raw_dir=raw_dir)
                    validation_id=identifier(quality)
                    quality_path=report_file(quality_path,area/'reports',validation_id)
                    if quality.get('estado')!='completado' or quality.get('raw_run_id')!=raw['run_id'] or quality.get('raw_modo')!='completo' or Path(quality.get('raw_dir','')).resolve()!=raw_dir:
                        raise PipelineError('linaje_validacion_invalido')
                    if set(quality.get('tablas',{}))!={t for t,_,_ in TABLES}:raise PipelineError('reporte_calidad_incompleto')
                    validated_dir=execution_dir(area/'validated'/validation_id,area/'validated',validation_id)
                    totals={'leidas':0,'validas':0,'rechazadas':0,'errores':0}
                    for table,filename,_ in TABLES:
                        item=quality['tablas'][table]
                        if Path(item.get('validated_file','')).resolve()!=validated_dir/filename:raise PipelineError('linaje_validacion_invalido')
                        if not all(type(item.get(key)) is int and item[key]>=0 for key in ('leidas','validas','rechazadas')):
                            raise PipelineError('reporte_calidad_inconsistente')
                        if item.get('balance_correcto') is not True or item['leidas']!=item['validas']+item['rechazadas'] or item['leidas']!=raw['tablas'][table]['filas_extraidas']:
                            raise PipelineError('balance_calidad_incorrecto')
                        errors=item.get('errores',{})
                        if not isinstance(errors,dict) or any(type(count) is not int or count<0 for count in errors.values()):raise PipelineError('reporte_calidad_inconsistente')
                        for key in ('leidas','validas','rechazadas'):totals[key]+=item[key]
                        totals['errores']+=sum(errors.values())
                    entry.update(run_id=validation_id,raw_run_id=raw['run_id'],directorio=str(validated_dir),reporte=str(quality_path),conteos=totals)
                    if totals['rechazadas'] or totals['errores']:raise PipelineError('registros_rechazados_o_errores_calidad',2)
                    return quality,quality_path,validated_dir
                quality,quality_path,validated_dir=stage('validacion_raw',validation)

                def preparation(entry):
                    ready,ready_dir=services.prepare(validated_dir=validated_dir,quality_report=quality_path,ready_root=area/'ready')
                    ready_id=identifier(ready)
                    ready_dir=execution_dir(ready_dir,area/'ready',ready_id)
                    if not (ready_dir/'reconciliacion.json').is_file() or ready.get('estado')!='completado' or ready.get('raw_run_id')!=raw['run_id'] or ready.get('validated_run_id')!=quality['run_id'] or Path(ready.get('validated_dir','')).resolve()!=validated_dir or Path(ready.get('quality_report','')).resolve()!=quality_path:
                        raise PipelineError('linaje_ready_invalido')
                    entry.update(run_id=ready_id,raw_run_id=raw['run_id'],validated_run_id=quality['run_id'],directorio=str(ready_dir),reporte=str(ready_dir/'reconciliacion.json'))
                    return ready,ready_dir
                ready,ready_dir=stage('preparacion_ready',preparation)

                def simulation(entry):
                    # Invariante: nunca inferir execute desde argumentos/env ni defaults del cargador.
                    loaded,load_path,code=services.load(ready_dir=ready_dir,execute=False,batch_size=batch_size,report_root=area/'load_reports')
                    load_id=identifier(loaded)
                    load_path=report_file(load_path,area/'load_reports',load_id)
                    entry.update(run_id=load_id,ready_run_id=ready['run_id'],raw_run_id=raw['run_id'],reporte=str(load_path))
                    if code!=0:raise PipelineError('simulacion_dwh_fallida')
                    if loaded.get('modo')!='dry-run' or loaded.get('commit_confirmado') is not False or loaded.get('estado') not in DRY_RUN_STATES:
                        raise PipelineError('resultado_dry_run_invalido')
                    if loaded.get('raw_run_id')!=raw['run_id'] or loaded.get('ready_run_id')!=ready['run_id'] or Path(loaded.get('ready_dir','')).resolve()!=ready_dir:
                        raise PipelineError('linaje_dwh_invalido')
                    entry['resultado']=loaded['estado']
                stage('simulacion_dwh',simulation)
                report['estado']='completado_dry_run';exit_code=0
            except KeyboardInterrupt:
                report.update(estado='interrumpido',error='interrumpido_por_usuario');exit_code=130
            except Exception as error:
                exit_code=error.exit_code if isinstance(error,PipelineError) else 1
                report.update(estado='detenido_rechazos' if exit_code==2 else 'fallido',error=error.code if isinstance(error,PipelineError) else 'error_pipeline')
            finally:
                report.update(fin_utc=utc_now(),duracion_segundos=round(perf_counter()-started,3))
                save_manifest(path,report)
    except KeyboardInterrupt:
        exit_code=130
        report.update(estado='interrumpido',error='interrumpido_por_usuario',fin_utc=utc_now(),duracion_segundos=round(perf_counter()-started,3))
        if path is not None:
            try:save_manifest(path,report)
            except OSError:pass
    except Exception as error:
        exit_code=error.exit_code if isinstance(error,PipelineError) else 1
        report.update(estado='bloqueado' if exit_code==3 else 'fallido',error=error.code if isinstance(error,PipelineError) else 'error_local_reporte_o_bloqueo',fin_utc=utc_now(),duracion_segundos=round(perf_counter()-started,3))
    print('Pipeline: '+report['estado']+'; error='+str(report['error']),flush=True)
    if path is not None:print(('Reporte: ' if path.is_file() else 'Reporte no guardado: ')+str(path),flush=True)
    return report,path,exit_code


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modo',choices=('completo',),required=True,help='Confirmación de extracción completa; READY no admite muestras.')
    parser.add_argument('--batch-size',type=positive_int,default=500)
    parser.add_argument('--dry-run',action='store_true',default=True,help='Siempre activo. Este orquestador no permite --execute.')
    return parser.parse_args(argv)


def main(argv=None):
    args=parse_args(argv)
    try:return run_pipeline(batch_size=args.batch_size)[2]
    except Exception:
        print('ERROR: no se pudo iniciar el pipeline; revise Python, lote y acceso local.',file=sys.stderr)
        return 1


if __name__=='__main__':sys.exit(main())
