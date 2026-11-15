-- SOLO REVISIÓN LOCAL. Ejecutar únicamente tras aprobación separada.
-- Consultas de verificación de catálogo: no muestran asignaciones ni usuarios reales.
SELECT nspname,pg_get_userbyid(nspowner) AS owner,nspacl
FROM pg_namespace WHERE nspname='app_security';
SELECT column_name,data_type,is_nullable,column_default FROM information_schema.columns
WHERE table_schema='app_security' AND table_name='user_roles' ORDER BY ordinal_position;
SELECT conname,pg_get_constraintdef(oid) FROM pg_constraint
WHERE conrelid=to_regclass('app_security.user_roles');
SELECT relrowsecurity,relforcerowsecurity,pg_get_userbyid(relowner) AS owner,relacl
FROM pg_class WHERE oid=to_regclass('app_security.user_roles');
SELECT policyname,permissive,roles,cmd,qual,with_check FROM pg_policies
WHERE schemaname='app_security';
SELECT r.rolname,has_schema_privilege(r.oid,'app_security','USAGE') AS usage,
       has_schema_privilege(r.oid,'app_security','CREATE') AS create_schema,
       has_table_privilege(r.oid,'app_security.user_roles','SELECT') AS table_select,
       has_table_privilege(r.oid,'app_security.user_roles','INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') AS extra_table,
       has_any_column_privilege(r.oid,'app_security.user_roles','INSERT,UPDATE,REFERENCES') AS extra_column
FROM pg_roles r WHERE rolname IN ('anon','authenticated','wwi_backend_reader');
SELECT r.rolname,a.attname,has_column_privilege(r.oid,a.attrelid,a.attnum,'SELECT') AS readable
FROM pg_roles r CROSS JOIN pg_attribute a
WHERE r.rolname IN ('anon','authenticated','wwi_backend_reader')
  AND a.attrelid=to_regclass('app_security.user_roles') AND a.attnum>0 AND NOT a.attisdropped;
SELECT d.defaclnamespace,d.defaclobjtype,d.defaclacl FROM pg_default_acl d
WHERE d.defaclnamespace IN (0,to_regnamespace('app_security'));
SELECT current_setting('pgrst.db_schemas',true) AS visible_postgrest_setting;
-- Comprobar además "Exposed schemas" en Supabase: este setting puede ser NULL
-- o no representar la configuración real de la conexión PostgREST.

-- Comprobaciones efectivas. No leer ni mostrar auth.users ni asignaciones individuales.
-- Sin privilegio de tabla SELECT: se requieren grants solo a las tres columnas.
DO $assertions$
DECLARE reader_oid oid := 'wwi_backend_reader'::regrole; column_name text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE oid=reader_oid AND rolcanlogin
        AND NOT (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication OR rolinherit))
       OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=reader_oid) THEN
        RAISE EXCEPTION 'Perfil del lector incompatible';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_class
        WHERE oid=to_regclass('app_security.user_roles') AND relrowsecurity AND relforcerowsecurity) THEN
        RAISE EXCEPTION 'Faltan tabla o controles RLS';
    END IF;
    IF NOT has_schema_privilege(reader_oid,'app_security','USAGE')
       OR has_schema_privilege(reader_oid,'app_security','CREATE')
       OR has_table_privilege(reader_oid,'app_security.user_roles',
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
       OR has_any_column_privilege(reader_oid,'app_security.user_roles','INSERT,UPDATE,REFERENCES') THEN
        RAISE EXCEPTION 'Permisos efectivos del lector incompatibles';
    END IF;
    FOREACH column_name IN ARRAY ARRAY['user_id','role','enabled'] LOOP
        IF NOT has_column_privilege(reader_oid,'app_security.user_roles',column_name,'SELECT') THEN
            RAISE EXCEPTION 'Falta permiso de columna requerido';
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN ('anon','authenticated')
        AND (has_schema_privilege(r.oid,'app_security','USAGE,CREATE')
             OR has_table_privilege(r.oid,'app_security.user_roles',
                 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
             OR has_any_column_privilege(r.oid,'app_security.user_roles','SELECT,INSERT,UPDATE,REFERENCES'))) THEN
        RAISE EXCEPTION 'Acceso inesperado de clientes API';
    END IF;
END $assertions$;

-- Sondeo READ ONLY. Requiere capacidad SET ROLE del operador; no la concede.
-- No se configura user_id ni ninguna otra identidad de usuario web en PostgreSQL.
BEGIN READ ONLY;
SET LOCAL ROLE wwi_backend_reader;
DO $reader$
BEGIN
    IF current_user <> 'wwi_backend_reader'
       OR NOT row_security_active('app_security.user_roles'::regclass) THEN
        RAISE EXCEPTION 'Identidad lectora o RLS incompatibles';
    END IF;
END $reader$;
SELECT user_id,role,enabled FROM app_security.user_roles LIMIT 0;
-- Sin asignaciones devuelve 0; con asignaciones, el lector debe ver TODAS las filas.
-- Un conteo cero sobre una tabla vacía no demuestra una política SELECT funcional.
SELECT count(*) AS visible_role_assignments FROM app_security.user_roles;
ROLLBACK;
-- Revisar también la definición de la política mostrada arriba: exclusivamente
-- FOR SELECT TO wwi_backend_reader USING (current_user = 'wwi_backend_reader').
-- Prueba positiva posterior: con asignaciones aprobadas, comparar el conteo del
-- lector con el del operador autorizado y probar FastAPI con sesiones reales.
-- No crear usuarios/asignaciones ni modificar políticas para realizar este sondeo.

SELECT 'Catálogos y sondeo completados; revisar definición RLS, Data API y prueba positiva pendiente' AS resultado;
