# Fase 2: RBAC y hardening del backend

## Estado y alcance

Implementación local. Los SQL de esta fase NO han sido ejecutados en Supabase.
No se crean usuarios ni asignaciones ADMIN automáticamente. No cambia React, ETL,
ML, el DWH ni sus políticas RLS. No hay administración de roles por HTTP.
La Fase 2 sustituye la denegación temporal de Fase 1 por una consulta de roles
con denegación por defecto. Hasta instalar el esquema con aprobación, una sesión
válida con política declarada recibirá 503 al no estar disponible la fuente de roles.
La ausencia de token sigue devolviendo 401. Sin asignación: 403 después de instalar.
React todavía no tiene login y seguirá recibiendo 401.

## Flujo y separación de responsabilidades

1. La dependencia GLOBAL de FastAPI excluye únicamente el endpoint real de health.
2. Se verifica JWT ES256 y se obtiene el sub de usuario; HS256 sigue rechazado.
3. Sin permiso declarado por el endpoint: 403, antes de consultar roles.
4. RoleRepository consulta exclusivamente el UUID verificado, con parámetros SQL.
5. Sin asignación, deshabilitado, rol desconocido o UUID diferente: 403.
6. Fallo de configuración/conexión/fuente de roles: 503 genérico, sin fallback.
7. Se comprueba el permiso, y para IA el límite de solicitudes, antes del servicio.

`permissions.py`: matriz y decorador. `role_repository.py`: lectura de roles.
`auth_dependencies.py`: decisiones HTTP. `security_http.py`: límites ASGI/cabeceras.
`rate_limit.py`: contador pequeño por usuario. Las conexiones PostgreSQL existentes
se reutilizan; no hay credenciales nuevas ni conexión al importar/iniciar health.
La identidad y los permisos no se obtienen de React, cabeceras personalizadas,
parámetros o metadata JWT. Incluso app_metadata no es autoridad en este diseño.

| Endpoint | VIEWER | ANALYST | ADMIN |
|---|---|---|---|
| GET /api/v1/health | Público | Público | Público |
| GET /api/v1/kpis | Sí | Sí | Sí |
| GET /api/v1/ventas/por-mes | Sí | Sí | Sí |
| GET /api/v1/productos/top | Sí | Sí | Sí |
| GET /api/v1/clientes/top | No | Sí | Sí |
| GET /api/v1/predicciones/ventas | No | Sí | Sí |
| POST /api/v1/asistente/consultar | No | Sí | Sí |

ROLES_MANAGE queda reservado a ADMIN; no existe endpoint administrativo ni
permisos de escritura para implementarlo. Todos los temas del asistente se bloquean
al VIEWER, evitando acceso indirecto a clientes o predicciones. Los servicios actuales
son agregados globales: no hay recursos individuales por usuario ni multitenencia.
Un futuro recurso individual necesitará autorización de propiedad adicional.

## Nuevas rutas: denegación predeterminada

Registrar rutas con FastAPI/APIRouter conserva la dependencia global, incluso con
`dependencies=[]`. Declarar el permiso debajo del decorador `@router.get/post`:

```python
@router.get('/nuevo')
@requires_permission(Permission.GENERAL_READ)
def nuevo():
    ...
```

Sin ese permiso: 403 con sesión válida, 401 anónima. No añadir rutas públicas nuevas
ni montar subaplicaciones/Starlette routes fuera del mecanismo de dependencias sin
una revisión de seguridad independiente. Swagger/OpenAPI automáticos siguen públicos
como en Fase 1; no contienen datos analíticos. La prueba de inventario controla las
rutas productivas y sus políticas. ETL, mantenimiento y entrenamiento siguen como CLI.

## SQL exclusivamente local y aprobación pendiente

Revisar en orden, sin ejecutar automáticamente:

1. `database/security/01_roles_backend.sql`: instalación inicial PG17.
2. `database/security/02_verificar_roles_backend.sql`: catálogos y sondeo read-only.
3. `database/security/03_revertir_acceso_roles.sql`: reversión de acceso conservando datos.

