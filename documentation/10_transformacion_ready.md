# Transformación local VALIDATED → READY

## Alcance y contrato

`etl/preparar_ready.py` recibe explícitamente el directorio VALIDATED de una ejecución completa y genera cinco CSV dimensionales y un reporte de conciliación. No conecta SQL Server, PostgreSQL ni Supabase y no ejecuta el DDL del DWH. No implementa staging, carga física, incrementalidad, API, frontend o IA.

Se revisaron `09_modelo_dimensional.md`, `01_modelo_logico.sql`, el análisis local del modelo, `validar_raw.py`, el esquema real y las cabeceras de la ejecución validadora completa. **No se detectaron diferencias de columnas.** Una prueba automatizada comprueba que las cabeceras READY coinciden exactamente, incluso en orden, con las columnas del borrador lógico.

El borrador lógico histórico propuso identidades, pero la [revisión física vigente](11_creacion_dwh_supabase.md) utiliza BIGINT PRIMARY KEY explícitas, sin IDENTITY, para cliente_key, producto_key, venta_key y pedido_key. READY ya calcula esas claves reproducibles y no se requieren secuencias. ventas_sin_impuestos y tiene_factura se mantienen generadas en PostgreSQL: la futura carga deberá excluir sus valores materializados tanto de la cabecera/fila enviada como de las columnas de destino, y conciliarlos después. No se ha implementado esa carga ni se deben enviar intactos los CSV de hechos a una lista de destino reducida.

| CSV | Tabla lógica | Grano |
| --- | --- | --- |
| DimFecha.csv | dwh.dim_fecha | Una fecha calendario, más desconocido 0. |
| DimCliente.csv | dwh.dim_cliente | Un CustomerID actual, más desconocido 0. |
| DimProducto.csv | dwh.dim_producto | Un StockItemID actual, más desconocido 0. |
| FactVentas.csv | dwh.fact_ventas | **Una fila por InvoiceLineID**, sin deduplicar factura/producto. |
| FactPedidos.csv | dwh.fact_seguimiento_pedidos | **Una fila por OrderID** en el estado de la extracción. |

FactVentas conserva InvoiceID y OrderID como identificadores degenerados; OrderID sigue siendo nullable. Usa **Invoices.CustomerID** para cliente comercial y conserva Invoices.BillToCustomerID en su columna de trazabilidad. No usa el cliente del pedido ni el maestro BillTo actual para sustituir el cliente comercial.

FactPedidos se prepara de manera independiente, con todos los pedidos como denominador. Cantidad_facturas cuenta cabeceras de Invoices vinculadas, incluyendo cualquier IsCreditNote, y tiene_factura se deriva de ese conteo. Un pedido con dos facturas sigue siendo un pedido. No hay importes de ventas en FactPedidos ni JOIN de hechos que multiplique ventas.

## Requisitos y PowerShell

Python **3.13+**, biblioteca estándar y entorno virtual existente. No se añaden dependencias. No hacen falta variables de conexión ni servicios de base de datos iniciados.

Desde PowerShell en la raíz:

```powershell
# Pruebas: datos ficticios, sin consultar SQL Server ni los CSV reales.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas.' }

# Transformación de la ejecución VALIDATED completa actual.
.\.venv\Scripts\python.exe .\etl\preparar_ready.py --validated-dir '.\data\validated\20261115T044952Z-14ac86dfa8bf4b73b92b937cccaa5b8c'
$LASTEXITCODE
```

Código 0: READY publicado y conciliado. Código 1: fallo; revisar el mensaje y su reporte. No hay opción para ignorar conciliaciones incorrectas ni para transformar las muestras independientes.

El reporte de calidad se busca, por defecto, en `data/reports/<validated_run_id>.json`, a partir del directorio indicado. Si se conserva en otra ubicación, se puede especificar:

