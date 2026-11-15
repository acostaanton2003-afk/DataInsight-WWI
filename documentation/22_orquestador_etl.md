# Orquestador ETL manual (etapa 22)

## Alcance

`etl/ejecutar_pipeline.py` encadena las cuatro etapas existentes, sin replicar extracción, reglas de calidad, transformación o conciliación. No es un scheduler, no se conecta desde FastAPI y no modifica backend, frontend, asistente, ML ni configuración de bases de datos. No añade dependencias: Python 3.13 y etl/requirements.txt ya existentes.

| Orden | Función reutilizada | Contrato de entrada/salida |
| --- | --- | --- |
| 1 | extraer_raw.run_extraction | Conexión de conexion_sqlserver.conectar; devuelve manifiesto y directorio RAW nuevo |
| 2 | validar_raw.run_validation | Recibe explícitamente ese RAW; devuelve reporte y ruta de calidad nuevos |
| 3 | preparar_ready.prepare | Recibe VALIDATED identificado por el reporte anterior y quality_report explícito; devuelve READY nuevo |
| 4 | cargar_dwh_supabase.run | Recibe únicamente ese READY, siempre execute=False; devuelve reporte y código del dry-run |

El orquestador mantiene la misma configuración de sesión READ COMMITTED de extraer_raw.main y cierra SQL Server antes de validar archivos. No modifica datos del origen ni sus opciones persistentes. La consistencia sigue siendo por consulta, no una instantánea común frente a cambios concurrentes: los conteos de extracción no garantizan ausencia de cambios con igual número de filas.

## Ejecución PowerShell desde la raíz

Requisitos: .venv con Python 3.13, ODBC y las conexiones existentes. Si faltan dependencias, instalarlas como en las etapas anteriores:

```powershell
.\.venv\Scripts\python.exe -m pip install -r etl/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_ejecutar_pipeline.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
.\.venv\Scripts\python.exe etl/ejecutar_pipeline.py --help
```

Para ejecutar deliberadamente una extracción completa y llegar hasta la simulación:

```powershell
.\.venv\Scripts\python.exe etl/ejecutar_pipeline.py --modo completo --dry-run --batch-size 500
$LASTEXITCODE
```

`--modo completo` es obligatorio para evitar lecturas pesadas accidentales. READY exige datos completos; el orquestador no acepta muestra. El script independiente extraer_raw.py conserva su muestra predeterminada sin cambios.

`--dry-run` puede omitirse porque es siempre activo. **No existe --execute** en este comando: se rechaza antes de conectar o iniciar etapas. No hay una variable de entorno que cambie ese comportamiento. El paso final pasa execute=False explícitamente, sin depender del default del cargador.

Para muestras técnicas seguir utilizando los scripts independientes de etapas 6–8; no usar muestras independientes para preparar READY ni para comprobar relaciones completas.

## Configuración existente, sin credenciales nuevas

La extracción reutiliza conexion_sqlserver.conectar con autenticación integrada y SQLSERVER_* del entorno del proceso. Como antes, este conector no carga automáticamente el .env raíz. No se agregó otro lector ni se sobrescriben variables.

La simulación reutiliza la configuración SUPABASE_DB_* del ETL y el comportamiento de cargar_dwh_supabase.py. No utiliza BACKEND_DB_* ni credenciales del asistente. El cargador exige el contrato/permisos ya documentados en etapa 13; no se cambian roles, RLS o privilegios para pasar el preflight.

Dry-run puede leer Supabase: abre transacción READ ONLY/REPEATABLE READ, inspecciona metadatos y compara contenido con el plan local, termina con rollback, sin COPY/INSERT/UPDATE/DELETE/TRUNCATE ni commit. Su configuración de timeout es local a la sesión y se conserva. No significa «sin conexión» ni «sin crear archivos locales».

No se implementó escritura real en el orquestador. Cualquier futura integración con --execute requiere autorización explícita y revisión separada. Un dry-run apto no es autorización para cargar ni reserva el estado remoto.

## Ejecuciones aisladas y linaje

Cada invocación que obtiene el bloqueo crea un pipeline_run_id único. Todas sus salidas quedan bajo un área nueva, utilizando los parámetros de salida ya soportados por las funciones:

