# Asistente de análisis de negocio (etapa 20)

## Qué ofrece y qué no

POST /api/v1/asistente/consultar interpreta preguntas acotadas sobre KPI, evolución mensual, productos destacados, clientes destacados y pronósticos históricos. Por defecto utiliza **reglas locales deterministas, gratuitas, sin clave y sin IA generativa**. El nombre de menú Asistente IA no implica que ese modo sea generativo; la interfaz y cada respuesta identifican el modo.

No genera SQL, no ejecuta código/comandos, no abre archivos elegidos por preguntas, no entrena modelos y no ofrece explicaciones causales. No modifica los cinco conjuntos del DWH, ETL, modelos ni artefactos. No añade dependencias a Python o npm.

## Arquitectura y fuentes

Question Pydantic → clasificación por reglas → funciones autorizadas → hechos verificables → interpretación/limitaciones permitidas → AssistantResponse Pydantic → React como texto.

La clasificación solo elige una rama fija. Se reutiliza AnalyticsRepository.monthly/kpis/products/customers y read_predictions de etapa 19; no se escriben nuevas consultas SQL ni se toma SQL del usuario/proveedor. Los rankings se limitan a tres posiciones. La serie debe tener fechas conocidas, consecutivas y ordenadas. Sus extremos determinan el período; no se copian fechas o cifras del prompt.

| Tema | Ejemplos | Datos usados |
| --- | --- | --- |
| kpis | Dame un resumen de los KPI; ¿cuántos pedidos hay? | Conteos y totales de kpis, período de monthly |
| mensual | ¿Cómo evolucionan las ventas por mes? | Número de meses, primero/último y máximo observado de monthly |
| productos | ¿Cuáles son los productos destacados? | Top 3 por ventas sin impuestos, identificado por StockItemID |
| clientes | ¿Cuáles son los clientes destacados? | Top 3 por ventas sin impuestos, identificado por CustomerID comercial |
| pronosticos | ¿Cuáles son los pronósticos históricos? | Resumen JSON validado, modelo, MAE/RMSE/sMAPE, tres estimaciones y bandas |

Los nombres de clientes/productos no se incorporan a la respuesta ni al contexto LLM. Las posiciones y ventas son agregados; no se leen transacciones individuales adicionales. El identificador comercial solo se muestra localmente para trazabilidad del ranking; tampoco se envía al proveedor. La verificación del pronóstico coteja extremos y cantidad de meses con monthly antes de combinar fuentes. Esto no demuestra completitud ni igualdad de la extracción si los valores cambiaron conservando las fechas; sigue aplicando la limitación de etapa 19.

Las consultas pueden ser sentencias/transacciones diferentes, como los endpoints existentes; no ofrecen una instantánea conjunta frente a cargas concurrentes. Se mantienen SSL, rol lector, timeouts de conexión/sentencia y manejo de conexiones existentes. El artefacto usa exclusivamente BACKEND_FORECAST_PATH y su lector acotado; nunca una ruta de la pregunta.

## Contrato HTTP

Solicitud JSON, sin parámetros de consulta:

```json
{"pregunta":"Dame un resumen de los KPI"}
```

Solo pregunta; campos adicionales se rechazan. Entre 5 y 500 caracteres, tras limpiar extremos, sin controles Unicode. Preguntas de un único tema. No admite filtros de fecha/identificador, dimensiones no disponibles, conversión de moneda ni tamaños de ranking configurables; preguntas con cifras o dimensiones fuera de alcance se rechazan sin consultar. Preguntas no soportadas o que piden instrucciones/SQL/credenciales/causas devuelven 200 con soportada:false, sin consultar datos ni llamar al proveedor. La lista léxica es una ayuda de clasificación, **no la barrera de seguridad**; la barrera es que no existe herramienta de ejecución, SQL dinámico o acceso libre a archivos en el flujo.

Respuesta:

- soportada y tema: alcance elegido.
- modo: reglas o llm_local_restringido.
- respuesta.hechos: afirmaciones construidas exclusivamente con datos tipados de las funciones autorizadas.
- respuesta.interpretacion: descripción permitida que no agrega cifras ni causalidad.
- respuesta.limitaciones: límites de alcance y calidad.
- fuentes: nombres y rutas estáticas de los GET utilizados; no rutas de disco, SQL ni credenciales.
- periodo.inicio/fin: meses históricos YYYY-MM; null en consultas no soportadas.
- advertencias: siempre incluye moneda no verificada, pronósticos históricos experimentales, mayo de 2016 no certificado y bandas sin garantía de cobertura.

Los importes de los hechos se convierten desde Decimal a texto con dos decimales, sin pasar a float ni inventar símbolo monetario. Las métricas de ML mantienen la precisión del artefacto. El caso pronósticos muestra también cobertura observada y aclara que no está certificada.

