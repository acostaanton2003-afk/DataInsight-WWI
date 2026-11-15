# Backend FastAPI en Docker Desktop / Windows WSL2

## Resultado de esta etapa

- Imagen: `datainsight-wwi-backend:entrega-20261115`, Linux amd64.
- Python de la imagen: 3.13.18; base oficial slim-bookworm fijada por digest.
- Docker 29.7.2 reporta **235 MB de disk usage** y **57 MB de content size**.
  No confundir las dos métricas: inspect devolvió 56 995 466 bytes de contenido.
- Contenedor creado: `datainsight-wwi-backend-prueba-20261115`, healthy, publicado solo
  en `127.0.0.1:8001`. Backend original `127.0.0.1:8000` comprobado con health 200.
- Muestra puntual: **50.3 MiB / 512 MiB**, CPU 0.25%, 2 PIDs. No es prueba de carga.
- Recursos: una CPU, memoria 512 MiB sin swap adicional, 64 PIDs y un worker.
- Usuario 10001:10001, raíz read-only, tmpfs /tmp 16 MiB, todas las capacidades
  eliminadas y no-new-privileges. No instala ni inicia Ollama u otros servicios.
- Contexto de build enviado: **69.91 kB**. pip check: sin requisitos incompatibles.

No SQL remoto, migraciones, ETL, entrenamiento, cambios de usuarios o permisos Supabase.
No se incorporan secretos, datos, modelos, frontend ni dependencias de tests a la imagen.
No se ejecutaron comandos de eliminación de imágenes/contenedores ni cambios de contexto.

## Archivos

- `backend/Dockerfile`: imagen de una etapa, solo wheels precompilados, sin compilador/ODBC.
  Una etapa basta porque no se construyen extensiones y no quedan herramientas de compilación.
- `.dockerignore`: allowlist de fuentes Python en backend/app y routers, backend/__init__.py,
  Dockerfile y lock. No env, Git, .venv, node_modules, data, artifacts ni tests en contexto.
  Si se añade otro subpaquete Python, revisar esta allowlist explícitamente.
- `backend/requirements-docker.lock.txt`: 21 paquetes runtime fijados, derivados de las
  versiones probadas y marcadores Linux de backend/requirements.txt, no de pip freeze global.
- `backend/.env.docker.example`: configuración pública/vacía; el archivo real está ignorado.

Base y paquetes están fijados para esta entrega. No implica ausencia de CVE en Debian o
librerías; no se hizo un escaneo OS/imagen completo. Revisar avisos y actualizar el digest
junto con las pruebas en futuras entregas. El lock no incluye hashes de distribución.

## Construcción desde PowerShell

Desde la raíz del repositorio, con Docker Desktop en modo Linux:

```powershell
docker build --builder desktop-linux --platform linux/amd64 --file backend/Dockerfile --tag datainsight-wwi-backend:entrega-20261115 .
docker image ls datainsight-wwi-backend:entrega-20261115
```

Se usó el builder integrado de Docker Desktop (driver docker), no el antiguo contenedor
BuildKit del usuario. No hay prune ni limpieza automática. Esta etiqueta se creó en esta
etapa; usar otra etiqueta si se desea preservar revisiones futuras de la misma entrega.

## Prueba mínima SIN credenciales de base de datos

Este es el comando usado. El contenedor ya está creado y ejecutándose: no repetirlo con
el mismo nombre. Para recuperarlo después de detenerlo, usar docker start.

```powershell
docker run --detach `
  --name datainsight-wwi-backend-prueba-20261115 `
  --publish 127.0.0.1:8001:8000 `
  --memory 512m --memory-swap 512m --cpus 1 --pids-limit 64 `
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m `
  --cap-drop ALL --security-opt no-new-privileges:true `
  --env SUPABASE_AUTH_URL=https://xunsksfkuabfpvjxhjbk.supabase.co `
  datainsight-wwi-backend:entrega-20261115
```

```powershell
Invoke-RestMethod http://127.0.0.1:8001/api/v1/health
curl.exe -i http://127.0.0.1:8001/api/v1/kpis
docker stats datainsight-wwi-backend-prueba-20261115 --no-stream
docker inspect datainsight-wwi-backend-prueba-20261115 --format '{{.State.Health.Status}}'
```

Esperados: health 200, KPI anónimo 401, healthcheck healthy. /docs, /redoc y /openapi.json
están deshabilitados (404). La URL Supabase es pública, no una contraseña ni cadena privada.

Para detener o arrancar SOLO el contenedor creado aquí:

```powershell
docker stop datainsight-wwi-backend-prueba-20261115
docker start datainsight-wwi-backend-prueba-20261115
```

No se eliminó el contenedor. No usar nombres/puertos de contenedores previos del usuario.
El contenedor de prueba carece de BACKEND_DB_*: un JWT válido no habilita consultas reales;
la fuente de roles falla cerrada con 503 hasta suministrar configuración lectora correcta.
Las pruebas negativas no necesitan datos ni una cuenta real.

## Ejecución funcional: configuración seleccionada del lector

Paso manual opcional posterior. NO usar `--env-file .env` raíz: contiene variables y
credenciales del ETL/administrador que el backend no necesita. No montar ese archivo en /app.

```powershell
if (-not (Test-Path -LiteralPath backend/.env.docker)) {
    Copy-Item -LiteralPath backend/.env.docker.example -Destination backend/.env.docker
}
notepad backend/.env.docker
```

Copiar localmente SOLO BACKEND_DB_HOST/PORT/NAME/USER/PASSWORD/SSLMODE existentes del
lector wwi_backend_reader y SUPABASE_AUTH_URL. No cambiar contraseñas ni crear usuarios.
No compartir ni versionar el archivo. No ejecutar docker inspect sin filtros ni exportar
logs/configuración completa: Docker mantiene variables runtime accesibles al administrador
local del daemon. Los secretos no están en las capas de la imagen.

Para usar 8001 con configuración, detener únicamente nuestra prueba, conservándola;
crear otro nombre de contenedor para no borrar ni reemplazar ninguno:

```powershell
docker stop datainsight-wwi-backend-prueba-20261115
docker run --detach `
  --name datainsight-wwi-backend-runtime-20261115 `
  --publish 127.0.0.1:8001:8000 `
  --memory 512m --memory-swap 512m --cpus 1 --pids-limit 64 `
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m `
  --cap-drop ALL --security-opt no-new-privileges:true `
  --env-file backend/.env.docker `
  datainsight-wwi-backend:entrega-20261115
```

