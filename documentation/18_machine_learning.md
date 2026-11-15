# Pronóstico mensual experimental (etapa 18)

## Alcance y datos

Módulo local Python/pandas/Scikit-learn, independiente de API y dashboard. Solo consulta agregados de dwh con `backend.app.config.load_settings().database` y `backend.app.database.read_connection`, usando exclusivamente BACKEND_DB_* / wwi_backend_reader, SSL y transacción read-only. No usa SUPABASE_DB_* ni credenciales administrativas. No requiere iniciar FastAPI: reutiliza su capa lectora sin modificarla.

La métrica es exactamente la del endpoint mensual: SUM(fact_ventas.ventas_sin_impuestos), is_credit_note=false, agrupada por anio/mes de fecha de factura. La consulta añade primera/última fecha, días con facturación y facturas distintas para revisar cobertura. Es un solo SELECT consistente, LEFT JOIN sobre la PK de dim_fecha y fetchmany(64); fechas desconocidas se rechazan, no se pierden silenciosamente. Solo se cargan 41 agregados, no líneas de factura. No hay escrituras al DWH.

La serie real contiene **41 meses consecutivos, enero 2013–mayo 2016**. Se exige orden original, unicidad, continuidad y cantidad de meses esperada; no se ordenan ni rellenan huecos silenciosamente. Se validan montos Decimal de dos decimales finitos, fechas en el mes y metadatos de cobertura. No se inventa moneda ni se imponen signos de negocio no aprobados: sMAPE acepta ceros y valores con signo.

## Meses completos: decisión explícita

