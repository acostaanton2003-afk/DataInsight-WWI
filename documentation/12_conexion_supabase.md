# Prueba segura de conexión Python a Supabase PostgreSQL 17

## Alcance y archivos

`etl/probar_conexion_supabase.py` realiza una única prueba de conexión con psycopg 3 y dos consultas SELECT. No crea ni modifica tablas, permisos o esquemas; no carga datos ni conecta READY con el DWH.

Dependencias añadidas en `etl/requirements.txt`: `psycopg[binary]` (distribución adecuada para Windows sin compilar libpq) y `python-dotenv`. Se conserva pyodbc y toda la configuración de SQL Server. Referencias: [instalación de Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html), [python-dotenv](https://bbc2.github.io/python-dotenv/).

## Configuración local, sin sobrescribir SQL Server

El archivo leído es siempre **.env de la raíz del repositorio**, resuelto respecto a la ubicación del script, no al directorio actual. El archivo debe contener estas seis variables; `.env.example` las incluye vacías:

```dotenv
SUPABASE_DB_HOST=
SUPABASE_DB_PORT=
SUPABASE_DB_NAME=
SUPABASE_DB_USER=
SUPABASE_DB_PASSWORD=
SUPABASE_DB_SSLMODE=
```

Obtener los valores reales desde **Connect** en el panel del proyecto y editarlos únicamente en el archivo local. No copiar la URL completa en HOST. Host, puerto, usuario y contraseña deben corresponder al mismo endpoint/modo y proyecto. NAME es el nombre de la base de datos, habitualmente postgres; la contraseña es la contraseña de base de datos, no una clave anon, publishable o service_role.

Completar o conservar estas seis entradas sin borrar ni reemplazar variables SQLSERVER_* u otras existentes. Los campos heredados POSTGRES_* y las claves de Data API no se utilizan en esta prueba.

El script utiliza `dotenv_values(..., interpolate=False)` y **no modifica os.environ**. La configuración de esta prueba sale del archivo, no de variables SUPABASE_DB_* previamente exportadas en PowerShell. No hay interpolación de `${...}` en contraseñas. Se conserva el valor de la contraseña sin aplicar strip ni codificación URL. Seguir la sintaxis de comillas/escapes de dotenv cuando la contraseña contenga espacios, #, comillas o barras; no pegarla en comandos, capturas o tickets.

Los seis campos son obligatorios; el puerto debe estar entre 1 y 65535. SSLMODE solo admite **require**, **verify-ca** o **verify-full**. Se rechazan disable, allow y prefer, para impedir conexión sin cifrado. require cifra, pero no equivale por sí solo a verificar el nombre y la cadena del certificado. Para verify-ca/verify-full, disponer de la CA correspondiente en la configuración estándar de libpq; no desactivar SSL para corregir un error de certificado. [Conexión y SSL en Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres).

.env y /data/ continúan excluidos en .gitignore. No se leyó ni mostró el contenido de .env en la salida de herramientas; la prueba únicamente lo procesa internamente. No se añadieron credenciales reales al código ni al ejemplo.

## PowerShell desde la raíz

Usar el entorno virtual existente de Windows. No es necesario activarlo:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\etl\requirements.txt

# Solo crea un ejemplo local si NO existe .env. Nunca lo sobrescribe.
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}

# Edición manual local: no copiar ni imprimir secretos en la terminal.
notepad .env

# Pruebas unitarias: solo datos y controladores ficticios.
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas.' }

