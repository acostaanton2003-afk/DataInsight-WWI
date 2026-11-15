-- REVERSIÓN DE ACCESO, SOLO LOCAL PARA REVISIÓN. NO EJECUTAR SIN AUTORIZACIÓN.
-- Conserva esquema, tabla, filas, restricciones y RLS. No toca dwh.
-- Revoca la lectura al backend: las solicitudes de negocio pasarán a 503, no a permitidas.
BEGIN;
SET LOCAL search_path=pg_catalog;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DO $guard$
BEGIN
    IF obj_description(to_regnamespace('app_security'),'pg_namespace')
       IS DISTINCT FROM 'DataInsight-WWI private authorization (phase 2)' THEN
        RAISE EXCEPTION 'Esquema no reconocido; revisar manualmente';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_namespace
        WHERE nspname='app_security' AND nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) THEN
        RAISE EXCEPTION 'Ejecutar como propietario autorizado';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_class
        WHERE oid=to_regclass('app_security.user_roles')
          AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) THEN
        RAISE EXCEPTION 'Ejecutar también como propietario de la tabla';
    END IF;
END $guard$;
REVOKE SELECT (user_id,role,enabled) ON app_security.user_roles FROM wwi_backend_reader;
REVOKE ALL ON TABLE app_security.user_roles FROM wwi_backend_reader;
REVOKE USAGE ON SCHEMA app_security FROM wwi_backend_reader;
DO $postflight$
DECLARE reader_oid oid := 'wwi_backend_reader'::regrole;
BEGIN
    IF has_schema_privilege(reader_oid,'app_security','USAGE,CREATE')
       OR has_table_privilege(reader_oid,'app_security.user_roles',
            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
       OR has_any_column_privilege(reader_oid,'app_security.user_roles','SELECT,INSERT,UPDATE,REFERENCES') THEN
        RAISE EXCEPTION 'Reversión incompleta: revisar permisos efectivos, sin revocar grants globales automáticamente';
    END IF;
END $postflight$;
COMMIT;
-- Reaplicar acceso requiere revisión/aprobación específica. No volver a ejecutar
-- 01: deliberadamente aborta ante esquema existente. No borrar la tabla para repetirlo.
