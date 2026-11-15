# Validación de calidad RAW → VALIDATED

## Alcance y ejecución

`etl/validar_raw.py` lee los cinco CSV del directorio indicado con `--raw-dir` (o las muestras legadas de `data/raw/` si se omite), separa registros válidos y rechazados y genera un reporte JSON por ejecución. No modifica RAW, no conecta a SQL Server, no transforma valores ni implementa READY, staging, Supabase, Data Warehouse o incrementalidad. No añade dependencias: utiliza la biblioteca estándar de Python **3.13 o superior** y reutiliza la lista cerrada de tablas de `extraer_raw.py`.

Desde PowerShell en la raíz, con el entorno virtual existente:

```powershell
# Pruebas: solo datos ficticios, sin leer las muestras ni conectar a SQL Server.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_validar_raw.py -v

# Validación: utiliza los cinco CSV RAW existentes, sin variables de conexión.
.\.venv\Scripts\python.exe .\etl\validar_raw.py
$LASTEXITCODE
```

Códigos del validador: **0** = ejecución completa sin rechazados; **2** = ejecución completa con rechazados; **1** = fallo operativo, de lectura o esquema, sin reporte de ejecución completa. Las advertencias no cambian el código 0 a 2. Las pruebas devuelven 0 cuando pasan.

## Selección de una ejecución RAW

Para validar una ejecución nueva usar `.\.venv\Scripts\python.exe .\etl\validar_raw.py --raw-dir '.\data\raw\<run_id>'`. Se conserva el modo sin argumentos para los CSV legados. El reporte registra directorio, run_id y modo de extracción; si hay manifiesto se exige estado completado y coincidencia con sus filas extraídas. Véase [extracción completa](08_extraccion_completa.md). Las claves foráneas permanecen desactivadas tanto para muestra como para completo hasta implementar comprobaciones seguras.

## Esquema real y reglas aplicadas

`etl/esquema_raw.json` conserva los metadatos consultados en la instancia local WideWorldImporters: nombres, orden, tipo, nulabilidad, longitud, precisión, escala y clave primaria de cada tabla. Incluye fecha UTC de captura y definiciones de claves foráneas pendientes. No contiene filas de negocio ni credenciales. Es una referencia del esquema consultado, no una inferencia desde las 100 filas. Si cambia la estructura de la fuente se debe revisar y actualizar este contrato antes de validar nuevos CSV.

| Tabla | Clave primaria | Fechas presentes en el esquema |
| --- | --- | --- |
| Sales.Invoices | InvoiceID | InvoiceDate, ConfirmedDeliveryTime, LastEditedWhen |
| Sales.InvoiceLines | InvoiceLineID | LastEditedWhen |
| Sales.Customers | CustomerID | AccountOpenedDate, ValidFrom, ValidTo |
| Warehouse.StockItems | StockItemID | ValidFrom, ValidTo |
| Sales.Orders | OrderID | OrderDate, ExpectedDeliveryDate, PickingCompletedWhen, LastEditedWhen |

Todos los campos se comprueban conforme a sus metadatos, no solo los enumerados en la tabla anterior. No se agregan columnas a los CSV válidos.

