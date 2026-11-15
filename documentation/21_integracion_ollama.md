# Ollama local con Qwen3 (etapa 21)

## Alcance y cambios respecto a etapa 20

Se reutiliza POST /api/v1/asistente/consultar, sus cinco temas, las consultas autorizadas y ProviderPlan. Se integra el modelo **qwen3:1.7b** ya instalado con Ollama en **http://127.0.0.1:11434/api/chat**. No se instalan paquetes nuevos, no se descargan ni entrenan modelos y no se modifican DWH, ETL, modelos predictivos, artefactos o políticas de acceso.

Esta etapa sustituye el timeout opcional inicial de 5 s por **30 s**, configurable entre 1 y 60. El cliente espera hasta 90 s y puede cancelarse al desmontar. La interfaz identifica el proveedor y modelo **realmente utilizados**, no solo el configurado. El modo de reglas locales permanece como default sin variables y como alternativa ante fallo de Ollama.

## Lenguaje natural y límite de confianza

La clasificación local reconoce variantes en español y conserva acentos/puntuación como entrada natural (normaliza para clasificación). Ejemplos equivalentes:

| Tema | Formulaciones admitidas |
| --- | --- |
| KPI | Dame un resumen de los KPI; ¿cómo marcha el negocio?; nuestra facturación total; cifras generales |
| Mensual | ¿Cómo cambiaron las ventas?; ventas mes a mes; ¿cómo se comportaron las ventas?; mes con mayor venta |
| Productos | Productos destacados; artículos con más ventas; ¿qué se vende más? |
| Clientes | Clientes destacados; compradores principales; ¿quiénes nos compran más?; cuentas comerciales que lideran |
| Pronósticos | Pronósticos históricos; previsiones de ventas; estimaciones de ventas mensuales; ¿qué se espera vender? |

En «previsión mensual», mensual se interpreta como frecuencia del pronóstico, no como otra pregunta. Consultas ambiguas de varios temas, filtros de fechas/IDs/tamaños de ranking, conversiones de moneda, causas, dimensiones no disponibles o instrucciones peligrosas siguen fuera de alcance. No es conversación general ni comprensión irrestricta de cualquier frase. Es posible ampliar expresiones sin permitir SQL dinámico.

**La pregunta libre no se envía al LLM.** La clasificación y obtención de hechos se realizan en el backend; Ollama solo recibe tema, período, agregados, métricas, advertencias y referencias f1…f8. No recibe nombres, IDs comerciales, preguntas con datos personales, credenciales, archivos, SQL o filas individuales. Supabase solo se consulta desde el backend con BACKEND_DB_* / wwi_backend_reader y los servicios existentes.

Ollama devuelve un plan estructurado para organizar hechos e interpretación permitida. Pydantic y el servicio comprueban que conserve todos los hechos exactamente una vez y no cambie de interpretación. Las cifras y fechas finales se insertan desde los resultados verificados, **nunca desde prosa del modelo**. No existe herramienta de SQL, código, comandos ni acceso libre a archivos para Qwen. Se mantiene deliberadamente la restricción de etapa 20: no se habilita redacción generativa libre, para evitar hechos o causas inventadas.

## Razonamiento interno y salida final

La petición utiliza `think:false`, `stream:false`, `/no_think`, JSON Schema, temperatura cero, num_predict=256, num_ctx=2048 y num_thread=2. keep_alive=2m conserva temporalmente el modelo cargado sin descargar otros ni cambiar sus pesos.

