# DataInsight-WWI

Primer examen de Tecnologia Emergente.

## Descripción

**DataInsight WWI — Plataforma Integral de Ingeniería de Datos y Analítica Inteligente** es un proyecto universitario que integra datos de WideWorldImporters, los transforma con Python y los organiza en un Data Warehouse en Supabase PostgreSQL. La plataforma ofrecerá consultas mediante una API, dashboards interactivos, modelos de Machine Learning, funciones de IA generativa y alertas automatizadas.

La etapa ETL incluye la conexión de Python a SQL Server y una primera muestra de extracción a CSV RAW. Las transformaciones y cargas siguen pendientes.

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

Los nombres de las variables son una propuesta inicial y se conectarán al código durante la implementación de cada componente.

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
