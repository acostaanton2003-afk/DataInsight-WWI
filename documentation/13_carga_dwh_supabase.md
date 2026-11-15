# Carga controlada READY → Supabase DWH

## Alcance y estado

`etl/cargar_dwh_supabase.py` implementa la primera carga completa a las cinco tablas existentes de dwh. **Dry-run es el modo predeterminado. No se ha ejecutado --execute en esta etapa.** Se ejecutaron pruebas con destinos simulados y un dry-run real exclusivamente de lectura. No se modifica el DDL, no se crean tablas de staging y no se carga incrementalmente.

La configuración se reutiliza de `probar_conexion_supabase.py`: `load_configuration` lee las seis variables SUPABASE_DB_* de .env sin modificar os.environ, y `open_connection` comparte los parámetros separados, SSL obligatorio, connect_timeout=10 y prepare_threshold=None. Las pruebas de conexión anteriores conservan su funcionamiento. No se añaden dependencias ni se muestran .env, contraseñas, DSN, host o excepciones originales del controlador.

## Contrato de entrada y mapeo

Se exige `--ready-dir` explícito, con cinco CSV y reconciliacion.json completado, sus controles certificados y un raw_run_id de procedencia. No se elige automáticamente el último directorio. No se usan archivos RAW o VALIDATED para cargar, ni se recrea READY.

Se revisaron el modelo 09, la transformación 10, el manifiesto/CSV READY y `03_creacion_tablas_dwh.sql`. Se conserva exactamente el esquema físico revisado: claves BIGINT explícitas sin IDENTITY, sin secuencias y sin cambios de tipos o atributos.

| Orden | CSV READY | Tabla destino | Filas de referencia | Columnas físicas | Campos enviados |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | DimFecha.csv | dwh.dim_fecha | 1249 | 6 | 6 |
| 2 | DimCliente.csv | dwh.dim_cliente | 664 | 11 | 11 |
| 3 | DimProducto.csv | dwh.dim_producto | 228 | 13 | 13 |
| 4 | FactVentas.csv | dwh.fact_ventas | 228265 | 17 | 16 |
| 5 | FactPedidos.csv | dwh.fact_pedidos | 73595 | 9 | 8 |
| Total | | | **304001** | **56** | **54** |

`ventas_sin_impuestos` y `tiene_factura` se comprueban en READY, pero se excluyen tanto de las columnas destino como de los valores enviados. PostgreSQL las genera. No se envía el CSV intacto a una lista reducida: se leen y adaptan sus valores antes de COPY. Los miembros desconocidos 0 vienen explícitos de las dimensiones; no se inventan ni asignan automáticamente.

