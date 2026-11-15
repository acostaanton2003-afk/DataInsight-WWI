"""Orquestador con servicios simulados, sin SQL Server/Supabase ni datos reales."""
import io
import json
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout,redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'etl'))
import ejecutar_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/'data'
        self.events=[]
        self.connection=MagicMock()
        self.secret='PASSWORD=ficticio-secreto-no-log;host=privado'
        self.output=io.StringIO()
        self.capture=redirect_stdout(self.output);self.capture.__enter__()
        self.addCleanup(self.capture.__exit__,None,None,None)
        self.services=pipeline.Services(
            MagicMock(side_effect=self.connect),MagicMock(side_effect=self.extract),
            MagicMock(side_effect=self.validate),MagicMock(side_effect=self.prepare),MagicMock(side_effect=self.load))

    def connect(self):
        self.events.append('connect');print(self.secret)
        return self.connection

    def extract(self,connection,mode,batch_size,raw_root):
        self.events.append('raw');print(self.secret,file=sys.stderr)
        self.raw_id=uuid.uuid4().hex
        self.raw_dir=Path(raw_root)/self.raw_id;self.raw_dir.mkdir(parents=True)
        self.raw_report=dict(run_id=self.raw_id,modo=mode,estado='completado',tablas={
            table:dict(estado='completado',filas_extraidas=1,error=None) for table,_,_ in pipeline.TABLES})
        pipeline.save_manifest(self.raw_dir/'extraction_manifest.json',self.raw_report)
        return self.raw_report,self.raw_dir

    def validate(self,data_dir,raw_dir):
        self.events.append('validated')
        self.assertTrue(self.connection.close.called)
        self.assertEqual(raw_dir,self.raw_dir)
        self.valid_id=uuid.uuid4().hex
        self.validated_dir=Path(data_dir)/'validated'/self.valid_id;self.validated_dir.mkdir(parents=True)
        self.quality_path=Path(data_dir)/'reports'/(self.valid_id+'.json');self.quality_path.parent.mkdir()
        self.quality=dict(run_id=self.valid_id,estado='completado',raw_run_id=self.raw_id,
            raw_modo='completo',raw_dir=str(raw_dir),tablas={table:dict(leidas=1,validas=1,rechazadas=0,
                balance_correcto=True,errores={},validated_file=str(self.validated_dir/filename)) for table,filename,_ in pipeline.TABLES})
        pipeline.save_manifest(self.quality_path,self.quality)
        return self.quality,self.quality_path

    def prepare(self,validated_dir,quality_report,ready_root):
        self.events.append('ready')
        self.assertEqual(validated_dir,self.validated_dir);self.assertEqual(quality_report,self.quality_path)
        self.ready_id=uuid.uuid4().hex
        self.ready_dir=Path(ready_root)/self.ready_id;self.ready_dir.mkdir(parents=True)
        self.ready=dict(run_id=self.ready_id,estado='completado',raw_run_id=self.raw_id,
            validated_run_id=self.valid_id,validated_dir=str(validated_dir),quality_report=str(quality_report))
        pipeline.save_manifest(self.ready_dir/'reconciliacion.json',self.ready)
        return self.ready,self.ready_dir

    def load(self,ready_dir,execute,batch_size,report_root):
        self.events.append('dry_run');self.assertIs(execute,False);self.assertEqual(ready_dir,self.ready_dir)
        load_id=uuid.uuid4().hex;report_root=Path(report_root);report_root.mkdir()
        self.load_path=report_root/(load_id+'.json')
        self.loaded=dict(run_id=load_id,modo='dry-run',estado='dry_run_apto_para_carga',commit_confirmado=False,
            raw_run_id=self.raw_id,ready_run_id=self.ready_id,ready_dir=str(ready_dir))
        pipeline.save_manifest(self.load_path,self.loaded)
        return self.loaded,self.load_path,0

    def run_pipeline(self,**kwargs):
        return pipeline.run_pipeline(data_dir=self.root,services=self.services,**kwargs)

    def assert_stopped_before_ready(self,code=1):
        report,path,result=self.run_pipeline()
        self.assertEqual(result,code)
        self.services.prepare.assert_not_called();self.services.load.assert_not_called()
        self.assertEqual(report['etapas']['preparacion_ready']['estado'],'pendiente')
        self.assertFalse((self.root/'.pipeline.lock').exists())
        self.assertIsNotNone(path)
        return report,path

    def test_success_order_only_current_paths_and_dry_run(self):
        old=self.root/'raw'/'old';old.mkdir(parents=True)
        report,path,code=self.run_pipeline(batch_size=7)
        self.assertEqual(code,0);self.assertEqual(report['estado'],'completado_dry_run')
        self.assertEqual(self.events,['connect','raw','validated','ready','dry_run'])
        self.services.extract.assert_called_once_with(self.connection,mode='completo',batch_size=7,raw_root=path.parent/'raw')
        self.assertIs(self.services.load.call_args.kwargs['execute'],False)
        self.assertEqual(self.services.load.call_args.kwargs['batch_size'],7)
        self.assertNotEqual(self.raw_dir,old)
        for stage in report['etapas'].values():
            self.assertEqual(stage['estado'],'completado');self.assertGreaterEqual(stage['duracion_segundos'],0)
        self.connection.close.assert_called_once()
        self.connection.cursor.return_value.execute.assert_called_once_with('SET TRANSACTION ISOLATION LEVEL READ COMMITTED;')
        self.connection.cursor.return_value.close.assert_called_once()
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),report)
        self.assertNotIn(self.secret,self.output.getvalue());self.assertNotIn(self.secret,path.read_text())

    def test_new_run_does_not_overwrite_previous_or_select_latest(self):
        first,path1,_=self.run_pipeline();first_bytes=path1.read_bytes()
        second,path2,_=self.run_pipeline()
        self.assertNotEqual(first['pipeline_run_id'],second['pipeline_run_id'])
        self.assertNotEqual(path1,path2);self.assertEqual(path1.read_bytes(),first_bytes)
        self.assertNotEqual(first['etapas']['extraccion_raw']['run_id'],second['etapas']['extraccion_raw']['run_id'])

    def test_rejects_stop_even_with_completed_quality_status(self):
        def rejected(**kwargs):
            report,path=self.validate(**kwargs);item=report['tablas'][pipeline.TABLES[0][0]]
            item.update(validas=0,rechazadas=1,errores={'PK_DUPLICADA':1})
            pipeline.save_manifest(path,report);return report,path
        self.services.validate.side_effect=rejected
        report,_=self.assert_stopped_before_ready(2)
        self.assertEqual(report['estado'],'detenido_rechazos')
        self.assertEqual(report['etapas']['validacion_raw']['conteos']['rechazadas'],1)

    def test_errors_without_rejects_also_stop(self):
        def errors(**kwargs):
            report,path=self.validate(**kwargs);report['tablas'][pipeline.TABLES[0][0]]['errores']={'TIPO':1};return report,path
        self.services.validate.side_effect=errors
        self.assert_stopped_before_ready(2)

    def test_invalid_balance_missing_table_or_foreign_lineage_stop(self):
        for condition in ('balance','missing','foreign'):
            with self.subTest(condition=condition):
                self.services.prepare.reset_mock();self.services.load.reset_mock()
                def invalid(**kwargs):
                    report,path=self.validate(**kwargs)
                    if condition=='balance':report['tablas'][pipeline.TABLES[0][0]]['balance_correcto']=False
                    elif condition=='missing':del report['tablas'][pipeline.TABLES[0][0]]
                    else:report['raw_run_id']='old-run'
                    return report,path
                self.services.validate.side_effect=invalid
                self.assert_stopped_before_ready()

    def test_connection_or_extraction_failure_no_secrets_and_closes(self):
        self.services.extract.side_effect=RuntimeError(self.secret)
        report,path,code=self.run_pipeline()
        self.assertEqual(code,1);self.services.validate.assert_not_called()
        self.connection.close.assert_called_once()
        self.assertNotIn(self.secret,self.output.getvalue()+path.read_text())
        self.assertEqual(report['etapas']['extraccion_raw']['estado'],'fallido')
        self.services.connect.side_effect=RuntimeError(self.secret)
        _,_,code=self.run_pipeline();self.assertEqual(code,1)

    def test_sample_result_is_never_forwarded(self):
        def sample(*args,**kwargs):
            manifest,directory=self.extract(*args,**kwargs);manifest['modo']='muestra';return manifest,directory
        self.services.extract.side_effect=sample
        self.assert_stopped_before_ready()

    def test_foreign_raw_directory_is_rejected(self):
        def foreign(*args,**kwargs):
            manifest,_=self.extract(*args,**kwargs);other=self.root/'old'/manifest['run_id'];other.mkdir(parents=True);return manifest,other
        self.services.extract.side_effect=foreign
        self.assert_stopped_before_ready()

    def test_ready_exception_or_foreign_lineage_stops_before_loader(self):
        self.services.prepare.side_effect=ValueError(self.secret)
        report,path,code=self.run_pipeline()
        self.assertEqual(code,1);self.services.load.assert_not_called()
        self.assertNotIn(self.secret,self.output.getvalue()+path.read_text())
        def foreign(**kwargs):
            report,directory=self.prepare(**kwargs);report['validated_run_id']='old-run';return report,directory
        self.services.prepare.side_effect=foreign
        _,_,code=self.run_pipeline();self.assertEqual(code,1);self.services.load.assert_not_called()

    def test_loader_failure_nonzero_and_no_retry(self):
        def failure(**kwargs):
            report,path,_=self.load(**kwargs);report.update(estado='fallido',error=self.secret);return report,path,1
        self.services.load.side_effect=failure
        report,path,code=self.run_pipeline()
        self.assertEqual(code,1);self.services.load.assert_called_once()
        self.assertEqual(report['error'],'simulacion_dwh_fallida')
        self.assertNotIn(self.secret,path.read_text()+self.output.getvalue())

    def test_invalid_loader_status_commit_or_lineage_never_report_success(self):
        for field,value in [('estado','carga_confirmada'),('commit_confirmado',True),('modo','execute'),('raw_run_id','old-run'),('ready_run_id','old-ready')]:
            with self.subTest(field=field):
                def invalid(**kwargs):
                    report,path,_=self.load(**kwargs);report[field]=value;return report,path,0
                self.services.load.side_effect=invalid
                report,_,code=self.run_pipeline();self.assertEqual(code,1);self.assertEqual(report['estado'],'fallido')

    def test_interruption_stops_releases_lock_and_preserves_completed_stages(self):
        self.services.validate.side_effect=KeyboardInterrupt()
        report,path,code=self.run_pipeline()
        self.assertEqual(code,130);self.assertEqual(report['estado'],'interrumpido')
        self.assertEqual(report['etapas']['extraccion_raw']['estado'],'completado')
        self.assertEqual(report['etapas']['validacion_raw']['estado'],'interrumpido')
        self.services.prepare.assert_not_called();self.services.load.assert_not_called()
        self.assertTrue(self.raw_dir.exists());self.assertFalse((self.root/'.pipeline.lock').exists())
        self.assertEqual(json.loads(path.read_text())['estado'],'interrumpido')

    def test_concurrent_or_stale_lock_refuses_all_services(self):
        with pipeline.pipeline_lock(self.root/'.pipeline.lock','another-run'):
            original=(self.root/'.pipeline.lock').read_bytes()
            report,path,code=self.run_pipeline()
            self.assertEqual(code,3);self.assertEqual(report['estado'],'bloqueado');self.assertIsNone(path)
            self.services.connect.assert_not_called();self.services.extract.assert_not_called()
            self.assertEqual((self.root/'.pipeline.lock').read_bytes(),original)
        self.assertFalse((self.root/'.pipeline.lock').exists())

    def test_report_failure_aborts_without_connections_and_releases_lock(self):
        with patch.object(pipeline,'save_manifest',side_effect=OSError(self.secret)):
            report,_,code=self.run_pipeline()
        self.assertEqual(code,1);self.services.connect.assert_not_called()
        self.assertNotIn(self.secret,self.output.getvalue());self.assertFalse((self.root/'.pipeline.lock').exists())

    def test_cli_requires_full_confirmation_and_has_no_execute(self):
        self.assertEqual(pipeline.parse_args(['--modo','completo']).batch_size,500)
        self.assertTrue(pipeline.parse_args(['--modo','completo']).dry_run)
        for args in ([],['--modo','muestra'],['--modo','completo','--execute'],['--modo','completo','--batch-size','0']):
            with self.subTest(args=args),redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):pipeline.parse_args(args)
        with self.assertRaises(pipeline.PipelineError):self.run_pipeline(batch_size=0)
        self.services.connect.assert_not_called()

    def test_default_adapters_reuse_existing_functions(self):
        import conexion_sqlserver,extraer_raw,validar_raw,preparar_ready,cargar_dwh_supabase
        services=pipeline.default_services()
        self.assertIs(services.connect,conexion_sqlserver.conectar)
        self.assertIs(services.extract,extraer_raw.run_extraction)
        self.assertIs(services.validate,validar_raw.run_validation)
        self.assertIs(services.prepare,preparar_ready.prepare)
        self.assertIs(services.load,cargar_dwh_supabase.run)


if __name__=='__main__':unittest.main()
