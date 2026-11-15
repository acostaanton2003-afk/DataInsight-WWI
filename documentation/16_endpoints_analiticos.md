# Endpoints analíticos (etapa 16)

## Definiciones acordes al modelo

- Ventas e impuestos: fact_ventas con is_credit_note=false. Ventas sin impuestos = SUM(ventas_sin_impuestos), impuestos = SUM(tax_amount), total facturado = SUM(extended_price). El total se concilia independientemente: no se reemplaza por base más impuestos ni se corrigen diferencias. Tolerancia 0.01 provisional solo por línea, nunca como tolerancia global. No se supone moneda.
- Facturas = COUNT(DISTINCT invoice_id) de esas líneas; una factura sin líneas no aparece en este hecho. No sumar conteos de facturas de rankings para obtener el total.
- Pedidos = COUNT(*) de fact_pedidos, facturados o no. No se une este hecho con líneas de venta.
- Clientes = COUNT(*) de dim_cliente con cliente_key<>0: clientes registrados en el maestro actual, no solo compradores con ventas. Se excluye únicamente el miembro desconocido. El cliente comercial de ventas ya procede de Invoices.CustomerID; no se sustituye por BillToCustomerID.
- Serie mensual: año/mes de fecha de factura, importe sin impuestos y facturas distintas por mes. Solo meses con ventas; no rellena meses vacíos. Una fecha desconocida se conserva como anio/mes null al final, sin perder su importe.
- Top productos: ventas por producto, acumulando presentaciones/PackageTypeID; difiere del KPI original por cantidad/presentación. Top clientes: ventas por cliente comercial. Desempate por ID de negocio ascendente (NULL al final), después clave sustituta. Los miembros desconocidos con ventas se conservan.

No hay filtros temporales en esta etapa. Los importes usan NUMERIC → Decimal → cadena JSON con dos decimales; no se convierten a float. El frontend futuro deberá tratar estas cadenas explícitamente; no se implementa React/ECharts aquí.

## Contratos HTTP

Todos son GET bajo /api/v1 y usan la conexión exclusiva BACKEND_DB_* de wwi_backend_reader; no hay fallback a variables del ETL. Sin configuración o ante error de base se devuelve HTTP 503 con `{"detail":"No se pudo consultar el Data Warehouse."}`, sin SQL, datos de conexión ni excepciones del driver. Limit fuera de rango/formato devuelve 422. POST devuelve 405. GET /health sigue sin usar base de datos.

| Ruta | Respuesta |
| --- | --- |
| /kpis | Objeto con tres importes y conteos de facturas, pedidos y clientes |
| /ventas/por-mes | Lista cronológica de anio, mes, importe, cantidad_facturas |
| /productos/top?limit=10 | Lista de producto_key, stock_item_id, stock_item_name, ventas_sin_impuestos |
| /clientes/top?limit=10 | Lista de cliente_key, customer_id, customer_name, ventas_sin_impuestos |

Limit: entero entre 1 y 50, predeterminado 10; se pasa como parámetro psycopg `%s`, nunca interpolado en SQL. Consultas estáticas SELECT y cursores locales a cada solicitud. No se aceptan SQL, nombres de tabla ni columnas del cliente. Las operaciones son síncronas para que FastAPI las ejecute fuera del event loop. Se reutiliza read_connection: SSL obligatorio, rol efectivo lector sin atributos administrativos, transacción read-only, timeout de conexión 10 s y sentencia 15 s, cierre al terminar o fallar.

Ejemplos **ficticios** de forma y serialización, no resultados reales:

```json
{"ventas_sin_impuestos":"30.00","impuestos":"3.00","total_facturado":"33.00","cantidad_facturas":2,"cantidad_pedidos":3,"cantidad_clientes":2}
```

```json
[{"anio":2013,"mes":1,"importe":"30.00","cantidad_facturas":2}]
```

```json
[{"producto_key":1,"stock_item_id":7,"stock_item_name":"Producto ficticio","ventas_sin_impuestos":"30.00"}]
```

```json
[{"cliente_key":1,"customer_id":9,"customer_name":"Cliente ficticio","ventas_sin_impuestos":"30.00"}]
```

Sin ventas, los tres importes y facturas son cero; pedidos y clientes se cuentan independientemente. Serie/rankings sin filas devuelven listas vacías. Los IDs comerciales pueden ser null para desconocidos. Los enlaces LEFT JOIN preservan ventas y agrupan por clave sustituta además de ID/nombre; las PK únicas de dimensiones impiden multiplicaciones. Nunca se une fact_pedidos con fact_ventas.