Se utiliza `COPY ... FROM STDIN` con `write_row`, sin FORMAT CSV: psycopg adapta tuplas Python tipadas, con Decimal para NUMERIC, int, date, bool y None para NULL. Se conservan texto vacío, Unicode, comas, saltos de línea y caracteres especiales. No se construyen URLs con contraseñas ni identificadores SQL procedentes del usuario. Tabla y columnas vienen de la lista fija y del contrato del repositorio. [COPY y adaptación de filas con Psycopg](https://www.psycopg.org/psycopg3/docs/basic/copy.html).

## Prevalidación local

Antes de conectar se hacen copias privadas de READY y se comprueban sus hashes y el manifiesto. La lectura usa UTF-8 con BOM y QUOTE_NOTNULL. El inspector existente valida las 56 cabeceras/tipos y las expresiones generadas, sin redondeos implícitos ni conversión monetaria a float.

Un índice técnico SQLite temporal en disco guarda las filas esperadas en representación canónica. No es una capa staging ni una tabla del servidor. Permite detectar PK/claves de negocio duplicadas y comparar posteriormente cada fila sin cargar los hechos completos en RAM. La caché es de 2 MiB; dimensiones y agregados por cliente/mes son pequeños y se mantienen en memoria. Las copias y el índice necesitan espacio temporal de disco, proporcional a la extracción. No se midió el pico de RAM.

Se verifican:

- Existencia, encabezados exactos, tipos, nulabilidad, longitudes numéricas, fechas y booleanos; hashes/conteos del manifiesto.
- PK y claves de negocio únicas; claves técnicas estables según el esquema READY; procedencia raw_run_id.
- Miembros 0 y atributos de calendario coherentes; referencias de ambos hechos a dimensiones y referencias comerciales disponibles entre estas tablas, sin reemplazar ausentes por desconocidos.
- Coherencia de InvoiceID entre sus líneas, cliente comercial de ventas ya materializado en READY y seguimiento de pedidos independiente. Se cuenta cualquier factura vinculada al pedido, incluidas notas de crédito, conforme al criterio documentado.
- Quantity × UnitPrice exacto en ventas_sin_impuestos, indicador tiene_factura exacto y diferencia de línea con ExtendedPrice no superior a 0.01.
- Conteos, facturas ordinarias distintas, pedidos sin factura, totales y agregados de los tres importes por cada cliente y mes contra reconciliacion.json.

Se aplica automáticamente la referencia histórica de `etl/referencias_ready.json` cuando coincide su raw_run_id. Para la extracción actual se exigen 228265 ventas, 73595 pedidos, 70510 facturas ordinarias distintas, 3085 pedidos sin factura, 41 meses y los tres importes indicados abajo. Es una referencia de ese run, no una restricción universal para toda fuente futura. Otros runs deben conciliarse con sus propios manifiestos y, si corresponde, disponer de un perfil aprobado.

El índice conserva semántica de tipos: Decimal 1.0 y 1.00 son iguales, pero no se normalizan ni recortan textos. PK, todos los atributos, campos degenerados y raw_run_id forman parte de la comparación de contenido.

## Validación remota y política idempotente

Se requiere PostgreSQL 17 y las cinco tablas base ordinarias del contrato. El ejecutor debe ser propietario de cada tabla y RLS no debe aplicarle: no basta ver cero filas bajo una política que oculte datos. Se rechazan tablas heredadas/particionadas, triggers de usuario activos, identidades, defaults inesperados, diferencias de columnas/tipos/nulabilidad y expresiones generadas distintas. Se comprueban las PK, UNIQUE, FK validadas/no diferibles, acciones de FK, índices asociados válidos y el conjunto de CHECK esperado. No se corrigen incompatibilidades ni se cambian roles, políticas o DDL.

La política inicial es deliberadamente conservadora:

| Estado de las cinco tablas | Dry-run | --execute futuro |
| --- | --- | --- |
| Todas vacías | Informa apta para carga; no envía filas. | Carga las cinco y concilia dentro de una transacción. |
| Conteos iguales y contenido íntegro idéntico a READY | Verifica cada fila y reporta ya cargado idéntico. | No inserta ni actualiza; confirma una transacción sin cambios. |
| Conteos parciales, datos adicionales o cualquier valor diferente | Error; no modifica datos. | Error y rollback; no intenta completar o sobrescribir. |

No se deduce identidad a partir de importes agregados o conteos iguales: se comparan todos los campos de cada fila por PK, incluidos atributos y procedencia. La lectura remota usa cursor de servidor y fetchmany, no una descarga completa a memoria. Si otra extracción tiene las mismas claves pero distinto raw_run_id o atributos, se considera conflicto, no una actualización autorizada.

No se usan TRUNCATE, DELETE ni upserts/ON CONFLICT para reemplazar información. Una tabla con solo un miembro 0 precargado se considera destino parcial y requiere revisión; no se borra ni se combina silenciosamente. Esta versión no es un reconciliador de estados parciales ni una carga incremental.

## Transacción, concurrencia y permisos

Dry-run abre una transacción **READ ONLY / REPEATABLE READ**, consulta metadatos y datos visibles en una instantánea y termina con rollback. No ejecuta COPY ni bloqueos de escritura. Solo configura localmente los límites de tiempo mediante SELECT set_config; no altera datos ni configuración persistente. Un dry-run no reserva el destino: --execute deberá repetir todos los controles.

Una ejecución real futura usa READ COMMITTED y adquiere un bloqueo SHARE ROW EXCLUSIVE NOWAIT sobre las cinco tablas, en el orden fijo, antes de evaluar su contenido. El bloqueo impide escritores concurrentes y otro cargador mientras dure la transacción, pero permite lectores. Si está ocupado se aborta, sin reintentos ni esperas indefinidas. Se mantienen los bloqueos hasta terminar la conciliación y el commit; planificar una ventana apropiada. [Bloqueos PostgreSQL 17](https://www.postgresql.org/docs/17/sql-lock.html).

Las cinco cargas y sus comprobaciones forman **una sola transacción**, no commits por tabla. Un fallo de COPY, FK, dato o conciliación anterior al commit provoca rollback de toda la carga. Los errores del controlador se traducen a códigos seguros, sin registros, secretos ni trazas. [Transacciones Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

Los límites locales son 120 segundos por sentencia y 5 segundos para esperas de bloqueo, además del timeout de conexión de 10 segundos. El tamaño inicial para lectura/adaptación es 500, configurable con --batch-size. COPY transmite filas tipadas con los buffers del driver; no hay un round trip por registro ni un commit por lote. El pooler puede imponer límites adicionales. Se mantiene prepare_threshold=None; si el endpoint no permite una operación de la transacción, se falla sin cambiarlo automáticamente.

No se habilita acceso de anon/authenticated, no se cambia RLS y no se expone dwh por Data API. Para esta versión se requiere el propietario, evitando COPY bajo RLS activo y lecturas filtradas que aparenten un destino vacío. No se otorgan permisos automáticamente para superar un error.

**Fallo durante commit:** un corte de conexión puede dejar un resultado incierto, aunque se intente rollback. Se reporta resultado_commit_desconocido_revisar_con_dry_run; no se afirma que el servidor haya deshecho una transacción cuyo commit pudo completarse. Repetir primero dry-run para comprobar el contenido, no asumir que hay que volver a insertar.

Si el commit se confirmó y solo falla guardar el reporte local, el estado indica commit_confirmado_reporte_local_no_guardado, con código 1; los datos no pueden deshacerse retroactivamente. No se implementan reintentos automáticos en ninguno de los casos. El diseño idempotente permite una revisión posterior sin sobrescribir datos.

## Conciliación posterior, antes de commit

En el camino --execute se comprueban:

- Conteos de las cinco tablas contra READY.
- Igualdad semántica de **cada fila y columna física**, incluidas las dos columnas calculadas por PostgreSQL, contra el índice local esperado. PK comparadas sin repeticiones ni pérdidas.
- Las seis FK de los hechos mediante anti-joins, sin referencias huérfanas.
- SUM de ventas_sin_impuestos, tax_amount y extended_price; facturas distintas y meses con IsCreditNote=false; pedidos sin factura.
- Agregados monetarios por cada cliente comercial y cada mes.
- Diferencias de línea abs(extended_price − ventas_sin_impuestos − tax_amount) ≤ 0.01.

Los importes de referencia actuales son:

| Medida | Importe |
| --- | ---: |
| Ventas sin impuestos | 172261341.20 |
| Impuestos | 25782098.25 |
| Ventas con impuestos | 198043439.45 |

La tolerancia **0.01 es por línea y provisional**. No se aplica como descuento general a diferencias de agregación. Como los tipos son exactos y los valores de escritura ya cumplen la escala NUMERIC, los totales del servidor deben coincidir exactamente con READY; ExtendedPrice se concilia independientemente, no se reemplaza por base más impuesto. La moneda y la validación detallada de impuestos siguen pendientes y no se inventan en esta carga.

## PowerShell: pruebas y dry-run autorizado

Desde la raíz del proyecto, con el entorno existente y .env configurado como en la guía 12:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas.' }

.\.venv\Scripts\python.exe .\etl\cargar_dwh_supabase.py --ready-dir '.\data\ready\20261115T051935Z-5599dca545214174bc721b3a016daafd' --dry-run
$LASTEXITCODE
```

Omitir --dry-run produce el mismo modo seguro. --dry-run y --execute son mutuamente excluyentes. Un error devuelve código 1; dry-run apto, ya cargado idéntico o carga real confirmada devuelven 0. No existe un parámetro de borrado, sobrescritura forzada u omisión de controles.

## Comando de carga real, pendiente de autorización expresa

**No se ha ejecutado este comando. No ejecutarlo hasta obtener la autorización expresa del usuario:**

```powershell
.\.venv\Scripts\python.exe .\etl\cargar_dwh_supabase.py --ready-dir '.\data\ready\20261115T051935Z-5599dca545214174bc721b3a016daafd' --execute --batch-size 500
```

Antes de confirmar, revisar el reporte del dry-run y disponer de una ventana de carga. No es necesario ni correcto volver a ejecutar el DDL de creación o vaciar tablas.

## Reportes y resultados de esta preparación

Cada intento guarda un JSON seguro en `data/load_reports/<run_id>.json` con modo, origen READY, hashes, conteos, estado, métricas esperadas, error genérico y confirmación de commit. Se publica mediante temporal/reemplazo; /data/ sigue ignorado por Git. No se guardan parámetros de conexión ni mensajes crudos del driver. Las copias e índices locales son temporales y se eliminan al finalizar. No se modifican READY, su manifiesto ni los CSV previos.

**98 pruebas locales aprobadas**, incluidas 18 del cargador. Cubren dry-run predeterminado, orden y proyección COPY tipada de 54 campos, transacción simulada, segunda ejecución sin cambios, conflicto de atributos aun con conteos iguales, destino parcial preservado, rollback ante fallos y conciliaciones, commit incierto, fallo del reporte después de commit simulado, entradas alteradas/duplicadas y metadatos físicos incompatibles. Los destinos --execute de pruebas son exclusivamente dobles ficticios; las pruebas no usan la conexión real.

El dry-run real **20261115T143904Z-2048888f70184ca4a47451f5ca8fe6e1** terminó con código **0** y estado **dry_run_apto_para_carga**:

| Tabla | READY verificado | Destino observado |
| --- | ---: | ---: |
| dim_fecha | 1249 | 0 |
| dim_cliente | 664 | 0 |
| dim_producto | 228 | 0 |
| fact_ventas | 228265 | 0 |
| fact_pedidos | 73595 | 0 |

Se verificaron localmente los 304001 registros, las referencias del run y los tres importes. La inspección remota confirmó esquema compatible, propietario, expresiones generadas, restricciones y tablas vacías. Reporte: `data/load_reports/20261115T143904Z-2048888f70184ca4a47451f5ca8fe6e1.json`.

**No se han enviado datos ni ejecutado --execute.** La conciliación posterior con filas reales cargadas y el rendimiento end-to-end de COPY quedan pendientes de esa autorización/ejecución. Las pruebas simuladas y el dry-run no equivalen a una carga de integración realizada. No se cambió el DDL ni se añadieron dependencias.