Los tres requieren aprobación explícita posterior antes de cualquier ejecución remota.
La instalación es transaccional y aborta si app_security ya existe: no es una migración
repetible ni utiliza IF NOT EXISTS para ocultar incompatibilidades. Revisar permisos del
operador, objetos Supabase y defaults globales. Un REVOKE de defaults por esquema NO
neutraliza un GRANT global; el script aborta si detecta defaults incompatibles para los
roles protegidos, sin alterar esos defaults globales.

La tabla privada app_security.user_roles contiene únicamente user_id, role y enabled:
PK/FK auth.users(id), CHECK de roles, enabled=false por defecto, sin rol predeterminado.
ON DELETE RESTRICT impide borrar un usuario Auth referenciado hasta revisar/eliminar
su asignación por un operador autorizado. Este procedimiento administrativo queda
pendiente; no hay usuarios creados ni asignaciones de prueba en los SQL.

El lector recibe USAGE del esquema y SELECT A NIVEL DE COLUMNA solo sobre los tres
campos, sin SELECT de tabla que se extienda a columnas futuras. No recibe CREATE,
INSERT/UPDATE/DELETE/TRUNCATE ni permisos administrativos. Las tablas futuras no
reciben automáticamente acceso del lector. Los defaults se limitan al esquema y al
rol creador; otros creadores requieren revisión. No se crean funciones: futuras funciones
necesitarán revisar explícitamente EXECUTE a PUBLIC, incluido el default global.

RLS se habilita y fuerza SOLO en la tabla nueva. La política es:

```sql
FOR SELECT TO wwi_backend_reader
USING (current_user = 'wwi_backend_reader')
```

Es una política de **cuenta de servicio**, no de usuario web: permite al lector consultar
TODAS las asignaciones usando las tres columnas autorizadas. FastAPI valida ES256 y
aplica `WHERE user_id = %s` con el sub verificado; comprueba además que la fila devuelta
pertenezca a ese sub. No se ejecuta set_config ni se lee un parámetro de sesión como
prueba de identidad. Cambiar parámetros PostgreSQL no altera esta política.

La consulta parametrizada evita que el UUID se interprete como SQL, pero no restringe
las consultas que un poseedor de credenciales lectoras podría ejecutar directamente.
Una fuga de esas credenciales o una vulnerabilidad de ejecución SQL arbitraria permitiría
leer todas las asignaciones (UUID, rol y estado). No permitiría por estos grants escribirlas,
otorgarse ADMIN en la tabla ni firmar una sesión Auth. No se afirma aislamiento por usuario
en PostgreSQL. La autoridad para el RBAC web continúa siendo el servidor con JWT verificado.
No se cambian políticas ni identidades de conexión para las tablas analíticas.

El backend abre conexiones psycopg breves, no un pool Python. La configuración local
revisada identifica Supavisor compartido en modo sesión; no se probó conectividad remota.
El lookup ya no depende de estado persistente ni de configuración entre consultas. Mantiene
autocommit=false, transacciones de lectura y prepare_threshold=None, compatible por diseño
con conexión directa y pooling de sesión/transacción. La identidad PostgreSQL efectiva debe
seguir siendo exactamente wwi_backend_reader; esto se comprueba en read_connection.
La comprobación con el despliegue real queda pendiente de aprobación.

Si la confidencialidad exige impedir lectura general desde esa cuenta, se necesita otro
límite de confianza: una identidad PostgreSQL dedicada a autorización sin grants de roles
para el lector analítico reduce el alcance de una fuga, pero sigue sin aislar usuarios web.
Una función con consulta fija y salida mínima puede reducir superficie si se revoca SELECT
directo y se revisan owner, search_path y EXECUTE. **Aceptar un UUID como argumento no
prueba identidad**: una función así tampoco impide consultar UUID ajenos por sí sola.
Para garantizarlo se requeriría un canal confiable que verifique la sesión antes de la
consulta. No se implementan funciones SECURITY DEFINER, JWT en GUC ni verificadores
criptográficos caseros. Cualquier arquitectura alternativa necesita revisión separada.

