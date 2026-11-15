# Extracción completa de WideWorldImporters

## Modos, lotes y salidas

`etl/extraer_raw.py` conserva `muestra` como modo predeterminado: `TOP (100)` por tabla con orden por clave primaria. `--modo completo` elimina TOP y lee todas las filas en ese mismo orden. Solo se admiten las cinco tablas fijas: Sales.Orders, Sales.Invoices, Sales.InvoiceLines, Sales.Customers y Warehouse.StockItems. No se reciben identificadores SQL libres.

El tamaño inicial es **500 filas**, configurable con `--batch-size` (entero positivo). Se usa `fetchmany`, una tabla a la vez, sin cargar tablas completas en RAM. Se mantienen los nombres y valores originales, UTF-8 con BOM, `QUOTE_NOTNULL`, fechas ISO con precisión temporal, caracteres especiales y hexadecimal para binarios/UDT descritos en [la guía RAW](06_extraccion_raw.md). No se añaden dependencias.

Cada ejecución crea un directorio nuevo `data/raw/<run_id>/`, con cinco CSV y `extraction_manifest.json`. El identificador combina fecha/hora UTC y UUID. No se sobrescriben ejecuciones ni las muestras antiguas que todavía están directamente en `data/raw/`.

Cada CSV se escribe en un temporal del mismo directorio y se publica mediante `os.replace` al completar la lectura y los controles de conteo. Un fallo elimina el temporal de la tabla y deja la ejecución marcada como fallida; las tablas anteriores pueden estar completas dentro de ese directorio, pero **la ejecución no debe consumirse**. No se mezclan datos de otras ejecuciones. Una terminación forzada puede dejar un temporal o manifiesto `en_proceso`.

El manifiesto se actualiza de forma atómica. Registra modo, lote, estado, inicio/fin UTC y, por tabla, filas extraídas, conteos fuente antes/después, filas esperadas, duración en segundos, errores y ruta. La consola muestra esos datos al terminar o fallar cada tabla. El código de salida es 0 si termina; 1 si falla. Los errores ODBC se registran por SQLSTATE sin volcar la cadena de conexión.

## Conteos y consistencia

Se consulta `SELECT COUNT_BIG(*)` sobre cada tabla antes y después de extraerla. En modo completo, filas extraídas debe coincidir con el conteo inicial; en muestra, debe coincidir con `min(100, conteo inicial)`. En ambos casos, si el conteo posterior difiere del inicial se falla antes de publicar el archivo. Los conteos no están fijados en el código.

La conexión compartida usa autenticación integrada, ODBC Driver 18 en los comandos siguientes y variables de entorno; se conserva el fallback 18/17 existente. El script explicita **READ COMMITTED**, con autocommit por consulta. **No existe una instantánea transaccional común** ni se cambian opciones de la base. Si la base usa READ_COMMITTED_SNAPSHOT, eso tampoco convierte estas consultas independientes en una sola instantánea.

Dos conteos iguales no detectan actualizaciones de valores, inserciones y eliminaciones compensadas ni garantizan coherencia entre tablas. Ejecutar contra una copia estable o durante una ventana sin escrituras. No se certifica una lectura consistente ante cambios concurrentes y no se usa NOLOCK. La implementación no modifica datos de SQL Server.

## PowerShell: pruebas, extracción y validación

Ejecutar desde la raíz, con `.venv` existente y Python 3.13+ para la validación. Configuración e instalación inicial: [guía de conexión](05_conexion_sqlserver.md).

```powershell
# 1. Pruebas unitarias: solo datos ficticios; no necesitan SQL Server.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas.' }

# 2. Conexión integrada de Windows a la instancia local.
$env:SQLSERVER_HOST = 'ANTON\SQLEXPRESS'
$env:SQLSERVER_DATABASE = 'WideWorldImporters'
$env:SQLSERVER_ODBC_DRIVER = 'ODBC Driver 18 for SQL Server'
$env:SQLSERVER_ENCRYPT = 'yes'
$env:SQLSERVER_TRUST_SERVER_CERTIFICATE = 'yes'

# 3. Extracción completa explícita.
.\.venv\Scripts\python.exe .\etl\extraer_raw.py --modo completo --batch-size 500
if ($LASTEXITCODE -ne 0) { throw 'Falló la extracción; no validar esa ejecución.' }

# 4. Seleccionar la última extracción completa terminada.
# Ejecutar secuencialmente, sin otras extracciones simultáneas.
$rawRun = Get-ChildItem .\data\raw -Directory | Where-Object {
    $manifestPath = Join-Path $_.FullName 'extraction_manifest.json'
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest.estado -eq 'completado' -and $manifest.modo -eq 'completo'
    }
} | Sort-Object Name -Descending | Select-Object -First 1
if (-not $rawRun) { throw 'No se encontró una extracción completa terminada.' }
$rawRun.FullName

# 5. Validar exactamente ese directorio, sin consultar SQL Server.
.\.venv\Scripts\python.exe .\etl\validar_raw.py --raw-dir $rawRun.FullName
$LASTEXITCODE
```

