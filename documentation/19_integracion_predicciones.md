# Integración de predicciones históricas (etapa 19)

## Arquitectura y contrato de origen

FastAPI lee **resumen.json** generado por la etapa 18. No importa machine-learning/, pandas, Scikit-learn, pickle ni joblib en la solicitud; no carga modelo.json ni ejecuta entrenamiento/predicción matemática en HTTP. El endpoint no abre conexiones a PostgreSQL. React sigue obteniendo el histórico desde GET /api/v1/ventas/por-mes, sin cambiar su definición ni credenciales.

Se inspeccionó el archivo real de la ejecución 20261115T163544Z-350622116680: schema_version=1, metric, coverage, evaluation.selected_model, evaluation.results[modelo].selection y holdout, evaluation.design, uncertainty y forecasts. Se publican campos de ese contrato, no se copian resultados del prompt al código. No se transmiten environment, config, source, coverage_note, rutas, advertencias libres ni otros metadatos del archivo. La API agrega una identificación de unidad y la advertencia fija de que la completitud no está certificada.

## Endpoint

`GET /api/v1/predicciones/ventas`, sin parámetros de consulta:

- selected_model: naive / moving_average_3 / ridge, tomado del archivo.
- metric: ventas_sin_impuestos; currency:null porque la moneda no está verificada.
- backtesting y holdout: mae, rmse y smape del candidato seleccionado. Se envían como **cadenas decimales**, manteniendo toda la precisión escrita en el JSON de origen. Las tarjetas indican backtesting, no ajuste de entrenamiento ni holdout.
- coverage: meses observados/utilizables, primer/último mes, complete_through, exclusiones y fechas/días de facturación del último mes observado.
- design: horizonte, ventana inicial, número de orígenes y prueba final; uncertainty: método y cantidad de errores por horizonte.
- forecasts: exactamente tres objetos month, forecast, lower, upper, historical_abs_error_p90. Los importes deben llegar como cadenas de dos decimales; no se aceptan floats monetarios ni se recalculan estimaciones.
- input_sha256: huella de trazabilidad del artefacto; completeness_verified:false y coverage_warning explican la limitación de cobertura.

HTTP 503 si falta el archivo, hay error de acceso, ruta fuera del directorio permitido, JSON corrupto, excesivo o incompatible. Mensaje público: `Predicciones no disponibles: falta un artefacto válido. Revise la configuración local.` No incluye ruta ni error del parser. Cualquier parámetro de consulta devuelve 422: el cliente no puede seleccionar archivos, ejecuciones ni modelos. No hay POST ni reentrenamiento HTTP.

## Ruta segura y publicación local

Variable del **backend** `BACKEND_FORECAST_PATH`, independiente de BACKEND_DB_*, SUPABASE_DB_* y VITE_*.

Default documentado, relativo a la raíz del repositorio:

```dotenv
BACKEND_FORECAST_PATH=artifacts/machine_learning/published/resumen.json
```

Solo se aceptan rutas resueltas bajo artifacts/machine_learning/ con nombre final resumen.json. Se normalizan rutas relativas/absolutas y se comprueba el destino resuelto de enlaces; una ruta que escape produce 503. La variable se configura en entorno de proceso o .env raíz, con precedencia del proceso, igual que las demás variables del backend. No se expone al navegador. Una configuración inválida no impide /health.

No hay búsqueda automática de «la última ejecución»: debe elegirse un resumen aprobado. El servidor lee y valida hasta 256 KiB por solicitud, sin caché de modelos ni dependencia de bases de datos. Esto permite sustituir un archivo publicado de forma atómica fuera del servidor; un archivo parcialmente escrito se rechaza, nunca se sirve como válido. No es un sistema de firma/auditoría de artefactos; solo los operadores locales deben poder escribir esa carpeta.

Para esta integración se creó una copia **nueva** validada en published/resumen.json del resumen real existente, sin sobrescribir archivos originales ni reentrenar. Esa copia y todos los artefactos permanecen ignorados por Git. En un clon de GitHub no estarán presentes: configurar una ruta existente o generar localmente el artefacto antes de esperar HTTP 200. Sin artefacto, la UI muestra el error y no inventa datos.