| Regla / código | Tratamiento |
| --- | --- |
| Cabecera | Debe coincidir exactamente con columnas y orden del esquema real. Archivo vacío, cabecera ausente o distinta: abortar la ejecución; no adivinar posiciones. |
| CSV_COLUMNAS | Fila con cantidad incorrecta de campos: cuarentena, con todos los campos originales también en JSON para conservar extras o ausencias. |
| PK_NULA | Clave primaria SQL NULL: cuarentena. Cadena vacía en una clave entera es un tipo inválido, no se confunde con NULL. |
| PK_DUPLICADA | Dos pasadas con índice SQLite en disco. Se rechazan **todas** las apariciones de una clave válida duplicada entre filas con estructura correcta, incluso separadas por lotes. Se compara su valor entero (`1` y `01` colisionan), pero nunca se reescribe el texto de salida. |
| OBLIGATORIO_NULO | Toda columna NOT NULL del esquema debe tener valor. Las columnas nullable se permiten salvo la excepción monetaria descrita abajo. No se inventa la prohibición de textos vacíos: NOT NULL no equivale a NOT EMPTY. |
| TIPO_INVALIDO | int dentro del rango SQL de 32 bits; decimal finito con precisión y escala del esquema, sin conversión a float; bit como True/False/0/1; nvarchar dentro de su longitud UTF-16 cuando sea limitada; varbinary y geography en hexadecimal 0x de bytes completos. No se interpreta ni certifica la geometría interna de geography. |
| FECHA_INVALIDA | Calendario y reloj válidos en formato ISO; date YYYY-MM-DD y datetime2 con T y fracción de hasta la escala del esquema. No se redondean ni truncan las fracciones de siete cifras en los CSV. |
| MONETARIO_INCOMPLETO | En InvoiceLines, NULL en Quantity, UnitPrice, TaxAmount o ExtendedPrice impide comprobar la fórmula y envía la fila a cuarentena. UnitPrice sí es nullable en SQL: esta es una restricción de verificabilidad del control, no una afirmación de que viole el esquema SQL. No sustituir NULL por cero. |
| DIFERENCIA_MONETARIA | En InvoiceLines se rechaza si ABS(ExtendedPrice - (Quantity × UnitPrice + TaxAmount)) > 0.01, usando Decimal y precisión suficiente. Solo se compara si los cuatro campos se pudieron interpretar correctamente. |

Una fila puede infringir varias reglas; se escribe una sola vez en cuarentena. El conteo por regla cuenta filas afectadas, como máximo una vez por regla y fila; por eso la suma de errores puede superar el número de rechazados.

## Tolerancia y límites de negocio

La tolerancia **0.01 es provisional**, conforme a `04_reglas_calidad_datos.md`. Una diferencia de exactamente 0.01 se acepta; no significa igualdad exacta. La tolerancia requiere aprobación según moneda y reglas de redondeo. Esta comprobación no valida la base gravable, exenciones, TaxRate ni reconstruye TaxAmount: la validación detallada de impuestos sigue pendiente. Tampoco cierra la conciliación completa de la sección 7 del SQL.

Las cantidades y precios se validan por su tipo y precisión reales. Se perfilan ceros y negativos de Quantity, QuantityPerOuter, UnitPrice, RecommendedRetailPrice, TaxAmount, ExtendedPrice y LineProfit cuando existan en la tabla. Se reportan como advertencias, sin rechazar por el signo, porque las reglas previas no han aprobado una política para créditos, gratuidades o márgenes negativos.

Las fechas futuras de OrderDate e InvoiceDate se reportan como advertencias respecto a la fecha de Honduras (America/Tegucigalpa, UTC-06:00). El rango histórico observado 2013-01-01 a 2016-05-31 no se impone como límite de aceptación. No se prohíben fechas futuras en ValidTo: es una columna temporal. No se inventan relaciones de orden entre fechas para las que no hay regla aprobada.

## Relaciones pendientes

**No se aplican controles de claves foráneas entre estas muestras independientes.** Tampoco se rechazan facturas por no encontrar aquí su pedido ni se compara InvoiceDate con OrderDate entre archivos. Eso produciría falsos errores por padres ausentes de la muestra.

Las relaciones reales están preparadas como definiciones en `esquema_raw.json`, en `foreign_keys_pending`. Para activarlas en otra etapa se necesita una extracción completa o relacionada y consistente, incluir los catálogos padres requeridos, comprobar primero claves únicas y después buscar referencias no nulas sin padre. Los NULL permitidos se tratan aparte. Algunas relaciones apuntan a tablas que no forman parte de los cinco archivos actuales; las definiciones no autorizan a dar esos controles por ejecutados. El reporte declara expresamente `NO_EVALUADAS`.

## Archivos y trazabilidad

Cada ejecución tiene un identificador UTC más UUID y produce:

```text
data/
  raw/                              # Originales: no se modifican
  validated/<run_id>/<tabla>.csv     # Misma cabecera y valores originales
  quarantine/<run_id>/<tabla>.csv    # Originales más motivo y procedencia
  reports/<run_id>.json              # Reporte de ejecución completa
```

Se crean cinco CSV válidos y cinco de cuarentena; si no hay rechazados, estos últimos contienen solo cabecera. Se conservan UTF-8 con BOM, comas, comillas, saltos de línea, NULL sin comillas y texto vacío entre comillas mediante `csv.QUOTE_NOTNULL`. Para leer estas salidas conservando NULL se requiere Python 3.13+. No se recortan textos ni se escriben los valores convertidos usados en las comprobaciones.