```text
data/
  .pipeline.lock
  pipeline_runs/<pipeline_run_id>/
    pipeline.json
    raw/<raw_run_id>/extraction_manifest.json
    raw/<raw_run_id>/*.csv
    validated/<validation_run_id>/*.csv
    quarantine/<validation_run_id>/*.csv
    reports/<validation_run_id>.json
    ready/<ready_run_id>/reconciliacion.json
    ready/<ready_run_id>/*.csv
    load_reports/<load_run_id>.json
```

Las etapas conservan sus propios IDs generados por el código existente; no se pretende que sean el mismo UUID. pipeline.json relaciona esos IDs, rutas, estado, inicio/fin UTC, duración y códigos de error. Se verifican raw_run_id, validated_run_id, ready_run_id, modo, estado y rutas de los reportes. El directorio VALIDATED se deriva del run_id devuelto y de los archivos indicados por su reporte, nunca del nombre de una carpeta antigua.

No se usa glob, «latest», orden por fecha ni búsqueda de ejecuciones previas. No hay flags raw-dir/validated-dir/ready-dir ni reanudación automática en el orquestador. Cada intento crea un área distinta y no sobrescribe resultados existentes. Las funciones siguen admitiendo sus ubicaciones normales cuando se usan por separado; solo este comando utiliza un data_dir propio por pipeline.

Si una función falla antes de devolver un ID, no se adivina buscando subcarpetas. El informe identifica la etapa y el área de salida conocida; sus artefactos parciales se conservan para revisión manual. La publicación atómica y limpieza de temporales de cada etapa siguen a cargo de su implementación original. pipeline.json también se escribe atómicamente mediante extraer_raw.save_manifest.

## Parada ante errores y rechazos

Se detiene inmediatamente cuando una etapa lanza error o devuelve un resultado incompatible. VALIDATED debe estar completado, tener las cinco tablas y el RAW correcto, conservar sus conteos y balance leídas=validas+rechazadas. **Cualquier rechazo o contador de error de calidad impide llamar a preparar_ready y al cargador**, aunque el reporte del validador diga completado. Las advertencias no equivalen a rechazos y se conservan en el reporte original; no se cambian sus reglas.

READY debe pertenecer al VALIDATED/RAW actuales y estar publicado. El resultado de simulación solo es exitoso con código 0, modo dry-run, commit_confirmado=false y estado dry_run_apto_para_carga o dry_run_ya_cargado_identico, además de los IDs y READY correctos. Un estado de carga real o commit confirmado jamás se presenta como éxito de este orquestador.

No hay reintentos automáticos ni reparación de datos. Se preservan resultados completos de etapas previas cuando falla una posterior. Una segunda ejecución empieza de nuevo; no reutiliza la anterior. Si el reporte principal no puede guardarse, el comando falla y no anuncia éxito ni revela el error bruto del sistema.

| Código de salida | Significado |
| --- | --- |
| 0 | Las cuatro etapas terminaron, con dry-run remoto aceptado; nada cargado |
| 1 | Fallo operativo, de linaje, calidad estructural, READY, reporte o simulación |
| 2 | Parada por registros rechazados o contadores de error de calidad; argparse también utiliza 2 para argumentos inválidos antes de iniciar |
| 3 | Hay un bloqueo existente; no se ejecutan etapas ni se crea otro pipeline.json |
| 130 | Interrupción con Ctrl+C; no se continúa con etapas posteriores |

## DWH ya cargado: conflicto esperado posible

La política conservadora de etapa 13 compara todos los campos, incluido **raw_run_id**. Una nueva extracción genera un raw_run_id distinto. Aunque claves y totales sean iguales a la carga ya existente, el dry-run puede devolver conflicto de contenido y el pipeline terminará con código 1. Eso es una comprobación de seguridad del cargador, no una razón para ignorar el error.

No se reetiqueta la extracción con un ID antiguo, no se modifica la procedencia, no se deshabilita idempotencia ni se borran/sobrescriben tablas para que pase la simulación. Si aparece ese caso, revisar el reporte de load_reports y decidir fuera de este comando una política futura de actualización, con autorización previa si implica escrituras.

