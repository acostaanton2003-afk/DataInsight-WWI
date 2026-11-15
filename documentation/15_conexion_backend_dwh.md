# Conexion del backend al DWH (solo lectura)

## Estado y decision pendiente

Se preparo la conexion, sin conectar a Supabase ni ejecutar SQL de roles, permisos o politicas. El DDL versionado activa RLS sin crear politicas; esto no demuestra cuales son las politicas vigentes en el proyecto remoto. Con RLS sin politicas, SELECT puede devolver cero filas aunque tenga GRANT. No se ha probado todavia visibilidad real con el nuevo rol.

Se eligio revisar politicas SELECT especificas, manteniendo RLS. **El script 06 sigue pendiente de autorizacion explicita antes de ejecutarse.** Su alcance es TODAS las filas presentes y futuras de las cinco tablas. Si se necesitan filtros por usuario/cliente, detenerse y disenarlos antes: este rol compartido no proporciona aislamiento por usuario final. Las politicas restrictivas existentes pueden limitar la propuesta. No se concede BYPASSRLS, no se cambia propietario, no se desactiva RLS ni se expone dwh mediante Data API.

## Pasos manuales en Supabase

1. En SQL Editor, inspeccionar con la primera seccion de `database/data-warehouse/07_verificacion_backend_lectura.sql` las politicas y permisos vigentes. Revisar tambien quien es propietario de dwh y de las tablas. No ejecutar el bloque final como postgres para acreditar visibilidad del lector.
2. Revisar y autorizar manualmente `05_rol_backend_lectura.sql`. Ejecutarlo como propietario de dwh con capacidad de crear roles y otorgar permisos. Es transaccional e idempotente: crea `wwi_backend_reader` sin contrasena si no existe; si existe conserva su contrasena y rechaza atributos peligrosos, membresias, propiedad o permisos adicionales detectados. Concede solamente CONNECT, USAGE y SELECT explicito en las cinco tablas. No concede secuencias (no hay IDENTITY), privilegios futuros ni permisos a anon/authenticated.
3. Si el preflight detecta CREATE efectivo por PUBLIC, detenerse: PostgreSQL suma permisos y un REVOKE al lector no cancela permisos de PUBLIC. Revisar el impacto de una correccion global por separado; el script no la aplica. Revisar tambien permisos adicionales sobre otros objetos de una base compartida: el script no es una auditoria global de funciones SECURITY DEFINER ni de concesiones ajenas al DWH.
4. Solo despues de aprobar explicitamente lectura completa, revisar y ejecutar `06_propuesta_rls_backend.sql`. Crea politicas SELECT para el lector; si encuentra una politica homonima incompatible falla sin reemplazarla. No ejecutar automaticamente junto al 05. Las politicas existentes se inspeccionan antes y se prueba la visibilidad despues.
5. Generar una contrasena unica con un gestor de contrasenas. En una consulta privada y temporal del SQL Editor establecer la contrasena mediante ALTER ROLE para `wwi_backend_reader`, escribiendo el literal unicamente alli, nunca en estos scripts, terminal, Git, capturas o documentacion. Escapar comillas simples duplicandolas. El SQL Editor puede conservar historial y el servidor puede registrar consultas: no se garantiza ausencia de la contrasena en ese historial. Si esto no es admisible, usar `psql` con `\password wwi_backend_reader` y entrada interactiva, en lugar del SQL Editor. Rotar si se expone; no guardar la consulta con el secreto.
6. Configurar exclusivamente BACKEND_DB_* en el `.env` local ignorado. No modificar SUPABASE_DB_* del ETL ni usar postgres. Host/puerto segun conexion directa o pooler del proyecto; con pooler el usuario suele ser `wwi_backend_reader.<project-ref>`. El rol efectivo debe seguir siendo `wwi_backend_reader`. Si el pooler rechaza el rol, comprobar formato y soporte del proyecto, sin recurrir al administrador.

Variables existentes, independientes del ETL: BACKEND_DB_HOST, BACKEND_DB_PORT, BACKEND_DB_NAME, BACKEND_DB_USER, BACKEND_DB_PASSWORD, BACKEND_DB_SSLMODE. Ejemplos permanecen vacios. SSL minimo `require`; preferir `verify-full` con CA confiable y nombre correcto. `require` cifra pero no equivale a verificar identidad del servidor. Entorno del proceso prevalece sobre `.env`, sin interpolacion ni impresion de secretos.

## Ejecutar desde PowerShell en la raiz

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
# Solo despues de los pasos manuales y de configurar el rol lector:
.\.venv\Scripts\python.exe -m backend.app.database
.\.venv\Scripts\python.exe -m backend
```

El probe hace solo SELECT, exige rol efectivo sin atributos administrativos, RLS activo y conteos visibles 1249/664/228/228265/73595 (304001). Son referencias actuales, no constantes universales: cualquier cambio requiere revisar conciliacion antes de actualizar la referencia. Un fallo puede ser politica restrictiva, default-deny, permisos, SSL o conectividad; no se imprimen excepciones del driver, filas ni secretos. La verificacion SQL final debe ejecutarse con credenciales reales del lector. Revisar que CONNECT/USAGE/SELECT sean verdaderos, CREATE/escritura falsos, ninguna membresia y RLS activo. No probar escrituras reales para comprobar permisos.

La conexion usa parametros separados, timeout de conexion 10 s, consultas 15 s, bloqueo 5 s, transaccion read-only y cierre mediante context manager (rollback ante error). No hay pool ni conexion al importar/iniciar health. El modo read-only es defensa adicional, no sustituye privilegios minimos y auditoria RLS. No se aceptan consultas SQL libres desde HTTP ni se anaden endpoints de negocio.

## Validacion local y limites

Pruebas con configuracion y conexiones ficticias: SSL, independencia del ETL, rechazo administrativo, cierre, errores sin secretos, RLS inactivo y cero filas rechazados. La prueba real queda pendiente de autorizacion y configuracion manual; las pruebas unitarias no acreditan politicas remotas.

Referencias PostgreSQL 17: [RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), [roles](https://www.postgresql.org/docs/17/sql-createrole.html), [GRANT](https://www.postgresql.org/docs/17/sql-grant.html). No se ejecuto DDL ni se modificaron datos, permisos o roles durante esta etapa.

Resultado local: 49 pruebas de backend y 98 pruebas existentes aprobadas; git diff --check sin errores. No se ejecuto el probe real ni los scripts SQL.