- Enero 2013: facturación de 2013-01-01 a 2013-01-31.
- Mayo 2016: facturación de **2016-05-02 a 2016-05-31**, 26 días con ventas y total 4970932.65. El 1 de mayo fue domingo; la ausencia de ventas ese día no demuestra un mes parcial. Abril llega al día 30 y marzo al 31.
- El rango hasta 2016-05-31 ya estaba documentado en 03_definicion_kpis.md. Microsoft también describe la muestra original con corte al 31 de mayo de 2016. Esta referencia respalda el contexto del corte, pero no certifica la integridad de nuestra copia. [Descripción oficial de WWI](https://www.microsoft.com/en-us/sql-server/blog/2016/06/09/wideworldimporters-the-new-sql-server-sample-database/).

**Por defecto se excluye el último mes observado:** 40 meses utilizables hasta abril 2016. Para incluir mayo se requiere `--complete-through 2016-05` y una `--coverage-note` no vacía, guardada en el reporte. Si el último mes no contiene facturación hasta el final calendario, el programa rechaza incluirlo incluso con esa declaración: guardia conservadora que también puede excluir meses completos si el último día es inhábil. En ese caso usar el último mes anterior y revisar cobertura, sin imputar/extrapolar ventas ni desactivar silenciosamente la guardia. La llegada al último día tampoco prueba que estén todas las facturas.

La ejecución real de esta etapa declaró cierre hasta mayo basándose en el rango documentado y el SELECT de fechas: **41 meses utilizables bajo esa declaración**. No se encontró evidencia de corte dentro de mayo. No es una auditoría de completitud de origen ni una certificación contable. No hay calendario de días hábiles ni marca de cierre comercial en las cinco tablas que permita automatizar esa certificación.

## Modelos y variables

1. `naive`: repetir el último valor conocido para los tres horizontes.
2. `moving_average_3`: promedio de los tres últimos valores, recursivo; los siguientes pasos incorporan sus propias predicciones, nunca ventas futuras reales.
3. `ridge`: Pipeline(StandardScaler, Ridge(alpha=10, solver=svd)). Parámetro fijo previo a la evaluación, sin búsqueda de hiperparámetros con la prueba final. Variables: tendencia (posición mensual), seno/coseno del mes, lag 1/2/3/12 y promedio de los tres valores anteriores. Al menos doce meses para construir variables y 24 para el primer origen de backtesting.

Cada origen vuelve a ajustar Ridge y su escalador únicamente con su historia; no se calculan variables sobre objetivos futuros. Forecast a tres pasos recursivo en todos los candidatos. No se introducen holidays, crecimiento supuesto, promociones ni atributos de tablas no extraídas. No hay clipping de predicciones ni límites artificiales de ventas.

Los agregados originales permanecen Decimal en validación/CSV/huella. Scikit-learn trabaja con float64 para estimación, no para conciliación financiera. Los pronósticos se presentan con Decimal(str(valor)) y redondeo HALF_EVEN a dos decimales; son estimaciones, no importes contables exactos. [Guía Scikit-learn sobre rezagos y evaluación temporal](https://scikit-learn.org/stable/auto_examples/applications/plot_time_series_lagged_features.html).

## Evaluación sin fuga

Horizonte fijo de **tres meses**, ventana expansiva, inicio con 24 meses. Los últimos tres meses se reservan antes de seleccionar el modelo.

Con 41 meses: 12 orígenes de selección, entrenamientos que terminan entre diciembre 2014 y noviembre 2015; objetivos entre enero 2015 y febrero 2016. Son 36 pares origen/horizonte por candidato, con solapamiento. No equivalen a 36 meses distintos ni a errores independientes. Se reportan métricas agrupadas y por horizonte. Se permiten nuevos valores reales al avanzar al siguiente origen, como sería normal en backtesting.

La prueba final es **marzo, abril y mayo 2016**, pronosticada desde febrero 2016: no interviene en selección ni en escalado del entrenamiento de ese origen. El ganador se elige por **MAE de selección** (desempate en orden ingenuo/promedio/Ridge). No se cambia el ganador tras ver la prueba final. El modelo final se reentrena con todos los meses declarados completos antes de pronosticar junio–agosto.

Métricas: MAE, RMSE y sMAPE = promedio de 200 × |real−predicción| / (|real|+|predicción|), en porcentaje. Ambos valores cero aportan 0; no se usa MAPE. MAE/RMSE tienen unidades de ventas; no se les asigna moneda. sMAPE no elimina la dificultad de evaluar ventas cercanas a cero.

La selección también puede ser optimista por comparar candidatos en el mismo backtesting; la prueba final es pequeña y no garantiza estabilidad. Umbral descriptivo de mejora convincente: reducción de al menos 10% MAE de Ridge contra la mejor base, acompañado de revisión del holdout; no es un test estadístico.

## Resultados reales

| Modelo | MAE selección | RMSE selección | sMAPE selección | MAE prueba final | RMSE prueba final | sMAPE prueba final |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Ingenuo | 371324.16 | 467571.52 | 8.21% | 721000.73 | 742156.60 | 16.44% |
| Promedio móvil 3 | **266657.84** | 352555.70 | **5.91%** | 478659.93 | 525116.56 | 10.60% |
| Ridge | 279193.70 | **335204.14** | 6.19% | **211127.22** | **275385.48** | **4.47%** |

**Seleccionado: moving_average_3**, por menor MAE fuera de muestra en selección. Reduce aproximadamente 28.19% MAE frente al ingenuo; Ridge tiene aproximadamente 4.70% más MAE que la mejor base. Ridge presenta mejor RMSE de selección y mejor resultado en los tres meses finales, pero cambiar el criterio o ganador después de observarlos contaminaría esa prueba. No hay evidencia convincente y estable de ventaja de Ridge sobre la mejor base. Mantener el promedio móvil como referencia experimental; no promover automáticamente ningún modelo a producción.

## Pronóstico e incertidumbre

| Mes histórico posterior al corte | Pronóstico | Banda inferior | Banda superior |
| --- | ---: | ---: | ---: |
| 2016-06 | 4726617.58 | 4051651.68 | 5401583.49 |
| 2016-07 | 4753738.78 | 4151498.35 | 5355979.21 |
| 2016-08 | 4817096.34 | 4144432.87 | 5489759.80 |

Son los tres meses posteriores al último mes declarado válido, **no pronósticos para la fecha actual de 2026**. No existen ventas reales futuras en este experimento para validar esos tres valores.

Bandas descriptivas: pronóstico ± percentil 90 interpolado de los errores absolutos de selección del ganador, por horizonte (12 errores por horizonte). Semianchos: 674965.91 / 602240.43 / 672663.46. Se redondean límites desde valores sin redondear, por lo que la aritmética de cifras publicadas puede diferir un centavo. No se fuerza monotonía del ancho, no se recorta a cero, no son intervalos de confianza ni garantías de 90% de cobertura. Los errores están correlacionados y la muestra es pequeña; no cubren cambios de régimen, error de completitud ni incertidumbre total del modelo.

## Instalación y comandos PowerShell

Desde la raíz, usando Python 3.13 del proyecto; no requiere iniciar servidores:

```powershell
.\.venv\Scripts\python.exe -m pip install -r machine-learning/requirements.lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s machine-learning/tests -v
# Modo conservador: excluye el último mes, usa 40; no requiere declaración de cierre.
.\.venv\Scripts\python.exe machine-learning/pronosticar_ventas.py
# Repetir el experimento documentado con 41 meses:
.\.venv\Scripts\python.exe machine-learning/pronosticar_ventas.py --complete-through 2016-05 --coverage-note "Rango documentado hasta 2016-05-31; SELECT lector verifica facturacion hasta ese dia (26 dias con ventas). Cierre declarado para experimento, no auditoria de completitud."
```

La declaración de cobertura debe revisarse si cambia la extracción. El programa espera 41 meses por referencia actual, no por regla universal: `--expected-months` permite cambiarla deliberadamente; siempre verifica continuidad y mínimo de 30 para separar selección/prueba. No hay flags para usar credenciales administrativas.

Cada ejecución informa su carpeta. Para repetir predicciones desde la ejecución real guardada, sin conexión ni reentrenamiento:

```powershell
.\.venv\Scripts\python.exe machine-learning/predecir_ventas.py --run-dir artifacts/machine_learning/20261115T163544Z-350622116680
```

Sustituir la ruta por la impresa al entrenar en otra máquina; los artefactos no están en GitHub. `predecir_ventas.py` solo lee JSON validado bajo artifacts/, nunca ejecuta pickle. Falta de conexión, forma inválida, mes parcial, pocos datos o fallo de publicación abortan con código 1 y mensajes sin secretos.

## Artefactos y reproducibilidad

Salida bajo artifacts/machine_learning/<run_id>/, ya ignorada por .gitignore:

- resumen.json: decisiones de cobertura, métricas por modelo/horizonte, prueba final, advertencias, pronósticos, versiones, huellas SHA256 de serie y código; sin host, usuario de conexión, contraseña ni .env. La identificación fija del rol lector solo documenta el origen autorizado.
- modelo.json: nombre del ganador, historia necesaria, nombres de variables, parámetros de escalado/coeficientes si gana Ridge y calibración de errores. No contiene código serializado.
- serie_observada.csv: agregados reales originales y fechas de cobertura (incluye meses excluidos, si los hay), no registros de clientes/productos.
- backtesting.csv: predicciones/objetivos por modelo, origen, horizonte y partición.
- pronosticos.csv: los tres resultados con bandas descriptivas.

No se escribe fuera de artifacts/. Carpeta temporal y publicación mediante renombrado en la misma unidad; cada ejecución tiene ID único y no sobrescribe anteriores. Resumen sin timestamp/run_id interno para poder comparar contenido con la misma entrada, código, configuración y versiones. Se conserva requirements.lock.txt con las versiones probadas; requirements.txt declara dependencias directas. BLAS limitado a un hilo. No se midió pico de RAM; el volumen es pequeño, sin redes neuronales, búsquedas masivas, GPU ni entrenamiento paralelo.

Versiones ejecutadas: Python 3.13, pandas 3.1.1 y Scikit-learn 1.9.1; versiones numéricas adicionales quedan en resumen.json. Las operaciones de coma flotante pueden variar entre plataformas/versiones. No se versionan datos reales ni artefactos; solo código, requisitos, pruebas sintéticas y este resumen agregado solicitado.

## Pruebas y límites

20 pruebas ML sintéticas aprobadas: 41 meses/Decimal, huecos, duplicados, desorden, errores de fechas/montos/cobertura, exclusión preventiva, bloqueo de cierre posiblemente parcial, huella de entrada, errores seguros, rezagos, escalado por entrenamiento, predicción recursiva, métricas con ceros, holdout sin fuga, JSON reproducible, horizontes, incertidumbre y rutas/publicación independientes. Pruebas no consultan Supabase ni leen .env.

Las cinco tablas no incluyen un cierre auditado de mes, calendario comercial, promociones ni señales externas. Solo hay tres ciclos anuales completos y cinco meses adicionales. Hay selección de modelo con pocos errores, dependencia temporal, incertidumbre de cobertura y prueba final mínima. No se integró el modelo en FastAPI, React ni el DWH. El SQL de origen que ya tenía cambios locales se conservó sin modificarlo en esta etapa.

Regresión final: además de las 20 pruebas ML, pasaron las 86 pruebas del backend y las 98 existentes (204 ejecutadas en total). git diff --check sin errores. La predicción desde el JSON real reprodujo exactamente las tres cifras y bandas publicadas, sin conectarse al DWH.
