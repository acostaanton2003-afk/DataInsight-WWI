# Backend inicial con FastAPI

## Estado y alcance

Se implementa únicamente la estructura inicial del backend y **GET /api/v1/health**. No existen endpoints de ventas, clientes, productos o KPI; no se construyó frontend y la API no abre conexiones a bases de datos. No se modificaron scripts ETL, DDL, usuarios, permisos ni datos del DWH.

El contexto actual informado del proyecto es un DWH cargado y conciliado con dim_fecha (1249), dim_cliente (664), dim_producto (228), fact_ventas (228265) y fact_pedidos (73595). Este backend no volvió a consultar esos conteos: health no es una prueba de disponibilidad de Supabase ni de los datos.

Versión inicial de la API: **0.1.0**, definida en `backend/__init__.py`. Se utiliza la misma versión en OpenAPI y en la respuesta health.

## Estructura

```text
backend/
  __init__.py                  # versión del paquete/API
  __main__.py                  # python -m backend
  requirements.txt             # dependencias de ejecución
  requirements-dev.txt         # ejecución + pytest/TestClient
  app/
    __init__.py
    main.py                    # app ASGI y fábrica create_app
    config.py                  # configuración aislada del ETL
    routers/
      __init__.py
      health.py                # router /api/v1/health y modelo de respuesta
  tests/
    conftest.py
    test_health.py
    test_config.py
```

`create_app(settings)` permite construir una aplicación con configuración explícita para las pruebas. El objeto ASGI público es `backend.app.main:app`. No hay pools, conectores, tareas de startup de datos ni dependencias de FastAPI que consulten Supabase.

## Instalación en Windows PowerShell

Ejecutar desde la raíz del repositorio con el entorno `.venv` existente (probado con Python 3.13):

```powershell
# Instala ejecución y herramientas de prueba del backend.
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements-dev.txt

# Pruebas nuevas, sin Supabase ni credenciales reales.
.\.venv\Scripts\python.exe -m pytest .\backend\tests -q

# Opcional: regresión de las pruebas existentes del proyecto.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Para instalar solo las dependencias de ejecución:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
```

No es necesario activar el entorno ni cambiar ExecutionPolicy. Las dependencias del backend permanecen separadas de `etl/requirements.txt`:

- Ejecución: FastAPI, Uvicorn y python-dotenv.
- Desarrollo: pytest y httpx2 para TestClient de la versión actual de Starlette.