# Conexión real: no ejecuta DDL ni cargas.
.\.venv\Scripts\python.exe .\etl\probar_conexion_supabase.py
$LASTEXITCODE
```

Para repetir solo la prueba:

```powershell
.\.venv\Scripts\python.exe .\etl\probar_conexion_supabase.py
```

No usar Get-Content .env, imprimir la configuración ni construir una URL con la contraseña. El script no necesita ejecutar la prueba de SQL Server y no altera su mecanismo de conexión.

## Consultas y seguridad

La conexión pasa host, port, dbname, user, password y sslmode como **argumentos separados**, sin concatenar URL ni DSN. Usa connect_timeout=10 segundos, prepare_threshold=None y autocommit=False. La conexión cierra automáticamente sus recursos al terminar, incluso ante errores.

Antes de la primera consulta se configura `connection.read_only=True`, de modo que las transacciones iniciadas por Psycopg son de lectura. Se ejecutan exclusivamente:

1. `SELECT CURRENT_USER, CURRENT_DATABASE(), VERSION()`.
2. SELECT sobre pg_catalog.pg_class/pg_namespace para contar las cinco tablas base de dwh: dim_fecha, dim_cliente, dim_producto, fact_ventas y fact_pedidos. Esquema y lista de nombres se pasan como parámetros.

No se ejecutan SELECT sobre los datos de los hechos, ni INSERT, UPDATE, DDL o concesiones. Los comandos de transacción que administra el controlador no alteran datos. No se configura estado de sesión persistente que dependa de conservar el backend de un pooler. [Estado de lectura y conexión Psycopg](https://www.psycopg.org/psycopg3/docs/api/connections.html).

VERSION() se comprueba internamente para exigir PostgreSQL 17, pero **no se imprime**. La salida siempre tiene solo cuatro líneas: estado, CURRENT_USER, CURRENT_DATABASE y cantidad de tablas. CURRENT_USER del servidor puede diferir del usuario de enrutamiento del pooler.

No se registran host, contraseña, conexión completa, objeto de configuración, texto de excepción del controlador, traceback ni contenido de .env. Se suprimen avisos del parser durante la lectura para no añadir líneas al resultado; los errores se traducen a estados genéricos. Los caracteres de control del usuario/base se neutralizan para impedir líneas adicionales en logs.

Contar tablas no prueba permisos de lectura sobre sus datos, restricciones, RLS o compatibilidad estructural; los catálogos pueden ser visibles aunque no haya acceso a los hechos. Tampoco indica cuántas filas tienen las tablas. Esta prueba no sustituye `04_verificacion_dwh.sql` ni ejecuta ese archivo.

## Estados y códigos de salida

| Estado | Código | Interpretación |
| --- | ---: | --- |
| conexion_correcta | 0 | Conexión y consultas correctas, PostgreSQL 17 y cinco tablas base encontradas. |
| conectado_tablas_incompletas | 2 | Se pudo consultar, pero faltan una o más tablas esperadas; no se crean automáticamente. |
| conectado_version_no_compatible | 2 | Se pudo consultar, pero VERSION no identifica PostgreSQL 17. |
| configuracion_invalida | 1 | .env ausente/inaccesible, campos incompletos, puerto inválido, SSL no permitido o formato inválido. |
| dependencias_incompletas | 1 | Falta psycopg o python-dotenv en el Python ejecutado. |
| conexion_fallida | 1 | No se completó conexión/primera consulta; revisar configuración, red, autenticación o SSL sin volcar excepciones. |
| consulta_fallida | 1 | Falló una consulta posterior o el cierre; no se muestra su error original. |

Cuando no existe resultado de consulta, usuario, base o número aparecen como «no disponible», sin usar valores secretos de configuración como sustitutos.

## Pooler: problemas frecuentes en Windows

Usar los parámetros exactos de Connect; no deducir el host a partir de la región ni mezclar el usuario de conexión directa con el del pooler. La configuración publicada por Supabase distingue:

| Modalidad | Puerto habitual | Usuario habitual | Consideración |
| --- | ---: | --- | --- |
| Directa | 5432 | postgres o rol configurado | Normalmente IPv6; en una red solo IPv4 puede no ser alcanzable sin opción IPv4 del proyecto. |
| Shared pooler, sesión | 5432 | rol seguido del identificador del proyecto | Alternativa para Windows/redes IPv4 y herramientas locales. |
| Shared pooler, transacción | 6543 | rol seguido del identificador del proyecto | No soporta sentencias preparadas en este modo; el script las desactiva. |

Son orientaciones, no valores que el script fuerce. El endpoint dedicado puede tener reglas diferentes; usar siempre el diálogo Connect. [Modos de conexión oficiales](https://supabase.com/docs/guides/database/connecting-to-postgres).

Ante conexion_fallida:

- Verificar que el proyecto esté activo y que host/puerto/usuario pertenezcan al mismo modo. El usuario del shared pooler incorpora el identificador del proyecto; no basta con usar solo postgres.
- En una red solo IPv4, revisar Session pooler en lugar de una conexión directa IPv6. Copiar su host, no inventarlo. Revisar VPN, firewall y acceso saliente al puerto indicado.
- Confirmar contraseña de base de datos y su lectura literal desde .env; no usar claves API ni hacer URL encoding de una contraseña pasada como argumento separado.
- Verificar SSLMODE y certificados. No cambiarlo a disable/prefer.
- El timeout de conexión es 10 segundos por intento gestionado por libpq; DNS o varias direcciones pueden ampliar el tiempo total. No se implementan reintentos en bucle.

Ante errores relacionados con el pooler, el script ya utiliza prepare_threshold=None y una sola transacción de lectura, compatibles con las limitaciones de prepared statements/estado de sesión del modo transacción. No abre un pool adicional ni consultas concurrentes. Si el estado indica tablas incompletas, comprobar manualmente la etapa física; esta prueba no intentará repararla. Para diagnosticar no compartir .env, cadenas de conexión ni trazas originales con credenciales.

## Pruebas y resultado de esta etapa

**80 pruebas locales aprobadas**, incluidas 14 nuevas: configuración obligatoria, no modificación del entorno SQL Server, contraseña literal/no interpolada, puerto y SSL, parámetros separados, timeout, lectura, consultas limitadas, ocultación de errores y fallos al cerrar, tablas incompletas, versión, dependencias, avisos del parser y control de líneas de log. Los tests usan .env ficticio en directorios temporales y un controlador simulado; no necesitan conexión real.

La prueba real se ejecutó una vez, sin imprimir secretos, y devolvió únicamente:

```text
Estado: conexion_correcta
Usuario: postgres
Base de datos: postgres
Tablas encontradas: 5
```

Código de salida 0. No se creó ni modificó ninguna tabla y no se cargaron datos. Este resultado no afirma que el DDL, los permisos o los datos hayan sido conciliados en el servidor.