- Se ignoran message.thinking y campos equivalentes del envoltorio; no se registran ni devuelven.
- Si content contiene un bloque legado `<think>…</think>` al principio, se descarta el bloque completo y se valida solo el JSON final.
- Un bloque sin cerrar, bloques adicionales, contenido vacío, salida truncada, herramientas o campos no permitidos provocan fallback. No se intenta convertir razonamiento en una explicación pública.
- Se admite un único envoltorio markdown ```json del plan final para compatibilidad; no se ejecuta su contenido.

El usuario recibe únicamente los hechos verificados, interpretación controlada y limitaciones, nunca el razonamiento privado. [Documentación oficial de thinking de Ollama](https://ollama.com/blog/thinking).

Límites existentes conservados: entrada 5–500 caracteres, contexto 8 KiB, petición 16 KiB, envoltorio de respuesta 8 KiB y JSON final 2048 caracteres (antes de extraerlo se limita content a 4096). JSON sin duplicados ni valores no finitos. Un worker/slot evita colas y generación paralela ilimitadas; si está ocupado o falla, se usa reglas. El límite de espera no equivale al timeout total de las consultas del DWH, y una inferencia iniciada puede continuar hasta finalizar en el proceso local después de que el cliente deje de esperar.

## Configuración Windows

No se sobrescribió el .env privado. La aplicación carga las siguientes variables del entorno o .env raíz; el proceso prevalece. Se conservan todas las variables de SQL Server/Supabase y BACKEND_DB_* existentes.

```dotenv
ASSISTANT_PROVIDER=ollama
ASSISTANT_OLLAMA_MODEL=qwen3:1.7b
ASSISTANT_OLLAMA_URL=http://127.0.0.1:11434/api/chat
ASSISTANT_LLM_TIMEOUT=30
```

.env.example conserva ASSISTANT_PROVIDER=local como opción segura por defecto y muestra el modelo de esta etapa. Si se activa ollama sin especificar modelo, el loader usa qwen3:1.7b. No hay clave de proveedor. No copiar credenciales al frontend ni imprimir .env.

Comprobar la instalación existente:

```powershell
Invoke-RestMethod 'http://127.0.0.1:11434/api/version'
ollama list
```

El usuario ya descargó/probó qwen3:1.7b. **No es necesario volver a descargarlo.** Si Ollama no está iniciado, abrir la aplicación de Windows o ejecutar `ollama serve` en su propia terminal. No ejecutar una segunda instancia si el puerto ya responde.

**Terminal de FastAPI, desde la raíz:**

```powershell
$env:ASSISTANT_PROVIDER = 'ollama'
$env:ASSISTANT_OLLAMA_MODEL = 'qwen3:1.7b'
$env:ASSISTANT_OLLAMA_URL = 'http://127.0.0.1:11434/api/chat'
$env:ASSISTANT_LLM_TIMEOUT = '30'
.\.venv\Scripts\python.exe -m backend
```

Reiniciar el backend anterior con Ctrl+C desde su terminal si ocupaba 8000. No es necesario cambiar permisos de PostgreSQL ni CORS. Para consultar pronósticos, conservar el resumen validado y BACKEND_FORECAST_PATH de etapa 19.

**Otra terminal, desde la raíz:**

```powershell
# Solo si faltan las dependencias locales del frontend:
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

No se añade SDK de Ollama ni dependencia npm/Python. El adaptador usa la biblioteca estándar. Con 8 GB de RAM evitar iniciar otras cargas pesadas simultáneas; se limita el contexto y dos hilos, pero no se midió pico de RAM. La primera consulta puede cargar el modelo y tardar más. Si el límite de 30 s es insuficiente, se puede revisar el uso de recursos y configurar hasta 60; no se aumentan límites silenciosamente.

## Verificación desde el navegador

