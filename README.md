# DataInsight-WWI

Primer examen de Tecnologia Emergente.

## Descripción

**DataInsight WWI — Plataforma Integral de Ingeniería de Datos y Analítica Inteligente** es un proyecto universitario que integra datos de WideWorldImporters, los transforma con Python y los organiza en un Data Warehouse en Supabase PostgreSQL. La plataforma ofrecerá consultas mediante una API, dashboards interactivos, modelos de Machine Learning, funciones de IA generativa y alertas automatizadas.

El Data Warehouse de ventas está cargado y conciliado, según el estado confirmado del proyecto. El backend inicia con FastAPI y un endpoint health sin conexión a datos; los endpoints de negocio y el frontend siguen pendientes.

## Tecnologías

- SQL Server y WideWorldImporters como fuente original.
- Python para los procesos ETL.
- Supabase PostgreSQL para staging y Data Warehouse.
- FastAPI para el backend.
- React y TypeScript para el frontend.
- Apache ECharts para los dashboards.
- Scikit-learn para Machine Learning.
- IA generativa y notificaciones automatizadas, con proveedor y canal por definir.
- Vercel para publicar el frontend.

## Estructura del repositorio

```text
DataInsight-WWI/
├── documentation/          Documentación técnica y académica
├── database/
│   ├── source/             Scripts y referencias de la fuente SQL Server
│   ├── staging/            Scripts de la capa staging en PostgreSQL
│   └── data-warehouse/     Modelo dimensional y scripts del Data Warehouse
├── etl/                    Extracción, transformación y carga con Python
├── backend/                API con FastAPI
├── frontend/               Aplicación React, TypeScript y Apache ECharts
├── machine-learning/       Entrenamiento y evaluación con Scikit-learn
├── generative-ai/          Integración de IA generativa
├── notifications/          Alertas automatizadas
├── tests/                  Pruebas de los componentes
├── deployment/             Configuración futura de despliegue
├── .env.example            Variables de entorno de referencia
├── .gitignore              Exclusiones de Git
└── README.md
```

Las carpetas vacías incluyen un archivo `.gitkeep` para conservarlas en Git.

## Configuración de entorno

El archivo `.env.example` contiene los nombres de las variables previstas y valores locales de referencia. Cuando se implemente cada componente, copiarlo a `.env` y completar únicamente las variables necesarias. `.env` está excluido de Git.

Las contraseñas, claves privadas y la clave de servicio de Supabase deben permanecer en procesos del lado del servidor. Las variables con prefijo `VITE_` son públicas y deben contener únicamente configuración apta para el navegador.

Cada componente consume únicamente su configuración documentada. El backend usa BACKEND_HOST, BACKEND_PORT y CORS_ORIGINS; reserva BACKEND_DB_* para un futuro rol lector, sin reutilizar las credenciales administrativas del ETL.

## Fases de desarrollo

1. **Preparación del repositorio.** Crear la estructura, las exclusiones de Git y las variables de referencia.
2. **Análisis y diseño.** Definir preguntas de negocio, indicadores, alcance y modelo dimensional a partir de WideWorldImporters.
3. **Base de datos y ETL.** Diseñar staging y Data Warehouse e implementar cargas por lotes con validaciones de calidad.
4. **Backend.** Exponer consultas e indicadores mediante FastAPI.
5. **Frontend y dashboards.** Construir las pantallas e integrar las visualizaciones con Apache ECharts.
6. **Machine Learning.** Definir casos de uso, preparar datos y evaluar modelos con Scikit-learn.
7. **IA generativa y alertas.** Implementar los casos de uso seleccionados y sus notificaciones.
8. **Pruebas y despliegue.** Validar la integración, documentar los resultados y publicar el frontend en Vercel.

## Trabajo con 8 GB de RAM

Desarrollar y ejecutar los componentes por etapas. Utilizar cargas ETL por lotes y conjuntos de datos acotados durante las primeras pruebas. Supabase alojará staging y el Data Warehouse. Planificar el uso de SQL Server según los recursos disponibles y evitar ejecutar simultáneamente todos los componentes locales.

La prueba de conexión usa autenticación integrada de Windows y pyodbc. Consulta [instalación y ejecución en PowerShell](documentation/05_conexion_sqlserver.md). El script lee variables de entorno del proceso; no carga `.env` automáticamente. Esta etapa no implementa transformaciones ni cargas.