Errores de forma/límites: 422. Si falla la consulta autorizada, faltan datos o no está disponible un artefacto válido: 503 con mensaje genérico, sin excepción del driver ni rutas internas. No hay respuesta numérica ficticia como fallback. Un fallo del proveedor opcional sí puede caer a **reglas con los mismos hechos reales** y advertencia explícita: no se inventan valores.

La respuesta exitosa lleva Cache-Control:no-store. No se escribe historial de preguntas/respuestas en archivos, logs de aplicación o localStorage. El acceso HTTP normal de Uvicorn no registra cuerpos, pero cualquier proxy/middleware adicional debe revisarse antes de despliegue. No introducir secretos en preguntas.

## Modo local y arranque Windows

Las variables se consumen desde entorno del proceso o .env raíz, sin modificar variables existentes ni imprimir .env. Proceso prevalece sobre archivo.

```dotenv
ASSISTANT_PROVIDER=local
ASSISTANT_OLLAMA_MODEL=
ASSISTANT_OLLAMA_URL=http://127.0.0.1:11434/api/chat
ASSISTANT_LLM_TIMEOUT=5
```

**Terminal 1, raíz:**

```powershell
$env:ASSISTANT_PROVIDER = 'local'
.\.venv\Scripts\python.exe -m backend
```

Para pronósticos debe existir el resumen de etapa 19, configurado con BACKEND_FORECAST_PATH; si falta, esa pregunta devuelve error controlado sin afectar los otros temas.

**Terminal 2, raíz:**

```powershell
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run dev
```

Abrir http://127.0.0.1:5173 → Asistente IA. Elegir un ejemplo (editable), pulsar Consultar. Hay estados inicial, carga, respuesta, consulta no soportada y error con reintento; se aborta al desmontar y tras 60 segundos en el navegador. No se envían consultas automáticamente al cargar la página. El último intento queda solo en memoria de la pestaña para reintentar.