1. Abrir http://127.0.0.1:5173 → Asistente IA.
2. Escribir «¿Cómo cambiaron las ventas?» y pulsar Consultar.
3. Al completar, comprobar **Ollama local · qwen3:1.7b · hechos validados**, período, fuentes y cuatro advertencias. El rótulo se basa en la respuesta efectiva de FastAPI.
4. Probar una variante de productos/clientes y «Previsiones de ventas mensuales». El modelo predictivo moving_average_3 es diferente del LLM Qwen3: Qwen no reentrena ni sustituye ese modelo.
5. Verificar que no aparece `<think>`, thinking ni razonamiento. La interfaz muestra solo respuesta final validada como texto, sin HTML ejecutable.
6. Para probar la alternativa sin detener Ollama, reiniciar FastAPI con `$env:ASSISTANT_PROVIDER = 'local'`; debe mostrar **Reglas locales · no es IA generativa**. Con Ollama activado pero indisponible/salida inválida, debe mostrar ese mismo modo local y una advertencia explícita. Nunca se etiqueta como Ollama una respuesta de fallback.

Swagger continúa en http://127.0.0.1:8000/docs. La respuesta conserva modo y agrega proveedor (local/ollama) y modelo (nombre utilizado o null en fallback). No hay cambio de URL del endpoint. El formulario no consulta automáticamente al abrir y no guarda historial permanente.

No se permiten destinos cloud: guardias de loopback, sin proxy ni redirecciones, sin credenciales en URL y rechazo de nombres :cloud/-cloud se mantienen. El daemon local debe ser legítimo y no configurarse para reenviar a proveedores remotos. No se contrató servicio de pago ni se alteraron políticas de seguridad.

## Pruebas reproducibles sin modelo real

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
.\.venv\Scripts\python.exe -m unittest discover -s machine-learning/tests -q
```

Las suites usan contextos sintéticos, transporte/proveedor simulado y no dependen del daemon. Añaden variantes en español, parámetros think/recursos, reasoning separado, bloque legado, bloque truncado, salida parcial, modelo efectivo, fallback, configuración y etiqueta UI consistente. Las pruebas anteriores de inyección, privacidad, ruta segura, decimales y acceso lector se mantienen.

## Integración local ejecutada

Se comprobó la API local de **Ollama 0.40.16**, y /api/tags identificó qwen3:1.7b como modelo instalado no remoto. Una llamada con agregado sintético devolvió plan válido en 13.22 s.

Después se probaron los cinco temas mediante TestClient de FastAPI, consultas reales autorizadas y el proveedor local real:

| Tema | HTTP | Proveedor efectivo | Modelo | Segundos observados |
| --- | --- | --- | --- | ---: |
| KPI | 200 | ollama | qwen3:1.7b | 21.50 |
| Mensual | 200 | ollama | qwen3:1.7b | 11.74 |
| Productos | 200 | ollama | qwen3:1.7b | 11.82 |
| Clientes | 200 | ollama | qwen3:1.7b | 12.58 |
| Pronósticos | 200 | ollama | qwen3:1.7b | 19.04 |

Todos conservaron sus cuatro advertencias y no incluyeron razonamiento en la respuesta HTTP. Los tiempos son mediciones puntuales, no garantías de latencia. Las solicitudes al modelo contenían solo contexto agregado reducido, sin pregunta original ni datos personales.

Se mantienen las advertencias: moneda no verificada; pronósticos históricos y experimentales, no ventas actuales; mayo de 2016 no certificado como completo; bandas descriptivas sin garantía de cobertura. No se modificaron bases, ETL ni artefactos de predicción. No se hizo commit ni push.

Resultado de regresión: **170 pruebas backend + 55 frontend + 98 existentes + 20 ML = 343 aprobadas**. TypeScript y build de producción correctos; git diff --check sin errores. El build conserva el aviso informativo conocido del chunk ECharts (525.81 KB, 179.30 KB gzip); no está relacionado con Ollama. La integración real se comprobó por la API y las pruebas React, no mediante una nueva inspección visual del navegador.

Archivos de esta etapa: configuración y proveedor existentes, clasificador/contrato del asistente, backend/tests/test_ollama.py, contrato/componente/pruebas frontend del asistente, .env.example, README y esta documentación. No se duplicó el endpoint ni el acceso a datos. Los cambios previos ya presentes en el árbol de trabajo se conservaron; no se hicieron commit ni push.