## PowerShell desde la raíz

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
.\.venv\Scripts\python.exe -m backend
```

En otra terminal, con el servidor iniciado y BACKEND_DB_* ya configuradas en el .env local:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/kpis'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ventas/por-mes'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/productos/top?limit=10'
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/clientes/top?limit=10'
```

Abrir http://127.0.0.1:8000/docs, expandir cada GET, pulsar Try it out y Execute. Para rankings comprobar limit=1 y 50 (200), después 0 y 51 (422). Swagger muestra modelos y los importes como cadenas. Detener servidor con Ctrl+C.

## Conciliación y límites

Referencias de la carga actual: base 172261341.20, impuestos 25782098.25, total 198043439.45, 70510 facturas, 73595 pedidos y 41 meses. No se fijan estas cifras en las consultas de producción ni se aplica una tolerancia global. Las pruebas sin red usan datos ficticios y verifican dos líneas de la misma factura, créditos excluidos, empates, fechas, conteos independientes y ausencia de inflación por JOIN; SQLite se usa solo para aritmética entera de prueba, no para validar precisión de PostgreSQL. Decimal y JSON se prueban aparte.

Cada respuesta usa una transacción propia. Si en el futuro hay cargas concurrentes, respuestas de rutas distintas podrían pertenecer a momentos diferentes; esta etapa no ofrece una instantánea común del dashboard. Cada consulta SQL individual obtiene una vista consistente. El límite de tiempo puede requerir revisión si crece el DWH; no se añade caché ni índices. CORS no es autenticación: la API permanece para desarrollo local, sin habilitar exposición pública. No hay filtros por usuario, JWT ni autorización multiusuario en esta etapa.

Para repetir la conciliación desde PowerShell (servidor iniciado):

```powershell
$kpi = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/kpis'
if ($kpi.ventas_sin_impuestos -ne '172261341.20' -or $kpi.impuestos -ne '25782098.25' -or $kpi.total_facturado -ne '198043439.45' -or $kpi.cantidad_facturas -ne 70510 -or $kpi.cantidad_pedidos -ne 73595) { throw 'Conciliación KPI incorrecta' }
$meses = @(Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/ventas/por-mes')
[decimal]$totalMeses = 0
foreach ($fila in $meses) { $totalMeses += [decimal]::Parse($fila.importe, [System.Globalization.CultureInfo]::InvariantCulture) }
if ($meses.Count -ne 41 -or $totalMeses -ne [decimal]172261341.20) { throw 'Conciliación mensual incorrecta' }
'Conciliación correcta'
```

## Resultados ejecutados

- 86 pruebas de backend y 98 pruebas existentes aprobadas, sin servicios externos en las suites.
- Integración real de solo lectura mediante TestClient y BACKEND_DB_*: los cuatro endpoints respondieron HTTP 200 en sus comprobaciones finales; no se escribieron datos ni se ejecutó DDL.
- KPI: ventas sin impuestos 172261341.20; impuestos 25782098.25; total facturado 198043439.45; 70510 facturas distintas; 73595 pedidos; 663 clientes registrados (excluye miembro 0). Los cinco valores de referencia coincidieron exactamente.
- Serie: 41 meses, suma 172261341.20, suma de conteos mensuales 70510. Productos/clientes: diez filas por ranking, orden monetario descendente verificado.

El KPI usa tres CTE MATERIALIZED que agregan cada proceso por separado y siempre producen una fila; el CROSS JOIN entre esas tres filas no multiplica ventas y conserva una sola instantánea de sentencia. Se verificó esta formulación contra PostgreSQL 17. La primera formulación con subconsultas escalares provocó un error operativo de conexión en esta integración; los SELECT individuales funcionaban y la formulación final respondió correctamente. No se atribuye una causa de servidor sin evidencia ni se amplían timeouts para ocultar el problema.

Las comprobaciones remotas verifican la carga visible actual, no constituyen auditoría de políticas RLS ni garantía sobre cargas futuras. No se modificaron conexión/configuración del ETL, roles, permisos o DWH; no se añadieron dependencias. Se actualizaron las dos expectativas de pruebas de health sobre rutas disponibles para reflejar la nueva etapa, manteniendo sus restantes comprobaciones.
