# Dashboard React + Vite + ECharts (etapa 17)

## Alcance

Dashboard local en español con barra lateral, seis tarjetas KPI, evolución mensual, top 10 productos y top 10 clientes. Consume únicamente los cuatro GET del backend. No accede a PostgreSQL/Supabase, no modifica DWH, no añade autenticación, ML, IA ni despliegue público.

Antes de implementar se inspeccionaron los modelos Pydantic, consultas, CORS y respuestas reales. Contratos reutilizados:

| Ruta (prefijo /api/v1) | Propiedades utilizadas |
| --- | --- |
| /kpis | ventas_sin_impuestos, impuestos, total_facturado (cadenas); cantidad_facturas, cantidad_pedidos, cantidad_clientes (enteros) |
| /ventas/por-mes | anio, mes (nullable), importe (cadena), cantidad_facturas |
| /productos/top?limit=10 | producto_key, stock_item_id (nullable), stock_item_name, ventas_sin_impuestos |
| /clientes/top?limit=10 | cliente_key, customer_id (nullable), customer_name, ventas_sin_impuestos |

Ventas/facturas excluyen notas de crédito. Clientes cuenta el maestro excluyendo desconocido 0; pedidos cuenta todos los pedidos. Producto agrupa presentaciones por ventas, no por cantidad. El periodo y número de meses se derivan de la respuesta, no son etiquetas fijas. El miembro desconocido se presenta sin inventar IDs/fechas. No se suman importes nuevos en el frontend para reemplazar los agregados de la API.

## Requisitos y ejecución en Windows 11

Node.js 24 LTS recomendado (probado 24.13.0), npm y el entorno Python .venv existente. npm.cmd evita conflictos de PowerShell con npm.ps1. Dependencias del frontend separadas en frontend/package.json y bloqueo reproducible package-lock.json. No hay cambios de dependencias del ETL/backend.

**Terminal 1, desde la raíz del repositorio:**

```powershell
.\.venv\Scripts\python.exe -m backend
```

Requiere BACKEND_DB_* y el lector ya configurados en el .env raíz. No copiar ese archivo al frontend ni imprimirlo. Swagger sigue en http://127.0.0.1:8000/docs.

**Terminal 2, desde la raíz del repositorio:**

```powershell
Set-Location frontend
npm.cmd ci
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
npm.cmd run dev
```

Abrir http://127.0.0.1:5173. Ctrl+C detiene cada servidor en su terminal. Vite usa puerto estricto: si está ocupado no cambia silenciosamente a un origen sin CORS. No se requiere Vite global. Instalación con npm ci reproduce el lockfile; usar npm install solo para cambiar dependencias deliberadamente.

frontend/.env.example define:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Es la raíz HTTP de FastAPI, sin /api/v1 al final. Cambiar URL en frontend/.env y reiniciar Vite. Las variables VITE_* son públicas y quedan en el bundle: nunca incluir contraseñas, tokens ni SUPABASE_DB_*/BACKEND_DB_*. El cliente valida HTTP(S), sin usuario/contraseña/query/hash en la URL. No guarda respuestas ni credenciales en localStorage; fetch usa credentials:omit. No hay proxy que oculte problemas CORS.

## Precisión, visualización y accesibilidad

Importes validados como cadenas con dos decimales. El formateador separa unidades y centavos, usa BigInt e Intl.NumberFormat y muestra `172.261.341,20`, incluso por encima de la precisión segura de Number. **No se asigna moneda ni símbolo**: la moneda de origen sigue pendiente. Tarjetas, tablas desplegables y tooltips conservan centavos originales.

ECharts requiere números binarios para las coordenadas: Number se usa exclusivamente en el trazado y etiquetas abreviadas de ejes/barras, nunca como fuente de totales o del importe exacto en tooltip/tabla. La posición gráfica es aproximada; una etiqueta abreviada no sustituye el valor financiero exacto. Tooltips renderMode:richText, sin HTML generado con nombres de clientes/productos. Nombres largos se abrevian visualmente en los ejes y se conservan completos en tooltips y tablas. Tooltips mensuales incluyen cantidad de facturas.

Se importan solo línea/barra, grid/tooltip/aria y renderer SVG. ResizeObserver adapta tamaños y dispose libera cada instancia. Son tres gráficos pequeños: 41 meses actuales y 10 puestos por ranking, sin cargar líneas de factura en el navegador, sin polling y sin librería adicional de gráficos, iconos o estilos. Fuentes del sistema, sin descargas de tipografías.

Diseño de escritorio con menú lateral; en pantallas pequeñas la navegación es horizontal y las tarjetas/gráficos se reorganizan. Hay enlaces reales a secciones, enlace de salto, controles de teclado, estados con roles accesibles y tablas exactas desplegables. Las tablas tienen desplazamiento propio cuando es necesario. El CSS respeta reducción de movimiento. Esta etapa no incluye filtros temporales porque la API no los ofrece.

## Estados y reintentos

