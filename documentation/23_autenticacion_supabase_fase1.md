# Fase 1: autenticación Supabase Auth en FastAPI

## Alcance y estado

Se valida la identidad de sesión, pero todavía NO existen permisos de aplicación.
Todos los endpoints analíticos, predicciones y asistente quedan bloqueados por defecto:
401 sin sesión válida y 403 con sesión válida hasta la Fase 2. No se consulta el DWH,
no se lee el artefacto ML ni se llama a Ollama en solicitudes denegadas.
React no se modifica: el dashboard actualmente recibirá 401, de forma intencional.
Health sigue público e independiente de Auth/PostgreSQL. Swagger y OpenAPI siguen públicos.
No existe bypass de desarrollo ni variable para habilitar acceso a datos.

## Configuración pública verificada

En esta implementación se consultaron por HTTPS los metadatos públicos del proyecto:

- URL: `https://xunsksfkuabfpvjxhjbk.supabase.co`.
- Discovery: `https://xunsksfkuabfpvjxhjbk.supabase.co/auth/v1/.well-known/openid-configuration`.
- Issuer publicado: `https://xunsksfkuabfpvjxhjbk.supabase.co/auth/v1`.
- JWKS publicado: `https://xunsksfkuabfpvjxhjbk.supabase.co/auth/v1/.well-known/jwks.json`.
- JWKS observado: clave EC, P-256, ES256, uso de firma.
- Audience aceptada: `authenticated`, definida por Supabase para sesiones de usuario.
  Discovery no publica el audience del access token; no se verificó un token real ni
  se crearon usuarios. Un Custom Access Token Hook que cambie estos claims necesitará revisión.

Fuentes oficiales: [claims](https://supabase.com/docs/guides/auth/jwt-fields),
[JWT/JWKS](https://supabase.com/docs/guides/auth/jwts).
El discovery anuncia varios algoritmos; la aplicación acepta exclusivamente ES256.
Los metadatos se usaron para verificar la configuración, no para ampliar automáticamente
la lista permitida. Solo se admite el dominio oficial de proyecto; un dominio personalizado
requerirá revisión explícita, no una URL enviada por el cliente.

Añadir manualmente en `.env` raíz, conservando las variables existentes:

```dotenv
SUPABASE_AUTH_URL=https://xunsksfkuabfpvjxhjbk.supabase.co
```

No hace falta una clave API ni JWT Secret para verificar firmas públicas. No copiar
SUPABASE_DB_* ni credenciales administrativas. La variable se carga con precedencia
entorno del proceso > .env. Si falta, health funciona y la autenticación con token falla
cerrada con 503; solicitudes sin token siguen devolviendo 401.

## Diseño y decisiones

- `auth_config.py`: URL confiable, issuer/JWKS derivados y audience fija.
- `authentication.py`: firma y claims; identidad mínima con UUID de usuario y sesión.
- `auth_dependencies.py`: Bearer HTTP, errores seguros y denegación temporal.
- `main.py`: protección centralizada de los tres routers de negocio, antes de sus dependencias.
- La conexión PostgreSQL y RLS se conservan sin modificaciones.

Se exige ES256, `typ=JWT`, `kid`, firma válida, issuer exacto, audience exacta,
expiración e issued-at numéricos enteros, exp posterior a iat, y se valida nbf si existe.
No hay tolerancia temporal: mantener el reloj de Windows sincronizado.
Se exigen sub y session_id UUID no nulos, role=authenticated, aal1/aal2 e
is_anonymous=false. `role=authenticated` identifica el tipo de sesión: NO concede
un rol administrador/analista/visualizador. No se confía en user_metadata.

Se rechazan HS256, otros algoritmos, tokens API/servicio y sesiones anónimas.
Los usuarios con access tokens HS256 deben renovar su sesión para obtener ES256;
si no ocurre, será necesaria una nueva autenticación cuando exista login.
No se usa el secreto heredado ni se intenta obtenerlo de JWKS.

Caché JWKS por proceso de 300 segundos, refresco por kid desconocido con separación
mínima de 30 segundos entre intentos y exclusión mutua. Una clave nueva puede requerir
esperar hasta 30 segundos. No se usan claves caducadas ante fallo de red. Las claves
retiradas pueden seguir aceptándose durante la vigencia de la caché; considerar también
la caché del servidor Supabase. Sin comprobación remota de revocación: una sesión cerrada
o usuario deshabilitado no se detecta inmediatamente por la verificación JWT local.
La autorización sigue denegada en esta fase.

Descarga HTTPS sin redirecciones ni proxies del entorno, timeout 5 segundos y respuesta
máxima 64 KiB. Token máximo 16 KiB. No se registran tokens ni excepciones originales.
JWKS/configuración no disponibles: 503; token no aceptable: 401 con WWW-Authenticate.
Estas medidas no sustituyen rate limiting ni un límite HTTP global de cuerpo, pendientes.
CORS permite Authorization únicamente para los orígenes configurados, sin credenciales.

## Windows PowerShell

Desde la raíz, sin ejecutar ETL ni conectar a bases de datos:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m backend
```

En otra terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
curl.exe -i http://127.0.0.1:8000/api/v1/kpis
```

Esperados: health 200; KPI anónimo 401. Swagger: http://127.0.0.1:8000/docs.
No compartir tokens en capturas, comandos guardados ni logs. No hay un usuario real
creado para probar 403: se verifica con claves y tokens sintéticos en las pruebas.

La restricción anterior de ejecución de `.venv` se resolvió ejecutando el intérprete
fuera del sandbox con autorización; no se eliminó ni recreó el entorno.

## Pruebas

Las pruebas de seguridad crean una aplicación sin overrides de autorización, generan
claves EC sintéticas y simulan JWKS. Cubren 401/403, firma, claims, algoritmos, rotación,
caché, CORS y fallos de red, y bloquean conexiones a PostgreSQL, ML y Ollama.
Las pruebas funcionales anteriores usan un override explícito de autorización solo en
su fixture, para conservar sus contratos de servicio. Ese override no existe en producción.
Los resultados de ejecución se registran en la entrega de esta fase.

## Pendientes

Fase 2: roles privados, autorización por permiso y pruebas de la matriz de acceso.
El visualizador no tendrá nombres de clientes ni asistente. No habilitar los endpoints
por el mero hecho de recibir un JWT válido. Login React queda para otra fase.