```powershell
.\.venv\Scripts\python.exe .\etl\preparar_ready.py --validated-dir '.\data\validated\20261115T044952Z-14ac86dfa8bf4b73b92b937cccaa5b8c' --quality-report '.\data\reports\20261115T044952Z-14ac86dfa8bf4b73b92b937cccaa5b8c.json'
```

El directorio debe coincidir con las rutas del reporte. No se selecciona automáticamente otro run ni se recurre a RAW como entrada de la transformación. El manifiesto RAW asociado se lee solo para verificar la trazabilidad y que la extracción fue completa; se requieren ambos reportes disponibles. Las cinco entradas de transformación son siempre VALIDATED.

## Claves reproducibles y desconocidos

Esquema versionado **wwi-int32-namespaces-v1**. Para CustomerID, StockItemID, InvoiceLineID y OrderID, que son int32 en la fuente:

```text
clave = (namespace << 32) | (clave_negocio + 2^31)
namespace: cliente=1, producto=2, venta=3, pedido=4
```

La codificación es inyectiva en int32, positiva y compatible con bigint. Entidades diferentes tienen espacios separados; no depende del orden de lectura, del tamaño de la muestra, de contadores locales, de `hash()` de Python ni de UUID aleatorios. Agregar otra clave de negocio no reasigna las existentes. El UUID se usa solo para identificar cada ejecución READY.

DimFecha mantiene la clave YYYYMMDD aprobada. Se genera un calendario continuo entre las fechas mínima y máxima de factura, pedido y entrega prevista. No se incluyen festivos ni atributos fiscales no verificados.

Se reserva **0** para desconocidos: fecha con atributos NULL, cliente/producto con nombre `Desconocido` y clave de negocio NULL. Estos tres miembros se incluyen explícitamente en las dimensiones. **No se asignan automáticamente a una referencia ausente.** Una referencia requerida sin padre detiene toda la publicación. Un OrderID NULL permitido se conserva como NULL degenerado, sin convertirlo en pedido 0.

La política está acotada a esta fuente WWI con claves int32 y dimensiones tipo 1. Multifuente, claves más amplias o SCD tipo 2 requerirán otro contrato/registro de claves, no una reinterpretación silenciosa del esquema v1. Las dimensiones representan atributos actuales: no reconstruyen sus históricos temporales.

## Importes y conservación de valores

Se reutilizan el lector CSV, tipos y tolerancia de la validación existente. Cantidades enteras y decimales se interpretan según el esquema real; no se convierten importes a float. Se usa Decimal con precisión de trabajo 50:

- Ventas sin impuestos: Quantity × UnitPrice, materializado como ventas_sin_impuestos.
- Impuestos: TaxAmount registrado, sin reconstruirlo desde TaxRate.
- Ventas con impuestos: ExtendedPrice registrado.
- Control de línea: diferencia absoluta entre ExtendedPrice y base más TaxAmount **no superior a 0.01**, tolerancia provisional.

No se redondean ni reparan diferencias. UnitPrice NULL impide certificar la línea y aborta la transformación, sin reemplazo por cero. No se inventa moneda ni se convierten presentaciones. PackageTypeID de la línea se conserva; precios y tasas históricos proceden de InvoiceLines, no del maestro actual de productos.

Todos los registros se conservan en FactVentas, incluido el indicador de crédito. Las conciliaciones monetarias por cliente/mes y las facturas distintas usan el escenario aprobado IsCreditNote=false. No se invierten signos ni se define una nueva semántica neta. El conteo de pedidos con factura considera cualquier cabecera vinculada, como en el KPI original.

Los CSV usan UTF-8 con BOM, comas y `QUOTE_NOTNULL`: NULL se mantiene como vacío sin comillas y texto vacío como `""`. Los booleanos READY se escriben `true`/`false`; las fechas como ISO y los decimales como texto exacto. Los atributos textuales seleccionados no se recortan ni normalizan. RAW y VALIDATED permanecen intactos; solo se transforman columnas y tipos definidos por el modelo.

## Integridad y procedencia