Cuarentena añade columnas técnicas con prefijo `__`:

- `__raw_file`: nombre del archivo de origen.
- `__raw_record`: número lógico de registro, empezando en 1 después de la cabecera.
- `__raw_line`: línea física inicial, útil para textos que incluyen saltos de línea.
- `__errors_json`: lista de códigos, columnas y detalles de cada regla incumplida.
- `__raw_fields_json`: lista completa de campos de origen, incluidos NULL y extras si la estructura de la fila era incorrecta. Las columnas originales se rellenan con NULL o se limitan a la cabecera solo para representar esa fila estructuralmente inválida; este JSON conserva la lista completa y RAW permanece intacto.

El reporte registra rutas, SHA-256 de cada entrada procesada, versión temporal del esquema, fecha de evaluación, filas leídas/válidas/rechazadas, errores por regla, advertencias y `balance_correcto`. Se verifica explícitamente **válidas + rechazadas = leídas** antes de publicar.

`/data/` ya está excluido en `.gitignore`, incluidos validated, quarantine, reports, instantáneas e índices temporales. Código, metadatos de esquema, documentación y pruebas se versionan.

## Lotes, fallos y publicación

Se procesa una tabla por vez en lotes de 25 registros. Las claves se cuentan en SQLite temporal con caché de 2 MiB, evitando un conjunto de todas las claves en RAM. Se hacen dos pasadas sobre una copia temporal de cada CSV: así se pueden rechazar todas las apariciones duplicadas sin cargar la tabla completa. La copia se hace en disco; su SHA-256 identifica los bytes usados. Si tamaño o fecha de modificación de RAW cambian durante la copia, se aborta. No ejecutar extracción y validación simultáneamente: este control no sustituye un bloqueo o una instantánea transaccional.

El lector usa CSV estricto, UTF-8 y un máximo de 16 MiB por campo. Una fila con número incorrecto de campos se puede identificar y rechazar. En cambio, comillas sin cerrar, UTF-8 inválido, un campo que excede ese límite o un error de E/S abortan toda la ejecución: no se inventan límites de filas para continuar leyendo datos ambiguos. El consumo depende también del ancho de cada registro y de los campos grandes, no solo de la cantidad de filas.

Todas las salidas se preparan en un directorio temporal bajo data. Solo se publican después de completar las cinco tablas y sus balances. Las carpetas de cada ejecución son nuevas; no se sobrescriben resultados anteriores. Se publica el reporte al final como marcador de ejecución completa. Ante un fallo de publicación capturado se retiran las carpetas recién publicadas de esa ejecución. Consumir únicamente identificadores que tengan reporte completo. No hay una transacción de sistema de archivos entre las tres zonas: una terminación forzada podría dejar temporales o carpetas huérfanas sin reporte; no se consideran resultados completos.

## Pruebas y resultado observado

Las pruebas automatizadas usan únicamente filas inventadas en directorios temporales y metadatos del esquema; no leen data/raw ni necesitan SQL Server. Cubren filas válidas de las cinco tablas, NULL, campos obligatorios, duplicados entre lotes, límites monetarios de ±0.01 y exceso, precio NULL, tipos/fechas/hexadecimal inválidos, conservación de caracteres y precisión, signos como advertencias, estructuras incorrectas y fallos de lectura/publicación.

Resultado de las muestras RAW existentes:

| Tabla | Leídas | Válidas | Rechazadas | Balance |
| --- | ---: | ---: | ---: | --- |
| Sales.Invoices | 100 | 100 | 0 | Correcto |
| Sales.InvoiceLines | 100 | 100 | 0 | Correcto |
| Sales.Customers | 100 | 100 | 0 | Correcto |
| Warehouse.StockItems | 100 | 100 | 0 | Correcto |
| Sales.Orders | 100 | 100 | 0 | Correcto |

No se encontraron errores bajo los controles aplicados. Hubo una advertencia `LineProfit:NEGATIVO` en InvoiceLines. Estos resultados no acreditan integridad referencial ni representatividad de la muestra ni completan los controles pendientes de la fuente.