## Cómo localizar o generar el resumen

Desde PowerShell en la raíz:

```powershell
Get-ChildItem -Path artifacts/machine_learning -Filter resumen.json -Recurse | Select-Object FullName
# Elegir explícitamente una ejecución revisada; ejemplo local de esta etapa:
$env:BACKEND_FORECAST_PATH = 'artifacts/machine_learning/20261115T163544Z-350622116680/resumen.json'
```

El nombre de ejecución cambiará en otra máquina. No imprimir .env ni copiar sus credenciales al frontend. Para conservar la configuración, agregar BACKEND_FORECAST_PATH al .env raíz, sin borrar las variables existentes.

Si no hay artefactos, seguir primero la etapa 18. Estos comandos son trabajo **offline explícito**, nunca los ejecuta FastAPI:

```powershell
.\.venv\Scripts\python.exe -m pip install -r machine-learning/requirements.lock.txt
# Conservador: excluye el último mes observado si no se declara cierre.
.\.venv\Scripts\python.exe machine-learning/pronosticar_ventas.py
```

Para reproducir el experimento que incluye mayo, revisar el cierre y usar `--complete-through 2016-05 --coverage-note "Cierre declarado para experimento, no auditoria de completitud"`, como explica documentation/18_machine_learning.md. Después apuntar BACKEND_FORECAST_PATH al resumen recién creado. No reentrenar para cada visita al dashboard.

## Arranque en dos terminales

**Terminal 1, raíz:** seleccionar ruta (o usar la copia predeterminada local) y arrancar FastAPI. Reiniciar el proceso si ya estaba ejecutándose con una versión previa o si cambia la variable.

```powershell
$env:BACKEND_FORECAST_PATH = 'artifacts/machine_learning/20261115T163544Z-350622116680/resumen.json'
.\.venv\Scripts\python.exe -m backend
```

**Terminal 2, raíz:**

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

