# Primera extracción a la zona RAW

## Alcance

La extracción ahora admite modos muestra/completo y guarda cada ejecución en data/raw/<run_id>/. La [guía de extracción completa](08_extraccion_completa.md) documenta el comportamiento vigente y los comandos de ambos modos. Las muestras legadas en data/raw/ se conservan.

`etl/extraer_raw.py` realiza cinco consultas de lectura y guarda una muestra técnica de hasta 100 filas por tabla. No aplica validaciones de calidad, transformaciones de negocio, staging, cargas a Supabase ni extracción incremental. No modifica la base.

La conexión se reutiliza desde `etl/conexion_sqlserver.py`, compartida con `etl/probar_conexion_sqlserver.py`: pyodbc, autenticación integrada de Windows y variables de entorno. Se utiliza ODBC Driver 18 en los comandos siguientes; se conserva la selección automática 18/17 si la variable del controlador queda vacía. La única dependencia sigue siendo `pyodbc`, en `etl/requirements.txt`.

| Tabla | Orden de la muestra | Archivo relativo a la raíz |
| --- | --- | --- |
| Sales.Invoices | InvoiceID | data/raw/<run_id>/Sales.Invoices.csv |
| Sales.InvoiceLines | InvoiceLineID | data/raw/<run_id>/Sales.InvoiceLines.csv |
| Sales.Customers | CustomerID | data/raw/<run_id>/Sales.Customers.csv |
| Warehouse.StockItems | StockItemID | data/raw/<run_id>/Warehouse.StockItems.csv |
| Sales.Orders | OrderID | data/raw/<run_id>/Sales.Orders.csv |

Las consultas de muestra están escritas en una lista fija y usan `SELECT TOP (100) * ... ORDER BY <clave primaria>`. No hay argumentos para introducir tablas, claves ni SQL libre. Se conservan los nombres y el orden de columnas devueltos por el servidor.

## Ejecución en PowerShell desde la raíz

Se necesita Python **3.12 o superior** para escribir CSV con NULL distinguibles de texto vacío; en este equipo se utiliza Python 3.13.7. El entorno virtual existente ya contiene pyodbc 5.5.0. SQL Server debe estar iniciado y el usuario de Windows debe tener permiso SELECT sobre las cinco tablas.

Si aún no existe `.venv`, crearlo con la instalación encontrada en este equipo:

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
& $pythonExe -m venv .venv
```

Instalar las dependencias si hace falta y ejecutar:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\etl\requirements.txt

$env:SQLSERVER_HOST = 'ANTON\SQLEXPRESS'
$env:SQLSERVER_DATABASE = 'WideWorldImporters'
$env:SQLSERVER_ODBC_DRIVER = 'ODBC Driver 18 for SQL Server'
$env:SQLSERVER_ENCRYPT = 'yes'
$env:SQLSERVER_TRUST_SERVER_CERTIFICATE = 'yes'

.\.venv\Scripts\python.exe .\etl\extraer_raw.py
$LASTEXITCODE
```

No es necesario activar `.venv`. Las variables se leen del proceso; `.env` no se carga automáticamente. `TrustServerCertificate=yes` se usa para el certificado autofirmado de esta prueba local; para un certificado válido usar `no`. No se utiliza usuario SQL ni contraseña. Para diagnóstico de conexión o instalación del controlador consultar [la guía de conexión](05_conexion_sqlserver.md).

Con las variables configuradas, el comando de ejecución es:

```powershell
.\.venv\Scripts\python.exe .\etl\extraer_raw.py
```

El directorio de destino se resuelve respecto a la ubicación del script, no al directorio actual de la terminal. Se crea `data/raw/` automáticamente. `.gitignore` ya excluye `/data/`, incluidos todos los CSV y temporales RAW; los scripts y esta documentación se versionan.

## Formato de los CSV