RLS y los GRANT son capas diferentes. No basta con habilitar RLS. Confirmar manualmente
que app_security NO está en los esquemas expuestos de Supabase Data API; el script no
lo añade y el setting SQL pgrst.db_schemas puede no reflejar la configuración efectiva.
Anon/authenticated no reciben USAGE ni acceso de tabla/columna. La consulta directa
psycopg no depende de que el esquema esté expuesto por Data API.

El sondeo de verificación no necesita ningún UUID de usuario ni modifica parámetros de
identidad: comprueba RLS activo, acceso a las tres columnas y un conteo agregado de filas
visibles. Con esta política el lector debe ver todas las asignaciones. Un conteo cero sobre
una tabla vacía no demuestra que funcione una política permisiva: la prueba positiva requiere
asignaciones futuras aprobadas. El SQL valida grants y perfil del lector con excepciones
si no cumplen; muestra la política para revisar su definición y no consulta datos auth.users.

Con FORCE RLS, un operador normal propietario sin una política de escritura tampoco
puede asignar roles: la operación administrativa futura debe revisarse con el operador
Supabase autorizado, sin otorgar BYPASSRLS ni privilegios de escritura al backend.

La reversión revoca grants de lectura/USAGE del backend; mantiene filas y RLS. Produce
503 cerrado para consultas de roles. No borra tablas, no toca dwh y no permite volver a
instalar 01 sin revisión. Restaurar permisos requiere otro cambio explícitamente aprobado.

## Hardening implementado

- Cuerpo HTTP máximo: 16 KiB, contando bytes reales, incluso chunked o Content-Length
  falso. Validación temprana de Content-Length y timeout total de recepción de 10 s.
  413 por tamaño, 408 por recepción lenta, 400 por longitud inválida. Se bufferizan como
  máximo 16 KiB antes de JSON; no se almacena el cuerpo excesivo.
- Asistente: 6 solicitudes por usuario en ventana fija de 60 s, antes de servicios,
  con 429/Retry-After. Hasta 2048 usuarios activos en memoria; al saturarse, deniega
  usuarios nuevos hasta expirar entradas. No confía en X-Forwarded-For.
- Sin caché de roles: deshabilitar o degradar tiene efecto en la siguiente consulta;
  una solicitud ya autorizada puede terminar. El límite requiere reiniciar proceso para
  reiniciar contadores; no es un límite distribuido y puede multiplicarse con workers.
- Cache-Control:no-store, nosniff, Referrer-Policy:no-referrer y X-Frame-Options:DENY.
- Validación 422 genérica para no reflejar entradas sensibles. Errores inesperados 500
  genéricos antes de que el servidor reciba la excepción original. Una respuesta que ya
  comenzó no puede reemplazarse; no se escriben detalles del error en el stream.
- Eventos de autenticación/autorización con motivo fijo y permiso, sin UUID, tokens,
  preguntas, headers, queries ni excepciones originales. La configuración del colector
  y de access logs de infraestructura requiere revisión separada.
- Se conservan consultas parametrizadas, modelos Pydantic y límites del proveedor.
  No se ejecuta SQL, código ni herramientas desde el contenido del asistente.

## Pendientes de despliegue

HTTPS/HSTS en el proxy cuando exista dominio TLS, límites de conexiones/frecuencia para
rutas públicas y fuente de roles, y rate limiting compartido si hay varios procesos.
La aplicación no sustituye protección DoS del proxy. No publicar Uvicorn debug.
CSP debe diseñarse en el servidor del frontend React con scripts/connect-src explícitos
para la API/Auth. No aplicar una CSP indiscriminada que rompa Swagger. Login React y
sesiones continúan fuera de alcance. La verificación JWT no consulta revocación remota
instantánea; enabled=false en la fuente de roles bloquea la siguiente solicitud.

