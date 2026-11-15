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