`TrustServerCertificate=yes` corresponde a la prueba local con certificado autofirmado; con certificado válido usar `no`. El script no carga `.env` automáticamente.

Se puede copiar directamente la ruta `data/raw/<run_id>` impresa por el extractor y pasarla a `--raw-dir`, evitando cualquier selección automática. El reporte de calidad conserva `raw_dir`, `raw_run_id` y `raw_modo`, además de hashes y conteos. El validador rechaza manifiestos no completados y comprueba que las filas leídas coincidan con las filas extraídas declaradas. Si no hay manifiesto se admiten los CSV legados.

Para conservar el uso anterior y ejecutar solo una muestra:

```powershell
.\.venv\Scripts\python.exe .\etl\extraer_raw.py
# Equivalente explícito:
.\.venv\Scripts\python.exe .\etl\extraer_raw.py --modo muestra --batch-size 500

# Valida las muestras legadas que están directamente en data/raw/:
.\.venv\Scripts\python.exe .\etl\validar_raw.py
```

La ejecución sin `--raw-dir` no elige automáticamente el último run: conserva el comportamiento legado. Para una muestra nueva se debe pasar su directorio explícito. Las zonas de salida VALIDATED, cuarentena y reportes conservan identificadores propios de validación. Códigos de calidad: 0 sin rechazados, 2 con rechazados y ejecución completa, 1 fallo operativo.

## Memoria y limitaciones

El extractor mantiene en memoria un lote, no una tabla. El consumo depende del lote y del ancho de las filas, especialmente imágenes y textos; si hace falta se puede reducir a `--batch-size 100`. La validación conserva lotes de 25 y un índice de claves en SQLite en disco, con caché de 2 MiB; las copias temporales y las dos pasadas requieren espacio y tiempo de disco. No se midió el pico de RAM ni se garantiza un número fijo, pero el diseño evita un consumo proporcional a todas las filas en RAM.

La conexión mantiene timeout de 10 segundos y las consultas de 30 segundos; una fuente mayor o bloqueada puede requerir revisar esos límites. No se ejecutan tablas en paralelo, reintentos automáticos, particionado ni extracción incremental. Cada repetición conserva una copia nueva: planificar espacio para RAW, VALIDATED y temporales.

Las claves foráneas permanecen **NO_EVALUADAS también en modo completo**: aún faltan comprobaciones seguras y varios catálogos padres no están entre estas cinco tablas. No se activa su validación por el solo hecho de extraer todas las filas. Se conservan la tolerancia monetaria provisional 0.01 y las demás reglas documentadas en [validación de calidad](07_validacion_calidad.md). No se implementan READY, Supabase, staging, Data Warehouse ni cargas.

`/data/` ya excluye todas estas ejecuciones, manifiestos, reportes y temporales de Git. No se añaden credenciales ni archivos de datos al repositorio.

## Pruebas automatizadas

La suite comprende 25 pruebas con datos ficticios. Incluye modo seguro predeterminado, lotes configurables, muestra menor de 100, tablas vacías, extracción completa, conservación de ejecuciones, formato CSV, diferencias de conteo y cambios de fuente, fallos de lectura y temporales, lista SQL fija, selección RAW explícita, compatibilidad legada, procedencia del manifiesto y rechazo de ejecuciones incompletas. También conserva las pruebas de calidad existentes. No requiere SQL Server para las pruebas unitarias.

## Resultado de la ejecución real

La suite de **25 pruebas** terminó correctamente. La extracción completa con lotes de 500 y su validación terminaron con código 0.

- RAW run_id: `20261115T044925Z-474e2802f9394e44855c01a4fc87e9e6`.
- Reporte de calidad: `data/reports/20261115T044952Z-14ac86dfa8bf4b73b92b937cccaa5b8c.json`.

| Tabla | Extraídas | COUNT_BIG antes/después | Válidas | Rechazadas | Extracción (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sales.Orders | 73595 | 73595 | 73595 | 0 | 2.032 |
| Sales.Invoices | 70510 | 70510 | 70510 | 0 | 4.646 |
| Sales.InvoiceLines | 228265 | 228265 | 228265 | 0 | 6.689 |
| Sales.Customers | 663 | 663 | 663 | 0 | 0.092 |
| Warehouse.StockItems | 227 | 227 | 227 | 0 | 0.031 |

Total: **373260 filas**. Todos los balances de calidad fueron correctos. Se observaron **4626 advertencias LineProfit:NEGATIVO**, sin rechazar esas filas conforme a las reglas provisionales existentes. No se detectaron errores bajo los controles ejecutados; no se ejecutaron claves foráneas ni se certifica consistencia transaccional. Estos son resultados observados, no conteos esperados fijados en el código.

Para repetir únicamente la validación de esta extracción conservada:

```powershell
.\.venv\Scripts\python.exe .\etl\validar_raw.py --raw-dir '.\data\raw\20261115T044925Z-474e2802f9394e44855c01a4fc87e9e6'
```