La [primera extracción RAW](documentation/06_extraccion_raw.md) guarda muestras de 100 filas por tabla en data/raw/ mediante lotes pequeños. Requiere Python 3.12 o superior. Los CSV locales están excluidos de Git.

La [validación RAW → VALIDATED](documentation/07_validacion_calidad.md) separa registros válidos y cuarentena y genera un reporte de calidad local. Requiere Python 3.13 o superior; no aplica claves foráneas entre las muestras independientes.

La [extracción completa](documentation/08_extraccion_completa.md) añade modos muestra/completo, lotes configurables (500 por defecto), conteos contra SQL Server y directorios RAW por ejecución. La muestra sigue siendo el modo predeterminado y el validador acepta --raw-dir.

El [modelo dimensional de ventas](documentation/09_modelo_dimensional.md) define una estrella al grano de InvoiceLineID, dimensiones de fecha/cliente/producto y seguimiento de pedidos independiente. Incluye un DDL PostgreSQL comentado y comprobaciones locales sobre la extracción completa; no se han creado tablas físicas del DWH ni conectado Supabase.

La [transformación local VALIDATED → READY](documentation/10_transformacion_ready.md) prepara las tres dimensiones y los hechos de ventas/pedidos con claves reproducibles, referencias completas y conciliación por cliente/mes. Guarda ejecuciones independientes en data/ready/; no conecta Supabase ni carga el DWH físico.

La [preparación del DDL físico en Supabase PostgreSQL 17](documentation/11_creacion_dwh_supabase.md) entrega la creación inicial de las cinco tablas dwh, restricciones, índices, revocaciones y consultas de inspección. Las cuatro claves técnicas son BIGINT explícitas sin IDENTITY ni secuencias; se mantienen las dos columnas calculadas. Se verificó localmente el contrato con READY; el DDL no se ha ejecutado y no se han cargado datos desde esta etapa.

La [prueba segura de conexión a Supabase PostgreSQL](documentation/12_conexion_supabase.md) usa psycopg, SSL y las variables SUPABASE_DB_* del .env local. Solo consulta identidad, versión y existencia de las cinco tablas dwh; no modifica SQL Server ni implementa cargas READY → DWH.

La [carga controlada READY → DWH](documentation/13_carga_dwh_supabase.md) incorpora prevalidación, dry-run predeterminado, transacción única y comparación idempotente sin borrar ni sobrescribir datos. La documentación conserva la evidencia de su dry-run inicial; el estado actual informado del proyecto confirma las cinco tablas cargadas y conciliadas.

El [backend inicial FastAPI](documentation/14_backend_fastapi.md) ofrece GET /api/v1/health, Swagger y CORS local configurable, con dependencias y pruebas separadas. Iniciar desde la raíz con `.\.venv\Scripts\python.exe -m backend` y abrir http://127.0.0.1:8000/docs. La API todavía no conecta PostgreSQL ni expone endpoints de negocio.

La [conexion lectora del backend al DWH](documentation/15_conexion_backend_dwh.md) incorpora psycopg y verificacion de visibilidad RLS. Los scripts de rol y la propuesta de politicas quedan para revisi?n y autorizacion manual; no se ejecutan al iniciar FastAPI.

Los [primeros endpoints analíticos](documentation/16_endpoints_analiticos.md) ofrecen KPI, ventas mensuales y rankings de productos/clientes mediante SELECT del rol lector. Los importes JSON se conservan como cadenas decimales; Swagger permite probar las cuatro rutas sin modificar el DWH.

El [dashboard React + Vite + ECharts](documentation/17_dashboard_react.md) consume los cuatro endpoints analíticos del backend y muestra KPI, ventas mensuales y rankings, con importes exactos, errores y reintentos por sección. Desde la raíz: `npm.cmd --prefix frontend ci` y `npm.cmd --prefix frontend run dev`, con FastAPI iniciado en otra terminal. Abrir http://127.0.0.1:5173.

El [módulo experimental de Machine Learning](documentation/18_machine_learning.md) compara ingenuo, promedio móvil y Ridge con validación temporal y lectura exclusiva del rol del backend. Guarda modelos JSON y resultados en artifacts/ ignorado por Git. El promedio móvil de tres meses ganó por MAE de selección; los pronósticos históricos de junio–agosto 2016 y sus bandas son experimentales, sin integración todavía con FastAPI o React.

