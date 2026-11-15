# Fase 3: login React y Supabase Auth con RBAC efectivo

## Alcance

Login con correo/contraseña usando @supabase/supabase-js oficial, recuperación de sesión,
renovación automática y cierre local de sesión. React solicita GET /api/v1/auth/me antes
de montar el dashboard. No se consulta PostgreSQL desde el navegador.
El usuario confirmó que la tabla de roles y el primer ADMIN ya están instalados.
Esta fase no modifica SQL, RLS, ETL, ML ni usuarios remotos; no se despliega.

El nuevo endpoint exige sesión ES256 y un rol habilitado. Reutiliza el lookup de la
dependencia global (una consulta de rol) y devuelve exclusivamente:

```json
{
  "user_id": "11111111-1111-4111-8111-111111111111",
  "role": "VIEWER",
  "permissions": ["general:read", "profile:read"]
}
```

UUID del ejemplo ficticio. No devuelve JWT, email, contraseña ni filas analíticas.
PROFILE_READ se concede a ADMIN/ANALYST/VIEWER; no es una ruta pública ni un bypass.
Roles desconocidos, deshabilitados o no asignados siguen dando 403; fuente no disponible,
503. No hay registro ni administración de usuarios/roles desde React.

## Configuración pública necesaria

En Supabase: abrir el proyecto → Project Settings → API Keys → Publishable key.
Copiar la clave pública con prefijo sb_publishable_ al archivo local indicado. No compartir
contraseñas ni copiar secret/service_role, JWT Secret o cadenas PostgreSQL.
No se inventó ni configuró una clave real: la verificación de login real queda pendiente.

Desde PowerShell, raíz del repositorio, crear frontend/.env.local a partir del ejemplo
si no existe. No sobrescribir un archivo existente:

```powershell
if (-not (Test-Path -LiteralPath frontend/.env.local)) {
    Copy-Item -LiteralPath frontend/.env.example -Destination frontend/.env.local
}
notepad frontend/.env.local
```

Completar localmente:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_SUPABASE_URL=https://xunsksfkuabfpvjxhjbk.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=
```

La última variable debe contener la Publishable key real; dejarla vacía muestra
Configuración pendiente. No pegar credenciales reales en Git ni capturas.
Vite exige reiniciar el servidor después de cambiar variables. El helper y la configuración
Vite rechazan claves con formato no publicable; si se proporciona una clave incorrecta,
el build aborta antes de incorporarla al bundle y no muestra el valor en el error.
Un build sin clave es posible, pero no tendrá login funcional hasta configurarla y recompilar.
La validación de formato no demuestra que una clave pertenezca al proyecto; Auth lo verifica.

Todas las variables VITE_ se consideran públicas. La publishable key identifica el proyecto,
NO autentica al usuario ni sustituye su access token. El backend mantiene por separado
SUPABASE_AUTH_URL y BACKEND_DB_*; no se copian al frontend ni cambian en esta fase.

Para Vercel, en una fase de despliegue posterior: raíz frontend, comando npm run build,
salida dist y las mismas tres variables públicas. La URL API debe ser HTTPS pública y
pertenecer al backend autorizado; no localhost. Añadir el origen de Vercel en CORS será
un cambio explícito posterior. No se ha desplegado ni modificado esa configuración.

## Arquitectura y sesión

- authConfig.ts valida configuración pública en runtime y antes del build.
- supabase.ts crea un cliente único con persistSession y autoRefreshToken, debug desactivado
  por defecto y detectSessionInUrl=false (solo flujo contraseña en esta fase).
- Session SDK en sessionStorage, no localStorage: permite recuperar tras recargar la pestaña.
  No se promete persistencia tras cerrar el navegador ni funcionamiento coordinado de
  múltiples pestañas. Navegadores pueden restaurar pestañas; cerrar sesión explícitamente
  antes de abandonar un equipo compartido. La coordinación multitab queda por verificar.
- AuthGate escucha eventos de sesión sin esperar operaciones SDK dentro del callback.
  Recupera permisos desde FastAPI, comprueba correspondencia del UUID y bloquea datos
  hasta recibir una identidad válida. No lee roles de user_metadata/app_metadata.
- http.ts centraliza GET/POST, Bearer, credentials:omit y redirect:error. Obtiene el token
  actual del SDK; no lo fija al construir el cliente. HTTP se permite solo en loopback;
  otros destinos API requieren HTTPS. URLs y rutas no proceden de las preguntas del usuario.
- Dashboard conserva el diseño y no monta clientes, predicciones ni asistente sin permiso.
  Los hooks deshabilitados no envían peticiones. Ocultar UI no concede permisos en backend.
- Al cambiar sesión/rol, cerrar sesión o revalidar, se desmontan los datos, se abortan
  consultas y se ignoran respuestas antiguas. No hay caché global de datos protegidos.

Los tokens siguen accesibles al JavaScript del mismo origen: sessionStorage NO es HttpOnly
ni elimina el riesgo XSS. Mantener texto JSX, dependencias revisadas y CSP de despliegue.
No se introducen dangerouslySetInnerHTML, eval ni ejecución del contenido del asistente.

## Respuestas y permisos

| Respuesta | Comportamiento |
|---|---|
| 401 | Retira el dashboard y solicita autenticarse de nuevo. Un 401 de un token ya sustituido no cierra la sesión nueva. |
| 403 | Retira los datos y ofrece revalidación manual de identidad con Reintentar. Sin rol habilitado permite salir. No hay bucles automáticos de reconsulta. |
| 429 | Mensaje de límite temporal y reintento manual, sin bucles automáticos. |
| 503 | Mensaje genérico y reintento manual; no muestra respuestas del servidor ni datos ficticios. |

VIEWER: KPI, mensual y productos. ANALYST/ADMIN: además clientes, predicciones y asistente.
ADMIN no dispone de interfaz administrativa en esta fase. Cada petición vuelve a autorizarse
en FastAPI; la UI puede reflejar permisos anteriores hasta una revalidación, pero no permite
nuevas lecturas si el servidor los revoca. Un navegador que ya recibió datos no puede
"desrecibirlos" retroactivamente.

Logout usa signOut(scope:local). Se ocultan los datos inmediatamente y se solicita revocar
la sesión actual; no se cierran deliberadamente otros dispositivos. Si falla, se informa
sin fingir una revocación exitosa y se permite reintentar. Un access token emitido puede
seguir siendo criptográficamente válido hasta expirar; la verificación local ES256 no
consulta revocación instantánea. enabled=false bloquea el siguiente lookup de autorización.
No se registran tokens ni credenciales; tampoco se muestran detalles crudos de errores Auth.

## Instalación, pruebas y ejecución local

Terminal 1, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -B -m pytest backend/tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m backend
```