Solo se acepta un reporte VALIDATED completado con `raw_modo=completo`, run_id coincidente y manifiesto RAW completo/terminado. Para esta primera versión también se exige **cero rechazados en las cinco tablas**, balances correctos y cobertura de todas las filas extraídas. Una extracción completa con cuarentena deja de ser una entrada íntegra para estas comprobaciones: se debe resolver antes de preparar READY, sin descartar filas silenciosamente.

Se detectan PK nulas/tipos inválidos y duplicados en las cinco tablas; las cabeceras se comprueban contra el esquema real. Se comprueban los ocho enlaces disponibles entre estas tablas:

1. InvoiceLines.InvoiceID → Invoices.
2. InvoiceLines.StockItemID → StockItems.
3. Invoices.CustomerID → Customers.
4. Invoices.BillToCustomerID → Customers.
5. Invoices.OrderID → Orders, solo cuando no es NULL.
6. Orders.CustomerID → Customers.
7. Orders.BackorderOrderID → Orders, solo cuando no es NULL.
8. Customers.BillToCustomerID → Customers.

No se intenta validar catálogos que no se extrajeron. Si faltan padres, el reporte de fallo incluye el conteo por relación; para líneas incluye hasta 20 ejemplos de sus identificadores. Ningún CSV parcial se publica como READY exitoso. También se rechazan facturas sin líneas: el modelo de ventas actual no puede reproducir su conteo de cabeceras y no debe inventar líneas de importe cero.

Cada archivo de entrada se copia a un área privada y se verifica por SHA-256 antes y después de copiarlo. Las copias se usan para procesar un estado estable; antes de publicar se vuelve a comprobar que VALIDATED no cambió. No transformar y revalidar/escribir simultáneamente los mismos archivos. Estos controles locales no convierten la extracción original en una instantánea transaccional de SQL Server.

## Conciliaciones y referencias específicas

El proceso **relee los cinco CSV READY** del área privada antes de publicarlos. Comprueba claves y atributos de dimensiones, cobertura del calendario, FK dimensionales, claves estables, unicidad de ambos hechos y correspondencia fila a fila por huellas de columnas. Las huellas e índices de líneas se guardan en SQLite temporal en disco, no en una lista de todas las líneas.

Se vuelven a calcular cantidades monetarias desde las salidas, con la misma población de créditos y fechas, y se comparan contra VALIDATED:

- Conteos de los hechos contra las filas validadas correspondientes.
- Facturas ordinarias distintas y conservación de cabeceras con líneas.
- Pedidos sin factura contra la existencia de cabeceras, no de líneas de venta.
- Tres importes generales.
- Los tres importes para **cada cliente comercial** y **cada mes**, no solo la suma de los grupos.
- Fórmula de cada línea y ausencia de pérdidas, duplicaciones o alteraciones.

`etl/referencias_ready.json` contiene además un perfil de aceptación para **RAW run 20261115T044925Z-474e2802f9394e44855c01a4fc87e9e6**, con hashes de las cinco entradas validadas actuales y estas métricas:

| Métrica | Referencia de este run |
| --- | ---: |
| FactVentas / InvoiceLineID únicos | 228265 |
| FactPedidos / OrderID únicos | 73595 |
| Facturas ordinarias distintas | 70510 |
| Pedidos sin factura | 3085 |
| Meses de ventas | 41 |
| Ventas sin impuestos | 172261341.20 |
| Impuestos | 25782098.25 |
| Ventas con impuestos | 198043439.45 |

No son límites universales ni constantes incrustadas en la transformación. El perfil se aplica automáticamente al raw_run_id correspondiente y no se puede omitir por CLI. Un run futuro sin perfil sigue sujeto a integridad y conciliación dinámica contra sus propias entradas, pero el reporte declara `referencia_historica=no_aplica_run_sin_perfil`; no se afirma que pasó referencias históricas no aplicables. Para certificar una nueva referencia, revisar sus resultados y añadir un perfil explícito, sin modificar el anterior.

## Memoria y publicación segura