La [integración de predicciones históricas](documentation/19_integracion_predicciones.md) añade GET /api/v1/predicciones/ventas y una sección React/ECharts con métricas, tres estimaciones y bandas descriptivas. FastAPI solo lee un resumen JSON validado mediante BACKEND_FORECAST_PATH; no carga modelos ni entrena en HTTP. La interfaz advierte que el cierre de mayo de 2016 fue declarado, no auditado.

El [asistente de análisis de negocio](documentation/20_asistente_ia.md) añade POST /api/v1/asistente/consultar y la sección Asistente IA. Funciona gratis con reglas locales explícitas, usando únicamente consultas autorizadas y el resumen ML validado. El proveedor Ollama es opcional, restringido a loopback y planes de hechos validados; no se hicieron llamadas LLM reales ni se habilitaron servicios de pago.

La [integración local de Ollama/Qwen3](documentation/21_integracion_ollama.md) conecta el proveedor existente a qwen3:1.7b, reconoce variantes en español, oculta el razonamiento y muestra el proveedor/modelo efectivos. Se validaron los cinco temas con Ollama local real; reglas permanece como alternativa. Activar con ASSISTANT_PROVIDER=ollama y reiniciar FastAPI según los comandos de Windows documentados.

El [orquestador ETL manual](documentation/22_orquestador_etl.md) encadena extracción completa, validación, READY y simulación DWH con rutas aisladas por ejecución, parada ante rechazos y bloqueo de concurrencia. Ejecutar desde la raíz: `.\.venv\Scripts\python.exe etl/ejecutar_pipeline.py --modo completo --dry-run`. No permite --execute ni escribe en Supabase.

### Seguridad: autenticación Supabase Auth, Fase 1

FastAPI valida sesiones ES256 con JWKS. Health es público; los endpoints de negocio
responden 401 sin sesión y 403 con sesión válida hasta implementar permisos.
El dashboard no tiene login todavía y recibirá 401.
[Configuración, decisiones y pruebas](documentation/23_autenticacion_supabase_fase1.md).

### Seguridad: RBAC y hardening, Fase 2

FastAPI aplica permisos ADMIN/ANALYST/VIEWER con fuente privada de roles y denegación
por defecto. VIEWER no puede consultar clientes, predicciones ni asistente. Se añaden
límites de cuerpo HTTP, frecuencia del asistente y errores/cabeceras seguros.
Los SQL privados están preparados **solo para revisión, sin ejecución remota**.
Hasta instalarlos con aprobación, la fuente de roles no estará disponible (503 con
sesión válida y política declarada). React sigue sin login (401).
[Arquitectura, SQL y pruebas](documentation/24_autorizacion_rbac.md).

La consulta RBAC usa únicamente el sub verificado como parámetro SQL, sin identidad
basada en variables PostgreSQL. La política privada autoriza al lector de servicio a leer
todas las asignaciones; no ofrece aislamiento de usuarios web dentro de PostgreSQL.

### Seguridad: login React y sesión efectiva, Fase 3

React incorpora login/logout con Supabase Auth y envía Bearer a FastAPI. El endpoint
`GET /api/v1/auth/me` confirma el rol y permisos antes de mostrar datos. El usuario confirmó
la instalación remota de roles y ADMIN; esta fase no ejecuta SQL. VIEWER no consulta
clientes, ML ni asistente. Configurar la Publishable key pública en frontend/.env.local;
no usar claves privilegiadas. [Instalación, pruebas y limitaciones](documentation/25_login_react_supabase.md).

### Fase 4: auditoría y estabilidad

Se cierran extensiones de rutas que omiten RBAC, se refuerzan claims/headers y se corrigen
carreras de sesión y validación de URLs antes del build. `BACKEND_DOCS_ENABLED=false`
permite desactivar Swagger/OpenAPI en producción. Resultado: 358 pruebas backend y 91
frontend, TypeScript/build correctos. No hubo cambios remotos ni despliegue.
[Hallazgos, límites y recomendaciones Docker/Vercel](documentation/26_auditoria_seguridad_estabilidad.md).

### Backend Docker para entrega

Imagen Linux no root del backend, sin ETL, modelos ni secretos; un worker, healthcheck,
filesystem read-only y límites de recursos. Construida y probada en 127.0.0.1:8001 sin
interrumpir el backend 8000. [Comandos, configuración y resultados](documentation/27_backend_docker.md).
