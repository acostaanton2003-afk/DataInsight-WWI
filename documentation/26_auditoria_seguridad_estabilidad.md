# Fase 4: auditoría de seguridad, calidad y estabilidad

Fecha de revisión: 2026-11-15. Alcance: código y pruebas locales, consultas de avisos
públicos npm/OSV. No SQL remoto, cambios de usuarios/RLS/permisos, ETL, entrenamiento,
login real, despliegue, commit ni push. No se imprimieron credenciales ni tokens.
La integración ADMIN remota proviene del estado confirmado por el usuario; no se repitió.
No es pentest completo, auditoría de todo el historial ni certificación OWASP ASVS.

## Hallazgos y correcciones

Las líneas se refieren al código resultante. "Potencial" no significa ataque demostrado.

| ID | Severidad | Evidencia / ubicación | Resultado |
|---|---|---|---|
| A1 | ALTO, latente | backend/app/main.py:25 y backend/app/route_security.py:8 | Dependencias globales no protegían Mount ni Route Starlette. Reproducido con aplicaciones sintéticas: 200 anónimo. No se encontró esa exposición en endpoints productivos existentes. Corregido con guardia de inventario por solicitud: configuración no revisada da 503 antes de handlers/recursos. |
| A2 | MEDIO, potencial por configuración | frontend/vite.config.ts:11; frontend/src/lib/apiConfig.ts:1; frontend/src/lib/authConfig.ts:1 | Antes podía empaquetarse una URL pública con credenciales aunque se rechazara en runtime; Supabase URL no se validaba si faltaba key. Se comparte validación pura con Vite, antes del bundle. No se detectó una credencial productiva filtrada. |
| A3 | BAJO, estabilidad | frontend/src/lib/http.ts:34 | Un 403 tardío podía bloquear una sesión posterior. Se comprueba token actual y señal cancelada tras el await antes de emitir eventos 401/403. No se demostró elevación de privilegios. |
| A4 | BAJO, estabilidad | frontend/src/components/AuthGate.tsx:48 | Payload de evento Auth podía proceder de otra pestaña, mientras sessionStorage pertenece a la pestaña actual. Se recupera sesión desde el propio SDK, fuera del callback, con secuencia y cleanup. No se usa el payload como autoridad ni se promete sincronización multitab completa. |
| A5 | BAJO, robustez | backend/app/authentication.py:82,108,116 | Headers JSON profundamente anidados y NumericDate no finito podían acabar en error interno; nbf opcional aceptaba conversiones de tipo. Ahora 401 para token malformado, nbf entero estricto y 503 si JWKS malformado. No había bypass de firma. |
| A6 | BAJO, defensa adicional | backend/app/auth_dependencies.py:24 | Authorization duplicado generaba ambigüedad entre componentes. Se rechaza con 401 antes de verificar claves o consultar roles. |
| A7 | BAJO, exposición informativa | backend/app/main.py:28; backend/app/config.py:116 | Swagger/OpenAPI públicos por defecto. Se incorpora BACKEND_DOCS_ENABLED=false para producción; true conserva desarrollo. Sin permisos sobre datos por esta opción. |
| P1 | MEDIO, riesgo residual XSS | frontend/src/lib/supabase.ts:12 | sessionStorage accesible a JavaScript. No se identificó un sink XSS en el código inspeccionado; no es HttpOnly. Una migración a cookies/BFF requeriría otra fase y CSRF. |
| P2 | MEDIO, disponibilidad | backend/app/rate_limit.py:15; backend/app/main.py:34 | Límite IA por proceso/usuario, no distribuido ni límite global de conexiones/consultas. Requiere proxy y decisión antes de varios workers. No se hicieron pruebas de carga. |
| P3 | MEDIO, despliegue | backend/app/config.py:69,83 | sslmode=require es el default admitido: cifra, pero no equivale a verify-full con identidad de servidor validada. Revisar CA/host al desplegar. No se cambió configuración privada ni se demostró MITM. |
| P4 | MEDIO, compatibilidad de despliegue | backend/app/config.py:98 | Ollama solo loopback. En contenedor, loopback no apunta al Ollama de Windows. No ampliar allowlist sin aprobar red/aislamiento. La alternativa local de reglas sigue disponible. |
| P5 | BAJO, rendimiento | frontend/vite.config.ts:17 | Chunk de ECharts 525.81 kB minificado; build correcto con aviso >500 kB. No se ocultó ni se rediseñaron gráficos. |