Para comprobar el endpoint:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/asistente/consultar' -Method Post -ContentType 'application/json; charset=utf-8' -Body '{"pregunta":"Dame un resumen de los KPI"}'
```

Swagger: http://127.0.0.1:8000/docs. Reiniciar FastAPI tras actualizar código/configuración. CORS conserva únicamente los orígenes configurados (por defecto localhost:5173 y 127.0.0.1:5173), con GET y POST para el nuevo JSON; sin credenciales ni comodines. Permitir preflight POST no hace que los GET acepten escrituras: conservan 405 en POST. CORS no sustituye autenticación; uso local de desarrollo, no exponer públicamente sin límites de acceso y control de abuso.

## Proveedor LLM opcional: decisión conservadora

Hay una interfaz Provider.generate(context) y un adaptador Ollama, **desactivado por defecto**. No se contrató ningún servicio, no se descargó ni inició un modelo y no se hicieron llamadas LLM reales. La prueba de transporte usa mocks.

Por seguridad, el proveedor no puede redactar prosa libre ni producir cifras. Solo devuelve un ProviderPlan con fact_ids, interpretation y limitation: ordena todos los IDs de hechos exactamente una vez y confirma códigos permitidos. Se valida con Pydantic extra=forbid y se comprueba que la interpretación corresponda al tema. El servidor compone hechos/interpretación/limitaciones, no presenta prosa sin verificar del modelo. La UI lo etiqueta «LLM local · organización validada de hechos», no como conversación generativa abierta. Es una interfaz deliberadamente restringida; habilitar redacción libre requeriría otra evaluación de seguridad y factualidad.

Contexto permitido: tema normalizado (no pregunta), meses, conteos, importes agregados, métricas, posiciones anónimas y advertencias. Se excluyen pregunta libre, nombres, IDs de clientes/productos, emails, credenciales, rutas, SQL y filas individuales. Incluso si la pregunta contiene instrucciones maliciosas, no alcanza el prompt del proveedor. Ningún tool-call es aceptado; tampoco existen herramientas ejecutables asociadas al LLM.

Para probar opcionalmente **un modelo ya instalado y ejecutado localmente por el usuario**, configurarlo antes de iniciar FastAPI:

```powershell
$env:ASSISTANT_PROVIDER = 'ollama'
$env:ASSISTANT_OLLAMA_MODEL = 'REEMPLAZAR_POR_MODELO_LOCAL_INSTALADO'
$env:ASSISTANT_OLLAMA_URL = 'http://127.0.0.1:11434/api/chat'
$env:ASSISTANT_LLM_TIMEOUT = '5'
.\.venv\Scripts\python.exe -m backend
```

No ejecutar ese ejemplo sin reemplazar el nombre y decidir conscientemente usar el proveedor local. No se recomienda ni instala un modelo concreto; con 8 GB de RAM el modo de reglas es la opción predeterminada. El adaptador no descarga modelos ni configura cuentas/API keys. Configurar el daemon local sin reenvío a cloud; la aplicación confía en que ese proceso local sea legítimo. Se rechazan nombres con :cloud/-cloud y destinos remotos; esto no audita la implementación del daemon.

URL admitida: HTTP en direcciones literales 127.0.0.1 o ::1, ruta /api/chat, sin usuario, contraseña, query o fragmento. Sin proxy de entorno ni redirecciones. Se usa salida estructurada Ollama (`format` con JSON Schema, stream:false), temperatura cero y límite de tokens solicitado. [Contrato oficial de salida estructurada](https://ollama.com/blog/structured-outputs).

Límites: contexto hasta 8 KiB, petición hasta 16 KiB, envoltorio de respuesta hasta 8 KiB y plan textual hasta 2048 caracteres. JSON con claves únicas, sin constantes no finitas, sin extras o herramientas. Timeout de proveedor de 1 a 10 segundos (default 5), tanto al esperar el resultado como en socket. Un único worker/slot; si está ocupado o vence la espera, se utiliza modo local. Un worker de red lento puede seguir hasta terminar su socket, pero no se crean workers/colas ilimitados y los resultados tardíos no se muestran. Las consultas del DWH mantienen sus propios timeouts; el timeout LLM no es el timeout global del endpoint.

No hay adaptadores de pago o cloud ni envío a servicios externos en esta etapa. Añadirlos requiere autorización explícita de uso/coste, revisar privacidad y nuevas pruebas. No reutilizar claves de Supabase/SQL Server como credenciales de proveedor.

## Pruebas reproducibles

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s machine-learning/tests -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Fixtures solo sintéticos y proveedor simulado: cinco temas, preguntas no soportadas, inyección/causalidad, tamaño/campos/control, métricas e importes exactos, fuentes y advertencias, fallo seguro, compatibilidad temporal, contexto sin datos personales/credenciales, plan inventado o extra, timeout, transporte/tamaño, configuración segura, POST/CORS, formulario, ejemplo editable, carga, reintento, cancelación y renderizado de texto sin HTML ejecutable.

## Resultados de esta etapa

- 143 pruebas backend, 53 frontend, 20 ML y 98 existentes aprobadas: **314 total**. Ninguna prueba usó un proveedor externo real. TypeScript y build correctos; git diff --check sin errores.
- Validación real en modo local explícito mediante TestClient: KPI, evolución mensual, productos, clientes y pronósticos respondieron HTTP 200, fuentes autorizadas y período 2013-01 a 2016-05. El resumen KPI leyó 172261341.20 / 25782098.25 / 198043439.45; producto destacado StockItemID 215; cliente destacado CustomerID 149. Esos resultados no son constantes de implementación.
- El tema pronósticos obtuvo moving_average_3 y las métricas completas del resumen validado, sin reentrenar ni modificar el archivo. Todas las respuestas incluyeron advertencias de moneda, mayo no certificado, horizonte histórico y bandas.
- HTTP real adicional en un Uvicorn temporal de loopback: POST 200 en modo reglas con cuatro advertencias. Preflight POST 200 para localhost:5173 y 127.0.0.1:5173. El proceso temporal propio se detuvo; no se interrumpieron servidores del usuario.
- Revisión visual pendiente: la herramienta de navegador no pudo iniciar el kernel. No se afirma revisión visual real en escritorio/móvil para esta sección. Sí se probaron el formulario React, estado inicial/carga/error/respuesta, ejemplos, reintento, cancelación y texto seguro.
- Build mantiene el aviso informativo conocido de chunk ECharts de 525.81 KB sin comprimir (179.30 KB gzip). No se ocultó ni se añadieron dependencias.

Archivos nuevos: backend/app/assistant.py, assistant_models.py, assistant_provider.py, routers/assistant.py y backend/tests/test_assistant.py; frontend/src/components/AssistantPanel.tsx, frontend/src/lib/assistant.ts y frontend/src/tests/assistant.test.tsx; esta documentación. Actualizados config/main y pruebas CORS/OpenAPI, App/estilos, README y .env.example.

Decisiones pendientes, sin bloquear modo local: si usar un LLM local real, elegir uno ya instalado que quepa en el equipo y verificarlo manualmente; el adaptador se probó con simulación. Cualquier proveedor cloud/de pago, redacción libre o exposición pública requiere autorización y revisión separada. No se modificaron SQL Server, Supabase, ETL, DWH, modelos ML ni artefactos existentes. No hubo commit.