Ese comando no se ejecutó en esta etapa. No imprimir tokens para probar login: usar el
frontend existente después de apuntar su URL pública de API a 8001 de forma deliberada.
No se cambió VITE_API_BASE_URL ni el backend actual en 8000.

## Predicciones: solo el resumen JSON montado read-only

No se empaquetan modelos ni pandas/scikit-learn. El código existente lee el JSON validado
con límites y permisos RBAC. Si no se monta, responde 503 controlado; no inventa datos.

Para habilitarlo, comprobar primero que existe el resumen y añadir esta opción al comando
run ANTES del nombre de imagen (no cambia un contenedor ya creado):

```powershell
$forecastPath = (Resolve-Path -LiteralPath artifacts/machine_learning/published/resumen.json).Path
# Opción para añadir al docker run:
# --mount "type=bind,source=$forecastPath,target=/app/artifacts/machine_learning/published/resumen.json,readonly"
```

Montar solo el archivo publicado, no toda la carpeta de modelos/datos. No se montó ni se
leyó ningún artefacto real para las pruebas de esta etapa. No ejecutar entrenamiento.

## Asistente y seguridad

ASSISTANT_PROVIDER=local conserva respuestas por reglas con sus advertencias. Ollama no
está en la imagen ni puede alcanzarse en Windows usando 127.0.0.1 del contenedor. No se
amplió la allowlist de proveedor a host.docker.internal ni se expuso su puerto: eso requiere
una decisión de red separada. No se han contratado ni usado proveedores de pago.

JWT ES256, JWKS, rol efectivo y permisos se conservan sin modificar código. Un worker
mantiene la cuota por proceso; --limit-concurrency 24 limita peticiones simultáneas y
puede devolver 503 al saturarse. No hay reload, access logs con query ni proxy headers
confiados indiscriminadamente. Healthcheck solo usa urllib de la biblioteca estándar.

No se publica Docker socket, base PostgreSQL ni un puerto de Ollama. El puerto 8001 se
vincula al loopback Windows; para publicar fuera se necesita otra revisión de TLS/proxy.
La autenticación real y acceso DWH con BACKEND_DB_* no se probaron en Docker: solo
pruebas sin credenciales y simuladas. No desactivar RBAC para conseguir un 200.

## Validaciones realizadas

- Health HTTP 200 y JSON status=ok, name=DataInsight WWI, version=0.1.0.
- Siete rutas privadas anónimas: 401, incluida POST del asistente.
- Bearer malformado: 401; documentación deshabilitada: tres 404.
- Dentro de Linux: ES256 real con clave sintética; expirado 401.
- Con repositorio simulado: VIEWER 403 en clientes, predicciones y asistente; /auth/me 200;
  sin asignación 403; fuente de roles no disponible 503. PostgreSQL/proveedor/artefactos
  reales bloqueados con mocks; cero llamadas de base de datos.
- UID 10001 confirmado. Ausencia de .env, .git, .venv, frontend, data, ETL y tests en /app.
- No pandas, numpy, sklearn, joblib, pyodbc, pytest ni httpx2 instalados.
- Healthcheck healthy; filesystem raíz read-only y restricciones Docker comprobadas.
- Backend original 8000 respondió 200 después de iniciar la prueba en 8001.
- No se repitieron suites generales sin cambios del código API/frontend; build, pip check
  y pruebas runtime verificaron los cambios de empaquetado en el entorno real Linux.

### Observación de inventario Docker

El inventario inicial mostró recursos antiguos; al finalizar, default y desktop-linux
mostraron el mismo daemon y solo el contenedor nuevo y las imágenes nuevas visibles.
No se ejecutaron rm, prune, reset ni context use. No se puede confirmar desde esta
observación el estado de los recursos antiguos fuera del inventario visible; revisar
Docker Desktop/almacenamiento antes de cualquier limpieza. No se intentó restaurar,
reiniciar ni alterar recursos ajenos para investigar.