CRÍTICO: ninguno confirmado dentro del alcance local. No equivale a ausencia de fallos
críticos en infraestructura o configuraciones remotas que no se inspeccionaron.

## Controles revisados (14 áreas)

1. **JWT:** firma exclusivamente ES256, URL JWKS derivada de configuración confiable,
   issuer/audience, exp/iat, sub/session_id UUID no nulos, role=authenticated, aal1/aal2,
   is_anonymous=false. HS256/none/otros algoritmos y jku/x5u/jwk/crit rechazados.
   Cache 300 s, cooldown 30 s, timeout 5 s, 64 KiB de JWKS y token 16 KiB. Nbf, si existe,
   entero. Posible latencia de revocación/rotación documentada; sin revocación remota instantánea.
2. **RBAC:** fuente privada consultada por sub verificado, no headers, body o metadata.
   Sin rol/deshabilitado/desconocido: 403; fuente no disponible: 503. Clientes, ML e IA
   bloqueados a VIEWER, también mediante HTTP directo. Tests prueban ausencia de trabajo
   analítico/artefactos/proveedor cuando falla autorización. No hay administración HTTP.
3. **SQL:** analytics.py:61 y role_repository.py:31 usan parámetros; nombres de tablas
   son constantes. database.py:27 comprueba identidad lectora y atributos no administrativos.
   La tabla de roles permite lectura general a esa cuenta: no se afirma aislamiento de
   usuarios web dentro de PostgreSQL. No se verificaron grants/RLS remotos nuevamente.
4. **XSS/URLs:** React usa texto JSX; no se identificaron dangerouslySetInnerHTML/eval
   ni ejecución de HTML en código productivo. charts.ts:16,31 y predictionChart.ts:10 usan
   tooltips richText. API HTTPS salvo loopback, sin credenciales, fragmentos ni query en base.
5. **CSRF:** API usa Bearer explícito y credentials:omit; no autentica mediante cookies.
   Una cookie o formulario cross-origin sin Bearer da 401. No se añadió un token CSRF
   innecesario; si se migra a cookies, habrá que revisar CSRF/SameSite/Secure/orígenes.
6. **CORS/cabeceras/errores:** orígenes explícitos y Authorization permitido, sin wildcard
   con credenciales. CORS no sustituye autenticación. No-store, nosniff, DENY y no-referrer.
   401/403/429/503 y errores inesperados sanitizados; logs propios sin tokens/prompts/UUID.
7. **Abuso/timeouts:** cuerpo real 16 KiB y recepción total 10 s; SQL 15 s por sentencia,
   conexión 10 s y lock 5 s; Ollama limitado y concurrente una tarea. Son límites por
   operación, no una garantía de deadline absoluto para toda petición. El proxy es necesario.
8. **Prompt injection:** clasificación por temas y funciones permitidas. El modelo recibe
   agregados acotados, sin pregunta original, nombres/IDs de clientes ni secretos.
   assistant.py:98,101 valida IDs y estructura; respuesta construida con hechos del servidor.
   assistant_provider.py:11,12,68 limita contexto/salida y rechaza herramientas/razonamiento.
   No SQL generado, eval, comandos ni lectura de archivos solicitados por usuario.