Se probaron FastAPI 0.163.1 y Uvicorn 0.54.0. Los rangos del archivo conservan esas familias; no se instala psycopg/pyodbc como dependencia del backend. La documentación actual de Starlette recomienda httpx2 y mantiene httpx como opción deprecada; se usa httpx2 para evitar ese aviso. [TestClient de Starlette](https://starlette.dev/testclient/), [pruebas de FastAPI](https://fastapi.tiangolo.com/tutorial/testing/).

## Inicio y Swagger

En una terminal desde la raíz:

```powershell
$env:BACKEND_HOST = '127.0.0.1'
$env:BACKEND_PORT = '8000'
.\.venv\Scripts\python.exe -m backend
```

Este punto de entrada respeta BACKEND_HOST/BACKEND_PORT de la configuración. Mantener 127.0.0.1 para desarrollo local. Se detiene con **Ctrl+C**.

Para desarrollo con recarga automática, como alternativa:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

En este segundo comando, host/port son los argumentos explícitos de Uvicorn; no se deducen automáticamente de los campos Settings. CORS y la configuración de la aplicación sí se siguen leyendo al importar la app.

Con el servidor iniciado, abrir en el navegador:

- **Swagger:** http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json
- Health: http://127.0.0.1:8000/api/v1/health

En Swagger, desplegar GET /api/v1/health → Try it out → Execute. También se puede probar desde otra terminal:

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/api/v1/health'
```

Respuesta HTTP 200:

```json
{"status":"ok","name":"DataInsight WWI","version":"0.1.0"}
```

Si aparece un error de puerto ocupado, no detener procesos ajenos: elegir por ejemplo BACKEND_PORT=8001 con `python -m backend`, o cambiar --port en Uvicorn, y ajustar la URL del navegador. Un error de módulo suele indicar que se ejecutó desde otra carpeta o con otro Python: volver a la raíz y usar `.venv\Scripts\python.exe`.

## Configuración y CORS

La aplicación puede iniciar **sin .env y sin credenciales**. Si existe, se lee el .env de la raíz con dotenv_values, sin interpolación y sin modificar os.environ. Precedencia para las variables consumidas: **entorno del proceso > archivo .env > valores predeterminados**. Esto difiere de la prueba ETL de Supabase, que usa directamente su archivo; no se modifica ese comportamiento anterior.

Se reutilizan los nombres existentes:

| Variable | Predeterminado / uso |
| --- | --- |
| BACKEND_HOST | 127.0.0.1; utilizado por python -m backend. |
| BACKEND_PORT | 8000; entero entre 1 y 65535. |
| CORS_ORIGINS | http://localhost:5173,http://127.0.0.1:5173; lista separada por comas. Vacío deshabilita acceso entre orígenes. |

Ejemplo en la terminal, sin escribir ni sobrescribir .env:

```powershell
$env:CORS_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173'
```

`.env.example` documenta esas opciones. No copiarlo encima de un .env existente ni borrar variables SQLSERVER_* o SUPABASE_DB_*; no es necesario editarlas para arrancar health. .env y /data/ continúan ignorados por Git. No se imprimen la configuración privada, contraseñas ni el contenido del archivo.

CORS admite únicamente orígenes HTTP(S) explícitos, sin comodines, credenciales incrustadas, rutas, query, fragmentos o caracteres de control. Se normaliza la barra raíz final y se eliminan duplicados. localhost y 127.0.0.1 son orígenes distintos; esquema, host y puerto deben corresponder al navegador.

Se fija **allow_credentials=False**, sin una opción que lo active accidentalmente. Solo se permite GET y los headers Accept/Content-Type; el middleware gestiona OPTIONS de preflight. Los orígenes no permitidos no reciben Access-Control-Allow-Origin y sus preflight son rechazados. **CORS no es autenticación:** una petición directa con curl/PowerShell puede obtener health aunque no sea un origen de navegador permitido. No se implementó autenticación en esta etapa. [CORS en FastAPI](https://fastapi.tiangolo.com/tutorial/cors/).

## Reserva para PostgreSQL de solo lectura

La capa de configuración contiene `ReadOnlyDatabaseSettings`, sin driver ni lógica de conexión. Utiliza únicamente variables **BACKEND_DB_*** separadas y vacías en el ejemplo:

```dotenv
BACKEND_DB_HOST=
BACKEND_DB_PORT=
BACKEND_DB_NAME=
BACKEND_DB_USER=
BACKEND_DB_PASSWORD=
BACKEND_DB_SSLMODE=
```

No se reutilizan SUPABASE_DB_*, POSTGRES_* ni el administrador del ETL como fallback. Es seguro conservar esas otras variables en el mismo archivo: el backend las ignora.

La configuración futura tiene puerto predeterminado 5432, SSL require (también admite verify-ca/verify-full) y read_only=True no configurable. Host, base, usuario y contraseña pueden permanecer vacíos: health no los requiere. Se rechazan postgres, su formato de pooler postgres.<proyecto> y otros nombres administrativos conocidos en BACKEND_DB_USER. Los campos de base de datos se excluyen de repr para evitar exposición accidental.

**read_only=True es solo un contrato de configuración futuro, no una certificación de permisos del servidor.** Antes de añadir un conector habrá que disponer de un rol dedicado con permisos realmente limitados, comprobarlos y configurar sus transacciones de lectura. Un nombre de usuario distinto de postgres tampoco prueba por sí solo que sea un rol lector. No se crea ahora ese usuario, no se alteran permisos y no se prueba ninguna conexión. Si se desea conectar la API más adelante, requerirá otra etapa autorizada.

Las configuraciones CORS/puertos/SSL inválidas fallan con mensajes genéricos, sin devolver el valor recibido. Un BACKEND_DB_USER administrativo también impide el arranque; dejar estas variables vacías mientras no exista el rol lector adecuado.

## Resultados de verificación

- **38 pruebas pytest del backend aprobadas**, sin avisos de deprecación. Cubren JSON/versionado de health, Swagger/OpenAPI, ausencia de endpoints de negocio, métodos no permitidos, CORS simple/preflight/credenciales, ausencia de necesidad de red, precedencia de configuración, aislamiento del ETL, secretos no expuestos, rol administrativo rechazado, puertos y SSL.
- **98 pruebas existentes aprobadas** mediante unittest, sin conexión real a servicios.
- Uvicorn se inició de verdad en un puerto temporal libre de **127.0.0.1**. Se verificaron health, /docs y /openapi.json con HTTP 200; el proceso se cerró al terminar. No se dejó un servidor de prueba ejecutándose ni se ocupó el puerto 8000 de otro proceso.
- Los scripts ETL y la carpeta database no tienen cambios en esta etapa. No se consultó ni alteró el DWH; sus conteos iniciales son contexto suministrado por el proyecto.

La prueba de health verifica que la API responde, no la conectividad de datos. Los siguientes pasos de datos, endpoints de negocio, autenticación o frontend no están implementados.