- UTF-8 con BOM (`utf-8-sig`), separador coma y manejo de saltos de línea con `newline=''`. El módulo `csv` escapa comillas, comas y saltos de línea dentro de los campos. No se recortan textos, cambian nombres ni normalizan valores.
- `csv.QUOTE_NOTNULL`: SQL NULL se escribe como campo vacío **sin comillas**; una cadena vacía se escribe como `""`. Para distinguirlos al leer, usar `csv.reader(..., quoting=csv.QUOTE_NOTNULL)` con Python 3.13 o superior. Un lector CSV genérico puede perder esta distinción. Véase la [documentación de csv de Python](https://docs.python.org/3/library/csv.html#csv.QUOTE_NOTNULL).
- Fechas y horas se representan en formato ISO. Un convertidor de salida para timestamps ODBC conserva las fracciones originales, incluida la séptima cifra de `datetime2`, sin truncarlas a los microsegundos de `datetime` de Python.
- Los decimales se escriben sin convertirlos a `float` ni aplicar redondeos; los demás escalares usan su representación textual del driver (por ejemplo, bit como `True` o `False`).
- Campos binarios, incluida una posible imagen, se serializan como `0x` seguido de hexadecimal. Los tipos espaciales de SQL Server, como `Customers.DeliveryLocation`, se conservan como bytes del driver mediante un convertidor de salida ODBC para el tipo UDT (-151), también en hexadecimal; no se convierten a coordenadas ni se descartan. Es una representación reversible de los bytes, no una transformación de negocio. Referencia: [convertidores de salida de pyodbc](https://github.com/mkleehammer/pyodbc/wiki/Using-an-Output-Converter-function).

CSV no almacena el esquema SQL ni los tipos. Para reconstruir tipos, binarios o valores espaciales, se necesita conocer el tipo de cada columna en la fuente. La representación técnica aquí descrita no debe confundirse con una nueva definición de negocio.

## Memoria, errores y archivos finales

Se procesa una tabla a la vez usando `fetchmany(500)` por defecto (configurable con `--batch-size`), sin `fetchall`, pandas ni cargar tablas completas en RAM. El límite inicial de 100 filas y los lotes pequeños son adecuados para una prueba en un equipo de 8 GB; campos binarios o textos grandes también influyen en la memoria usada. La conexión conserva 10 segundos de timeout y cada consulta 30 segundos.

Cada tabla se escribe en un temporal único dentro de `data/raw/<run_id>/`. Solo después de completar y cerrar el CSV se publica con `os.replace`. Cada ejecución usa un directorio nuevo y conserva las muestras anteriores. Ante una excepción se elimina el temporal y se conserva el archivo final previo, si existía. Si Windows impide reemplazar un CSV abierto en otra aplicación, se informa del fallo y se conserva el anterior.

La consola informa tabla, filas y ruta absoluta por cada archivo publicado. Ante error se indica la tabla y ruta afectadas cuando corresponde, se detiene el proceso y se devuelve código 1. Una ejecución correcta devuelve 0. No se registra la cadena de conexión ni credenciales. No hay atomicidad conjunta entre las cinco tablas: si falla una, la ejecución queda marcada como fallida y no debe consumirse, aunque contenga archivos completos de tablas anteriores. Una terminación forzada del proceso o del equipo puede dejar un `.tmp`, pero no publica ese archivo como CSV final.

## Limitaciones y comprobación técnica

La muestra no representa una extracción completa ni estadísticamente representativa. Cada tabla se selecciona de forma independiente: **no se garantizan relaciones completas entre tablas**. El orden por clave hace repetible la selección sobre el mismo estado de la fuente; cambios de datos pueden modificar la muestra. No se mantiene una instantánea transaccional común entre consultas.

En la ejecución real de esta implementación se extrajeron **100 filas de cada una de las cinco tablas**, con ODBC Driver 18 y código de salida 0. Se comprobó el formato y la cantidad de filas de los cinco CSV, la exclusión por Git, la distinción NULL/texto vacío, caracteres especiales, fechas, decimales, binarios y precisión temporal. Una prueba con fallo simulado confirmó que el destino anterior se conserva y el temporal se elimina. Son comprobaciones del código de extracción; no constituyen validaciones de calidad o integridad de los datos de negocio.