9. **Secretos:** búsqueda heurística en 160 textos versionados (máximo 2 MB por archivo).
   Dos coincidencias de URI en tests/test_conexion_supabase.py:131,138 corresponden a
   casos de validación/redacción; no se confirmó secreto productivo. Cero commits en rutas
   .env, frontend/.env y frontend/.env.local consultadas. No se escanearon todos los blobs
   de todo el historial: no afirmar limpieza histórica absoluta. Data/artifacts/env ignorados.
   Build final también revisado sin mostrar coincidencias/valores sensibles.
10. **Dependencias:** npm audit devolvió 0 vulnerabilidades conocidas. OSV querybatch no
    reportó avisos para 14 paquetes Python instalados: fastapi, starlette, uvicorn, pydantic,
    pydantic-core, python-dotenv, psycopg, psycopg-binary, PyJWT, cryptography, anyio, h11,
    httpx2, cffi. Consulta parcial, no todo .venv/transitivos/ETL/ML/SO ni garantía futura.
    No se instalaron herramientas ni se cambiaron versiones. requirements backend no es lock.
11. **Datos restringidos:** permisos separados y /auth/me sin JWT ni consultas analíticas.
    predicciones valida JSON de tamaño acotado bajo artifacts/machine_learning; no carga
    pickle ni entrena. VIEWER no monta ni consulta secciones restringidas.
12. **Rutas/documentación:** FastAPI/APIRouter mantienen dependencia global y política explícita.
    Inventario rechaza Mount, raw Route, rutas custom y wrappers desconocidos, incluso añadidos
    después del inicio. Solo rutas de documentación originales son excepciones de framework.
    Si se añade un mecanismo no soportado, TODA respuesta HTTP pasa a 503 para fallar cerrada
    hasta corregir configuración. WebSocket no soportado se cierra con 1008. No crear un bypass
    para static/mounts: requerir revisión aparte. La detección de routers diferidos se prueba
    con la versión instalada de FastAPI; al actualizarla, conservar estas regresiones.
13. **Validación:** Pydantic en contratos; pregunta y ProviderPlan extra=forbid, límites
    de longitud/contenido y limit 1..50. Respuestas inválidas son genéricas. No todo parámetro
    desconocido de GET se rechaza actualmente; ignorarlo no le concede autoridad ni cambia SQL.
14. **Sesiones:** SDK oficial, renovación y recuperación desde el almacenamiento propio,
    logout local, cancelación de peticiones y comprobación de UUID efectivo. Una respuesta
    antigua no restaura datos tras logout. Los JWT emitidos no se invalidan instantáneamente
    por logout; disabled bloquea el siguiente lookup. Datos ya recibidos no se borran de la
    memoria de quien los haya copiado. Los tests multitab son simulados, no navegación real.

## Despliegue Vercel + backend Docker (recomendaciones; no ejecutadas)

- Vercel: root frontend, npm ci, npm run build, salida dist. Solo VITE_API_BASE_URL HTTPS,
  VITE_SUPABASE_URL y Publishable key públicas. Nunca .env de servidor, DB password o secret.
- Frontend HTTP: nosniff, no-referrer, frame-ancestors/anti-frame y política de caché HTML
  apropiada. Diseñar CSP con orígenes reales de Auth/API y probar en staging/report-only.
  No introducir unsafe-inline/unsafe-eval por comodidad ni una CSP que rompa Vite/HMR/ECharts.
  No se añadió una CSP en esta fase. Revisar requisitos concretos del bundle antes de imponerla.
- Docker: imagen Python compatible y no root; instalar solo dependencias backend (no ETL/ML).
  Preparar .dockerignore: .git, .env*, .venv, node_modules, data, modelos y artifacts. Montar
  únicamente resumen de predicciones necesario en volumen read-only, no toda la carpeta.
  No hay Dockerfile/.dockerignore creado ni despliegue validado en este repositorio.
- Inyectar BACKEND_DB_* y SUPABASE_AUTH_URL al ejecutar el contenedor, nunca en imagen ni
  argumentos versionados. Valorar verify-full con CA/host válidos; no cambiar credenciales.