Terminal 2, desde la raíz:

```powershell
Set-Location frontend
npm.cmd ci
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npm.cmd run dev
```

Abrir http://127.0.0.1:5173 o http://localhost:5173. CORS ya admite ambos orígenes.
Con clave pública configurada, usar personalmente la cuenta habilitada existente:

1. Antes del login no deben existir consultas de KPI/clientes/ML/IA.
2. Login correcto consulta /api/v1/auth/me y monta únicamente las funciones permitidas.
3. Recargar verifica recuperación; esperar renovación comprueba token nuevo sin fijarlo.
4. Cerrar sesión elimina el dashboard; recargar no debe recuperar una sesión cerrada.
5. Contraseña incorrecta muestra un error genérico. No incluir contraseñas ni tokens en logs,
   DevTools exportados, capturas o informes.

No crear usuarios para estas comprobaciones sin aprobación. Las pruebas automatizadas
usan exclusivamente sesiones, claves, usuarios y repositorios sintéticos/mocks. No hacen
login ni consultas reales a Supabase y no modifican cuentas o roles.
Las pruebas de servicio conservan sus fixtures; AuthGate y RBAC se prueban por separado
sin una excepción de autorización productiva. Se verifica typecheck y build de producción.
Los resultados finales y las limitaciones de integración se registran en la entrega.

Referencias oficiales: [React Auth](https://supabase.com/docs/guides/auth/quickstarts/react),
[eventos de sesión](https://supabase.com/docs/reference/javascript/auth-onauthstatechange),
[claves API](https://supabase.com/docs/guides/api/api-keys).

## Resultados de ejecución

- Backend: **338 pruebas aprobadas**, incluidas 7 nuevas para /auth/me.
- Frontend: **85 pruebas aprobadas** en 9 archivos.
- TypeScript: aprobado en el build final (`tsc --noEmit`).
- Producción: `npm.cmd run build` aprobado. Advertencia de tamaño del chunk ECharts
  (~526 kB minificado); no es un error de compilación y no se ha ocultado el aviso.
- `git diff --check`: sin errores. Instalación npm del cliente oficial reportó cero
  vulnerabilidades en ese momento; no equivale a una auditoría completa de seguridad.
- Se corrigió durante la verificación una referencia a process sin tipos Node en
  vite.config.ts usando loadEnv de Vite, sin añadir dependencias de tipos innecesarias.
- No se verificó login con Supabase real ni se hizo revisión visual del login en navegador:
  falta configurar la Publishable key local. Las pruebas no usan credenciales reales.