Referencias: [OWASP autorización](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
[Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security).
Se aplican mínimo privilegio, validación por petición y fail-closed; no se afirma una
certificación ASVS ni ausencia total de vulnerabilidades. Proponer auditoría de dependencias
con pip-audit y npm audit en una revisión separada, sin instalar/actualizar paquetes aquí.

## PowerShell y pruebas locales

Desde la raíz, sin ejecutar SQL ni ETL:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m backend
```

Health sigue en http://127.0.0.1:8000/api/v1/health. No crear usuarios ni compartir tokens
para probar esta fase: los tests generan claves/identidades sintéticas y repositorios falsos.
Se conservan las 240 pruebas anteriores; sus fixtures se adaptaron al nuevo repositorio.
Las pruebas funcionales siguen omitiendo autorización solo mediante override de test;
las de seguridad no. Las pruebas SQL son estáticas: no prueban sintaxis ni permisos en
PostgreSQL real. La ejecución/verificación remota permanece pendiente de aprobación.

### Resultado local previo a la simplificación

Suite completa: **329 pruebas aprobadas**, incluyendo las 240 anteriores y 89 nuevas.
Se detectaron y corrigieron durante el desarrollo dos expectativas de tests (construcción
de dependencia antes de validar un body y rutas diferidas de FastAPI) y una comprobación
SQL estática que confundía nombres de privilegios con sentencias. No quedan fallos en
la ejecución completa. Ningún SQL se ejecutó, ni se comprobó remotamente su sintaxis.

## Orden de ejecución futura (NO autorizado todavía)

1. Revisar y aprobar la revisión exacta de los tres SQL. Confirmar en Supabase Data API
   que app_security no esté en Exposed schemas; un setting de SQL Editor no basta.
2. Identificar al operador autorizado del SQL Editor, su capacidad de crear esquema,
   referenciar auth.users y otorgar los grants. No usar el lector para instalar.
3. Ejecutar 01 completo, únicamente con aprobación remota explícita. Si aborta por esquema
   existente o defaults globales, detenerse: no omitir preflight ni revocar defaults globales.
4. Ejecutar 02 y revisar catálogo, columnas, política y grants. Esperados: RLS/force activos;
   USAGE y SELECT de las tres columnas solo para el lector; SELECT de tabla, CREATE y
   permisos de escritura falsos. Anon/authenticated sin acceso. La política del lector no
   filtra por usuario web. El conteo visible equivale a todas las asignaciones existentes.
5. Tras asignaciones aprobadas, hacer pruebas positivas/negativas de FastAPI con sesiones
   legítimas. No publicar tokens ni copiar secretos a scripts o capturas.
6. Si hace falta revertir, solicitar aprobación para 03; conserva filas y RLS y verifica que
   no queden privilegios efectivos del lector. No ejecutarlo junto con la instalación.

### Primer ADMIN, procedimiento manual futuro

No se crea ni asigna automáticamente. Requiere autorización posterior separada:

- Crear/invitar al usuario desde Supabase Auth, verificar su titularidad y su UUID en el
  panel confiable. No aceptar un UUID enviado por un solicitante como prueba de titularidad.
- Revisar en SQL Editor los atributos del operador y sus privilegios sobre la tabla.
  FORCE RLS también afecta al propietario normal. Si el operador no puede escribir con
  sus privilegios administrativos existentes, detenerse: no desactivar RLS ni dar BYPASSRLS
  al backend para resolverlo.
- En una transacción administrativa controlada, bloquear user_roles, comprobar que no hay
  ya un ADMIN habilitado y que el UUID no tiene asignación. Insertar exactamente una fila
  con el UUID verificado, role=ADMIN, enabled=true; exigir una fila afectada y confirmar.
  No usar un upsert que sobrescriba una asignación existente ni registrar el UUID real en Git.
- No modificar directamente auth.users. La FK valida que el usuario exista; no confirma su
  titularidad. Revisar MFA para ese usuario y probar la API después, sin interfaz administrativa.

## Resultado de la simplificación

Se elimina el uso de parámetros de sesión para identidad. Resultado actualizado: **331
pruebas aprobadas, 0 fallidas**, incluyendo las 329 anteriores y dos comprobaciones nuevas.
Comando: `.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider`.
Las verificaciones SQL siguen siendo estáticas y no sustituyen una ejecución PostgreSQL
expresamente aprobada.