Cada sección consulta y valida su propia respuesta; las demás siguen funcionando si una falla. Muestra carga, error seguro con Reintentar y listas vacías explícitas. Cero es un valor válido de KPI. Actualizar datos vuelve a consultar las cuatro rutas. No hay datos ficticios como fallback ni cifras antiguas presentadas como actualización correcta.

Timeout del frontend de 25 segundos por consulta y cancelación al desmontar o cambiar la consulta. La hora mostrada es hora local de recepción, no fecha de actualización del DWH. Actualización parcial significa que al menos una sección falló. En desarrollo StrictMode puede iniciar/cancelar una consulta adicional para comprobar limpieza; no hay polling permanente.

## CORS y resolución de problemas

Se conservaron los orígenes explícitos del backend: http://localhost:5173 y http://127.0.0.1:5173; no se añadieron comodines ni credenciales. Se comprobaron ambos contra /health con Origin y cada uno devolvió Access-Control-Allow-Origin correspondiente. Si CORS_ORIGINS está definido localmente sustituye los defaults: debe incluir ambos orígenes separados por coma, sin rutas. Reiniciar FastAPI después de cambios.

Si hay error: abrir /api/v1/health y /docs, confirmar FastAPI en puerto 8000, comprobar VITE_API_BASE_URL y la pestaña Network del navegador. HTTP 503 indica que el backend no logró consultar el DWH; no resolverlo exponiendo credenciales administrativas en React. No desactivar CORS indiscriminadamente. La API es local y CORS no es autenticación.

## Comprobaciones reproducibles

Desde la raíz:

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m pytest backend/tests -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Build en frontend/dist, ignorado por Git junto con node_modules y .env locales. El lockfile, código y .env.example se versionan. Para inspeccionar el build (con FastAPI iniciado):

```powershell
npm.cmd --prefix frontend run preview -- --port 5173 --strictPort
```

Detener antes el servidor Vite de desarrollo para liberar 5173. Evitar el puerto preview predeterminado 4173, que no está en el allowlist CORS.

Pruebas ficticias separadas de producción: contratos de las cuatro rutas, importes exactos/grandes, URL sin credenciales, estados y reintentos, cancelación, actualización, tooltips, ciclo de vida del gráfico y SVG generado por ECharts real sin navegador. Los fixtures viven solo en src/tests y no se importan en la aplicación.

Referencias técnicas: [Vite](https://vite.dev/guide/), [importación modular ECharts](https://echarts.apache.org/handbook/en/basics/import/), [resize/dispose](https://echarts.apache.org/handbook/en/concepts/chart-size/).

## Resultados de esta implementación

- 36 pruebas de frontend aprobadas en seis archivos; TypeScript sin errores.
- 86 pruebas del backend y 98 existentes aprobadas (220 en total contando frontend).
- Build de producción correcto con Vite 8.3.8. CSS ~10.20 KB (3.17 KB gzip), aplicación ~235.35 KB (73.94 KB gzip), gráficos ~525.81 KB (179.30 KB gzip), más runtime pequeño. El chunk de ECharts supera el aviso de 500 KB sin comprimir; el aviso es informativo, no se ocultó aumentando el umbral. No se midió pico de RAM.
- API real: KPI 172261341.20 / 25782098.25 / 198043439.45; 70510 facturas, 73595 pedidos y 663 clientes. Primera fila mensual enero 2013: 3770410.85 y 1639 facturas. Las respuestas reales tienen las propiedades utilizadas por los modelos TypeScript. Top producto por ventas: StockItemID 215; top cliente: CustomerID 149. No se fijan esos resultados en la interfaz.
- CORS real: ambos orígenes locales devolvieron su Access-Control-Allow-Origin correcto. No se modificó backend ni su configuración.
- Vite inició en 127.0.0.1:5173; ECharts real generó SVG en pruebas de renderizado sin navegador. Las herramientas de navegador/Computer Use de esta sesión fallaron al iniciar su kernel, por lo que **no se pudo completar revisión visual de escritorio/móvil ni interacciones reales de tooltip con puntero**. No se presenta esa revisión como aprobada.

Revisión visual manual pendiente: abrir el dashboard con FastAPI activo, confirmar seis tarjetas y tres gráficos; pasar el puntero por meses/barras; expandir tablas; comprobar nombres completos e importes; probar navegación con Tab y enlaces laterales; reducir ventana a 390 px y confirmar ausencia de desbordamiento de la página (las tablas sí pueden desplazarse internamente). Detener FastAPI, actualizar y comprobar errores con Reintentar; reiniciarlo y reintentar. Las pruebas automáticas ya cubren los estados de carga/error/vacío y cancelación con datos ficticios.

Archivos de la etapa: frontend/package.json y package-lock.json, index.html, .env.example, tsconfig.json, vite.config.ts; src/main.tsx, App.tsx, styles.css, vite-env.d.ts; src/lib (contratos/transporte, formato exacto, hook de consulta); src/components (Icon, SectionState, ResourceView, Chart y opciones ECharts); src/tests (fixtures y seis suites). README y esta documentación actualizados. .gitignore existente ya excluye dependencias, dist y variables locales sin ocultar código ni ejemplos. No hubo commit ni modificación de datos/DDL.
