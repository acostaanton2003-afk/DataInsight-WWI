-- EJECUCION MANUAL AUTORIZADA. No configura contrasena ni modifica RLS.
-- Ejecutar como propietario de dwh con capacidad CREATEROLE y GRANT.
BEGIN;
DO $preflight$
DECLARE r record; role_oid oid; t text;
BEGIN
  IF current_setting('server_version_num')::int / 10000 <> 17 THEN
    RAISE EXCEPTION 'Se requiere PostgreSQL 17';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='dwh' AND nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)) THEN
    RAISE EXCEPTION 'Ejecutar como propietario de dwh';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='wwi_backend_reader') THEN
    CREATE ROLE wwi_backend_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
  -- pg_roles SI expone oid en PostgreSQL 17. La conversion regrole deja
  -- explicita la resolucion del identificador sin leer pg_authid ni contrasenas.
  role_oid := 'wwi_backend_reader'::regrole::oid;
  SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
         rolreplication, rolbypassrls, rolinherit
    INTO STRICT r
    FROM pg_roles WHERE oid=role_oid;
  IF NOT r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls OR r.rolinherit THEN
    RAISE EXCEPTION 'Rol existente incompatible; revisar manualmente';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member=role_oid) THEN
    RAISE EXCEPTION 'El rol tiene membresias inesperadas';
  END IF;
  -- Solo propiedad (o): no rechazar dependencias ACL (a), ACL inicial (i)
  -- ni politicas RLS (r), normales despues de otorgar SELECT y crear politicas.
  -- pg_shdepend es compartido: se rechaza propiedad en cualquier base del
  -- cluster, intencionalmente, para este rol exclusivo sin objetos propios.
  IF EXISTS (SELECT 1 FROM pg_shdepend
             WHERE refclassid='pg_authid'::regclass
               AND refobjid=role_oid AND deptype='o') THEN
    RAISE EXCEPTION 'El rol es propietario de objetos; revisar manualmente';
  END IF;
  IF has_database_privilege(role_oid,current_database(),'CREATE')
     OR EXISTS (SELECT 1 FROM pg_namespace WHERE has_schema_privilege(role_oid,oid,'CREATE')) THEN
    RAISE EXCEPTION 'CREATE efectivo (posiblemente heredado de PUBLIC); revisar sin revocar privilegios globales automaticamente';
  END IF;
  FOREACH t IN ARRAY ARRAY['dim_fecha','dim_cliente','dim_producto','fact_ventas','fact_pedidos'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid=to_regclass('dwh.'||t) AND relkind='r' AND relrowsecurity) THEN
      RAISE EXCEPTION 'Tabla ausente o RLS desactivado: %',t;
    END IF;
    IF has_table_privilege(role_oid,'dwh.'||t,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') THEN
      RAISE EXCEPTION 'Privilegios adicionales inesperados: %',t;
    END IF;
  END LOOP;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO wwi_backend_reader',current_database());
END $preflight$;
GRANT USAGE ON SCHEMA dwh TO wwi_backend_reader;
GRANT SELECT ON TABLE dwh.dim_fecha,dwh.dim_cliente,dwh.dim_producto,dwh.fact_ventas,dwh.fact_pedidos TO wwi_backend_reader;
-- No secuencias: las claves llegan explicitamente desde READY.
-- No privilegios por defecto para tablas futuras, ni acceso para anon/authenticated.
ALTER ROLE wwi_backend_reader SET default_transaction_read_only = on;
COMMIT;
-- RLS puede seguir ocultando todas las filas. No confundir GRANT con visibilidad.