- BACKEND_DOCS_ENABLED=false en producción; mantener true localmente si se necesita Swagger.
  No usar --reload/debug. Empezar con un worker para conservar RAM y cuotas por proceso:

```text
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
```

- Publicar solo mediante TLS/proxy; limitar conexiones, cabeceras, cuerpo, ritmo global y
  tiempos. Confiar forwarded headers solo del proxy conocido, nunca indiscriminadamente.
  Conservar eventos mínimos de seguridad y evitar access logs con queries/tokens.
- CORS_ORIGINS debe contener orígenes exactos de frontend, incluidos previews solo si se
  autorizan explícitamente. No wildcard de todos los dominios Vercel. Eliminar orígenes de
  desarrollo en producción si no se necesitan. Hosts confiables requieren dominio conocido.
- Redis/servicio adicional NO se introduce: si se decide usar múltiples workers/réplicas,
  aprobar una estrategia de cuotas compartidas antes de asumir que seis/minuto es global.
- Ollama en Docker requiere una decisión previa de red: 127.0.0.1 es el propio contenedor,
  no Windows ni otro servicio. No se habilitó host.docker.internal, URL arbitraria ni puerto
  Ollama público. Mantener proveedor local de reglas hasta aprobar y probar una red privada
  o una alternativa compatible. Detenerse antes de ese cambio de arquitectura.
- Verificar manualmente Data API (dwh/app_security no expuestos), grants efectivos, RLS y
  estrategia MFA del ADMIN con aprobación separada. No se modificaron esos controles remotos.
  No tener registro en React NO demuestra que signup público esté deshabilitado en Supabase.
  No se inspeccionó esa opción remota: usuarios nuevos sin asignación quedan en 403, pero
  deben revisarse invitaciones, cuotas y política de altas. Tampoco se exige aal2 a ADMIN
  actualmente; añadir MFA obligatorio exige aprobar política y flujo antes de bloquear cuentas.
- Para reproducibilidad, preparar lock específico del backend en entorno limpio; no congelar
  toda la .venv que mezcla ETL/ML. Revisar avisos periódicamente, sin upgrades masivos ciegos.

## Pruebas y evidencia local

- Backend: **358 aprobadas, 0 fallidas** (338 anteriores + 20 regresiones).
- Frontend: **91 aprobadas, 0 fallidas** (85 anteriores + 6 regresiones).
- TypeScript aprobado; producción aprobada. ECharts 525.81 kB minificado mantiene aviso >500 kB.
- git diff --check sin errores. No se modificaron SQL, datos, usuarios, RLS o credenciales.
- npm audit: 0; OSV: 0 avisos en el conjunto limitado descrito. Son resultados puntuales.
- Escaneo de 5 archivos textuales del build: sin patrones de claves privadas, secret keys,
  JWT literales o contraseñas URI. Publishable key es pública; no se considera secreto.
- No pruebas de carga, fuzzing agresivo, ataques públicos, SQL remoto ni nuevo login real.
  Las reproducciones de bypass fueron apps TestClient sintéticas, con JSON ficticio.

PowerShell desde raíz:

```powershell
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider
Push-Location frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npm.cmd audit
Pop-Location
git diff --check
```

## Calidad y referencias

SRP: inventario de rutas separado; validadores puros compartidos build/runtime; JWT, roles,
HTTP y sesiones continúan separados. DRY evita repetir reglas de URL. KISS/YAGNI: sin nuevas
dependencias, gateway, cookies/BFF, motor de políticas ni servicios de rate limiting.
Los tests prueban efectos y ausencia de acceso a recursos, no solo implementación.

Referencias: [OWASP autorización](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html),
[OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
[Supabase JWT](https://supabase.com/docs/guides/auth/jwts), [OSV API](https://google.github.io/osv.dev/api/).
Aplicación orientada a principios OWASP; no se afirma conformidad ASVS sin evaluación formal.
