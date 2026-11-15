-- SOLO PROPUESTA LOCAL. NO EJECUTADO. Requiere aprobación explícita posterior.
-- Instalación inicial PG17: aborta si app_security ya existe; no oculta incompatibilidades.
-- Revisar manualmente Data API: app_security NO debe estar en "Exposed schemas".
-- Sin contraseñas, usuarios, asignaciones, funciones SECURITY DEFINER ni cambios en dwh.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $preflight$
DECLARE reader_oid oid;
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 17 THEN
        RAISE EXCEPTION 'Se requiere PostgreSQL 17';
    END IF;
    IF to_regnamespace('app_security') IS NOT NULL THEN
        RAISE EXCEPTION 'app_security ya existe; revisar manualmente, no reutilizar objetos desconocidos';
    END IF;
    IF current_user IN ('anon','authenticated','wwi_backend_reader') THEN
        RAISE EXCEPTION 'Ejecutar como operador administrativo autorizado';
    END IF;
    reader_oid := to_regrole('wwi_backend_reader');
    IF reader_oid IS NULL OR NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE oid=reader_oid AND rolcanlogin
          AND NOT (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication OR rolinherit)
    ) OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=reader_oid) THEN
        RAISE EXCEPTION 'Perfil del lector incompatible';
    END IF;
    IF (SELECT count(*) FROM pg_roles WHERE rolname IN ('anon','authenticated')) <> 2
       OR to_regclass('auth.users') IS NULL THEN
        RAISE EXCEPTION 'Faltan objetos o roles esperados de Supabase';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname=current_user)
          AND d.defaclnamespace=0 AND d.defaclobjtype IN ('r','S')
          AND (a.grantee=0 OR a.grantee IN
               (SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated','wwi_backend_reader')))
    ) THEN
        RAISE EXCEPTION 'Defaults globales incompatibles: un REVOKE por esquema no los neutraliza; revisión separada';
    END IF;
    IF 'app_security' = ANY(string_to_array(replace(
        coalesce(current_setting('pgrst.db_schemas',true),''),' ',''),',')) THEN
        RAISE EXCEPTION 'app_security aparece en esquemas Data API; revisar configuración antes de continuar';
    END IF;
    -- current_setting puede no reflejar la configuración efectiva de PostgREST:
    -- la comprobación manual en Supabase sigue siendo obligatoria.
END $preflight$;

CREATE SCHEMA app_security;
COMMENT ON SCHEMA app_security IS 'DataInsight-WWI private authorization (phase 2)';
REVOKE ALL ON SCHEMA app_security FROM PUBLIC, anon, authenticated, wwi_backend_reader;
-- Solo objetos futuros del ejecutor en ESTE esquema; no modificar defaults globales.
ALTER DEFAULT PRIVILEGES IN SCHEMA app_security REVOKE ALL ON TABLES
    FROM PUBLIC, anon, authenticated, wwi_backend_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA app_security REVOKE ALL ON SEQUENCES
    FROM PUBLIC, anon, authenticated, wwi_backend_reader;
-- No se crean funciones. Cualquier función futura debe revisar EXECUTE/defaults
-- globales (EXECUTE a PUBLIC es el default PostgreSQL) antes de su creación.
CREATE TABLE app_security.user_roles (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('ADMIN','ANALYST','VIEWER')),
    enabled boolean NOT NULL DEFAULT false,
    CONSTRAINT nonzero_user CHECK (user_id <> '00000000-0000-0000-0000-000000000000'::uuid)
);
ALTER TABLE app_security.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_security.user_roles FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE app_security.user_roles FROM PUBLIC, anon, authenticated, wwi_backend_reader;
GRANT USAGE ON SCHEMA app_security TO wwi_backend_reader;
GRANT SELECT (user_id,role,enabled) ON TABLE app_security.user_roles TO wwi_backend_reader;
CREATE POLICY backend_read_roles ON app_security.user_roles
    FOR SELECT TO wwi_backend_reader
    USING (current_user = 'wwi_backend_reader');
-- Política de cuenta de servicio: el lector puede leer TODAS las asignaciones.
-- No ofrece aislamiento por usuario web ni verifica JWT dentro de PostgreSQL.
-- FastAPI valida ES256, consulta WHERE user_id = %s con el sub verificado y
-- comprueba que la asignación retornada pertenece a ese mismo sub.
-- Ningún parámetro PostgreSQL representa la identidad del usuario.
-- Las credenciales lectoras permanecen exclusivamente en el servidor.
-- Ninguna política de escritura. Ninguna asignación de rol ni ADMIN automático.
DO $postflight$
DECLARE reader_oid oid := 'wwi_backend_reader'::regrole;
BEGIN
    IF has_table_privilege(reader_oid,'app_security.user_roles','SELECT')
       OR NOT has_schema_privilege(reader_oid,'app_security','USAGE')
       OR has_schema_privilege(reader_oid,'app_security','CREATE')
       OR has_table_privilege(reader_oid,'app_security.user_roles',
           'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
       OR has_any_column_privilege(reader_oid,'app_security.user_roles','INSERT,UPDATE,REFERENCES') THEN
        RAISE EXCEPTION 'El lector tiene privilegios efectivos inesperados';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles r WHERE r.rolname IN ('anon','authenticated')
        AND (has_schema_privilege(r.oid,'app_security','USAGE,CREATE')
             OR has_table_privilege(r.oid,'app_security.user_roles','SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
             OR has_any_column_privilege(r.oid,'app_security.user_roles','SELECT,INSERT,UPDATE,REFERENCES'))) THEN
        RAISE EXCEPTION 'Acceso efectivo inesperado de clientes API';
    END IF;
END $postflight$;
COMMIT;