Se procesan las entradas en lotes de **25 registros**, reutilizando el lector existente. En memoria se mantienen las dimensiones pequeñas, fechas y agregados por cliente/mes. Las cabeceras de pedidos/facturas y las claves/huellas de las 228265 líneas se indexan en un SQLite **temporal de trabajo** con caché de 2 MiB. No se carga InvoiceLines completa en RAM.

La caché desechable usa journaling y sincronización desactivados para evitar coste de durabilidad innecesario: no es un almacén publicado ni una base del DWH. Si falla, la ejecución completa se rehace. Las copias de entrada, índices y salidas requieren espacio de disco; el pico de RAM no se ha medido y también depende del ancho de las filas y de la cantidad de dimensiones/agregados. Se conserva el límite del lector de 16 MiB por campo.

Cada CSV se escribe como temporal y se reemplaza al completarse, **dentro de un área privada**. Solo después de todas las verificaciones se guarda reconciliacion.json con estado completado y se renombra atómicamente la carpeta de salidas a:

```text
data/ready/<ready_run_id>/
  DimFecha.csv
  DimCliente.csv
  DimProducto.csv
  FactVentas.csv
  FactPedidos.csv
  reconciliacion.json
```

Cada run usa UTC más UUID y no sobrescribe uno anterior. El reporte incluye los run_id RAW/VALIDATED/READY, rutas, hashes, esquema de claves, conteos, relaciones, métricas, agregados conciliados y controles. Los índices y copias de trabajo no se publican.

Un fallo deja un reporte con estado fallido en `data/ready/failures/<run_id>.json`, sin directorio READY final de esa ejecución. Una terminación forzada podría dejar un temporal privado; solo se consumen directorios finales con reconciliacion.json completado. No se implementan reintentos ni limpieza automática de ejecuciones anteriores.

`/data/` ya está ignorado por Git, incluidas salidas READY, fallos y temporales. No se ignoran scripts, perfiles de referencia, pruebas ni documentación. No se añadieron credenciales.

## Resultados reales

Ejecución READY: **20261115T051935Z-5599dca545214174bc721b3a016daafd**, basada en VALIDATED **20261115T044952Z-14ac86dfa8bf4b73b92b937cccaa5b8c**. Terminó con código **0**.

| Salida | Filas |
| --- | ---: |
| DimFecha | 1249 |
| DimCliente | 664 |
| DimProducto | 228 |
| FactVentas | 228265 |
| FactPedidos | 73595 |

Las tres dimensiones incluyen un miembro desconocido cada una; **ninguna fila de hecho fue asignada a desconocidos**. DimFecha cubre 2013-01-01 a 2016-06-01 más el miembro 0: incluye entregas previstas posteriores al último mes de facturación.

Todas las referencias anteriores coincidieron: 70510 facturas, 3085 pedidos sin factura, 41 meses y totales 172261341.20 / 25782098.25 / 198043439.45. Los agregados por cliente/mes coincidieron campo a campo; las ocho relaciones tuvieron cero faltantes. Se verificaron los hashes de entrada/salida y los conteos de los CSV finales. No se modificaron RAW ni VALIDATED.

**50 pruebas automatizadas aprobadas**, incluidas 16 de READY: estabilidad e inyectividad de claves, independencia del orden, repetición sin sobrescritura con CSV idénticos, correspondencia de cabeceras con el DDL, granos, cliente comercial distinto del de facturación, duplicados, fecha inválida, importes Decimal y diferencias, relaciones, rechazo de muestra, perfiles de referencia, alteración de salida detectada, OrderID NULL, varias facturas por pedido, créditos y fallo de publicación. Los datos de prueba son ficticios y no requieren servicios externos.

Siguen pendientes la moneda, la política neta de créditos, las conversiones de presentación, la aprobación definitiva de la tolerancia y la validación detallada de impuestos. READY local conciliado no significa un DWH físico cargado ni cierra las comprobaciones pendientes sobre un destino PostgreSQL inexistente.