Las referencias históricas por raw_run_id se aplican tal como lo hagan READY/cargador. Un nuevo run no hereda automáticamente el perfil de otro ni se fija un conteo universal en el orquestador.

## Bloqueo de concurrencia

Creación exclusiva local de data/.pipeline.lock antes de conectar. Contiene PID, pipeline_run_id e inicio UTC, sin credenciales; se mantiene el descriptor durante la ejecución. Otra invocación se rechaza, sin abrir conexiones ni llamar etapas. Se retira únicamente el archivo propio al terminar o ante excepciones normales/Ctrl+C. No hay expiración por tiempo, porque una extracción legítima puede ser larga.

Una terminación forzada del proceso, corte eléctrico o fallo al retirar el archivo puede dejar un bloqueo residual. No se elimina automáticamente: podría pertenecer a otro pipeline activo. Para inspeccionarlo desde la raíz:

```powershell
$lock = Get-Content -LiteralPath 'data/.pipeline.lock' -Raw -Encoding UTF8 | ConvertFrom-Json
$lock | Select-Object pid, pipeline_run_id, inicio_utc
Get-Process -Id $lock.pid -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, StartTime
```

El PID puede haber sido reutilizado. Confirmar manualmente proceso, fecha e informe y que no hay un pipeline ejecutándose antes de retirar **solo ese archivo**. No borrar el bloqueo mientras una ejecución esté activa. El bloqueo es por carpeta data y para este orquestador: no coordina scripts independientes que no lo implementan, otras máquinas con carpetas diferentes o escritores externos del DWH. Usar un directorio local de Windows, no interpretar este mecanismo como bloqueo distribuido.

## Seguridad de registros y recursos

La consola del orquestador muestra inicio/fin/estado/duración y códigos controlados, sin str(error), trazas o cadenas de conexión. La salida stdout/stderr de las funciones reutilizadas se descarta durante cada etapa, sin acumularla en memoria. El reporte principal no copia error crudo de los subreportes ni datos de registros. Los manifiestos, cuarentena y reportes detallados existentes permanecen locales con el formato de sus scripts; no se versionan.

Se reutilizan fetchmany, procesamiento por lotes y SQLite temporal. No se leen tablas completas en RAM, no se crean procesos de etapas paralelos ni listas de datos en el orquestador. --batch-size controla extracción y simulación; validación y READY conservan los lotes/cachés originales. No se midió pico de RAM. Las copias/snapshots, índices temporales y CSV completos requieren espacio libre de disco; no hay limpieza automática de ejecuciones anteriores.

.gitignore ya excluye /data/ y temporales: no se cambió ni se ocultan código, pruebas o documentación. No hay credenciales nuevas, cambios a bases, permisos, conexiones del backend o configuración global.

## Pruebas y verificación de esta entrega

Pruebas nuevas con Services/mocks y directorios temporales: orden, conexión/cierre, execute=False, IDs/rutas actuales, ejecuciones independientes, rechazo y errores, balances/tabla faltante, modo muestra prohibido, reportes/linajes ajenos, READY y dry-run fallidos, commit inesperado, Ctrl+C, exclusión concurrente, errores sin secretos y CLI sin --execute. Además se comprueba que los adaptadores son las funciones existentes, sin llamarlas contra bases.

No se ejecutó el pipeline completo ni se abrieron conexiones reales durante esta entrega; se ejecutaron las pruebas y --help. El comando real queda disponible para ejecución manual deliberada. Los resultados de las pruebas se registran abajo, sin presentar simulaciones como una carga o extracción real.

Resultados ejecutados: **16 pruebas nuevas aprobadas**; suite completa de tests/ **114 pruebas aprobadas, incluidas esas 16** (10.037 s en la ejecución registrada). Tras el ajuste final del mensaje de reporte no guardado se repitieron las 16 pruebas del orquestador y volvieron a pasar. --help finalizó correctamente y git diff --check no detectó errores. Se confirmó que data/.pipeline.lock y data/pipeline_runs/.../pipeline.json están ignorados por Git. No se realizaron extracciones, simulaciones remotas o cargas reales; no se hizo commit ni push.