frontend/.env conserva VITE_API_BASE_URL=http://127.0.0.1:8000 (valor predeterminado). No hay secretos ni conexiones de PostgreSQL en el navegador. Abrir http://127.0.0.1:5173 y navegar a Predicciones. CORS mantiene los dos orígenes locales existentes, sin comodines nuevos.

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/predicciones/ventas'
```

Swagger: http://127.0.0.1:8000/docs. Detener con Ctrl+C. Para volver al default en esa terminal: `Remove-Item Env:BACKEND_FORECAST_PATH` (si se configuró también en .env, seguirá aplicándose el valor del archivo).

## Validación del resumen y del gráfico

Backend: JSON con claves únicas, sin NaN/Infinity, schema_version entero 1, objetivo exacto, importes/bandas coherentes, métricas finitas no negativas (sMAPE hasta 200), tres candidatos y ganador consistente con MAE de selección. Fechas consecutivas, conteos y exclusiones coherentes, holdout separado y diseño consistente; tres pronósticos inmediatamente después de complete_through. No se acepta un último mes incluido sin facturación en su cierre calendario, conforme a la guardia de etapa 18. Esa condición es conservadora y **no certifica** que el mes esté completo.

Frontend: valida el contrato, moneda no asignada, unidad y rangos; coteja número de meses, fechas inicial/final y continuidad del histórico real contra coverage. Si no coincide, bloquea el gráfico y permite reintentar ambas consultas. Si el artefacto excluyó meses observados (por ejemplo mayo en modo conservador), el tramo real del gráfico termina en complete_through y se indican explícitamente las exclusiones; no se superpone el mes observado excluido como si fuera dato de entrenamiento.

No se recalcula la huella input_sha256 desde el endpoint mensual, porque esa respuesta no incluye las fechas de cobertura que forman parte de la huella original. La coincidencia de fechas/unidad no prueba igualdad numérica de la extracción ni certificación de completitud. Si se actualiza el DWH, revisar el artefacto antes de publicarlo; no se reentrena automáticamente.

ECharts: línea verde azulado para reales, línea discontinua ámbar para pronóstico (con ancla en el último real), área tenue para la banda descriptiva. El tooltip del ancla sigue etiquetado Real. Las posiciones usan Number solo para dibujar; tooltips y tabla conservan las cadenas originales. Las métricas se redondean a dos decimales HALF_EVEN mediante BigInt solo al presentarlas. sMAPE muestra porcentaje. No se interpreta la banda como 90% de confianza o garantía: es un resumen de errores históricos, con pocos datos y dependencia temporal.

Cada sección tiene carga, error, vacío y reintento. La falta de artefacto no bloquea KPI ni rankings; el histórico mensual se reutiliza, no se solicita otra vez en estado normal. Actualizar datos vuelve a consultar las cinco rutas. No hay fallback ficticio ni datos antiguos presentados como respuesta nueva.

## Mayo de 2016: advertencia obligatoria

El resumen real indica facturación del **2 al 31 de mayo de 2016**, 26 días con ventas, y cierre **declarado**, no auditado. La etapa 18 no dispone de una marca de cierre comercial o conciliación que certifique todas las facturas del mes. No se puede concluir que mayo fue completo solo por llegar al día 31. No se modificaron el artefacto de entrenamiento ni el DWH para cambiar esa suposición.

La interfaz muestra cobertura del último mes observado «no certificada», fechas y días reales del archivo. También mantiene siempre visible:

> Pronóstico histórico experimental; no representa ventas actuales ni garantiza resultados futuros

Los pronósticos son para junio–agosto de **2016**, no para 2026. La selección y su incertidumbre siguen sujetas a las limitaciones de la etapa 18.

## Pruebas

Desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s machine-learning/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Fixtures únicamente sintéticos: formas JSON y decimales grandes, valores corruptos, ausencia/exceso de archivo, unidades/modelo/bandas/períodos incompatibles, rechazo de parámetros/rutas externas, filtrado de metadatos privados, endpoint sin pandas/Scikit-learn/DB, estados UI y reintentos, unión temporal y renderizado SVG real de ECharts. La revisión visual del navegador es adicional a estas pruebas.

## Resultados ejecutados

- 107 pruebas backend, 46 frontend, 20 ML y 98 existentes aprobadas (271 total). TypeScript y build correctos; git diff --check sin errores.
- Integración real con TestClient: nuevo GET y GET mensual devolvieron 200, 41 meses y extremos temporales compatibles. Verificación HTTP adicional en un Uvicorn temporal de loopback: endpoint de predicciones 200; servidor temporal detenido al terminar.
- El backend validó el resumen sin importar pandas/Scikit-learn ni abrir conexión al DWH en la ruta de predicciones. Se reprodujeron los valores del archivo existente sin entrenar.
- Herramienta de navegador no disponible por fallo al iniciar kernel: no se acredita revisión visual de esta nueva sección. Pruebas de componentes y SVG real sí pasaron.
- Permanece la advertencia informativa del build de ECharts por chunk de 525.81 KB (179.30 KB gzip); no se incrementó el umbral para ocultarla.

Valores leídos del resumen local validado para esta documentación:

Modelo: `moving_average_3`. MAE de selección: 266657.8354423868; RMSE: 352555.6987396208; sMAPE: 5.905083044486336%.

| Mes | Estimación | Inferior | Superior |
| --- | ---: | ---: | ---: |
| 2016-06 | 4726617.58 | 4051651.68 | 5401583.49 |
| 2016-07 | 4753738.78 | 4151498.35 | 5355979.21 |
| 2016-08 | 4817096.34 | 4144432.87 | 5489759.80 |

La completitud de mayo no está verificada: la cobertura declarada del archivo se informa con advertencia visible, no como hecho auditado. No se modificaron SQL Server, Supabase, ETL, DWH ni artefactos originales. No se hizo commit.
