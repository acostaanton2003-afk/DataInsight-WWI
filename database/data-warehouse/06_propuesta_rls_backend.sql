-- PROPUESTA PENDIENTE DE AUTORIZACION EXPLICITA. NO ejecutar junto al script 05.
-- Permite al rol lector ver TODAS las filas presentes y futuras de estas tablas.
-- Mantiene RLS y no concede BYPASSRLS. Requiere propietario de las tablas.
-- Las politicas RESTRICTIVE existentes siguen aplicandose; revisar pg_policies antes.
BEGIN;
DO $policies$
DECLARE
  t text;
  p record;
  table_oid oid;
  reader_oid oid;
  using_sql text;
BEGIN
  IF current_setting('server_version_num')::int / 10000 <> 17 THEN
    RAISE EXCEPTION 'Se requiere PostgreSQL 17';
  END IF;
  reader_oid := 'wwi_backend_reader'::regrole::oid;
  IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles
             WHERE oid=reader_oid AND (rolsuper OR rolbypassrls)) THEN
    RAISE EXCEPTION 'El rol lector no puede ser superusuario ni tener BYPASSRLS';
  END IF;
  FOREACH t IN ARRAY ARRAY['dim_fecha','dim_cliente','dim_producto','fact_ventas','fact_pedidos'] LOOP
    -- Serializar con cambios DDL de tabla/politicas hasta COMMIT.
    EXECUTE format('LOCK TABLE dwh.%I IN SHARE ROW EXCLUSIVE MODE',t);
    table_oid := to_regclass(format('dwh.%I',t));
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class
                   WHERE oid=table_oid AND relkind='r' AND relrowsecurity) THEN
      RAISE EXCEPTION 'Tabla ausente, incompatible o RLS desactivado: %',t;
    END IF;
    SELECT polcmd, polpermissive, polroles, polqual, polwithcheck
      INTO p FROM pg_catalog.pg_policy
      WHERE polrelid=table_oid AND polname='backend_select';
    IF FOUND THEN
      -- Descompilar el arbol con formato explicito (sin pretty printing).
      -- PG17 representa la constante booleana como true. Se admite tambien
      -- un unico envoltorio (true); no se eliminan parentesis indiscriminadamente.
      -- Lista cerrada: no evaluar SQL existente ni aceptar expresiones que
      -- simplemente resulten verdaderas, NULL, casts o llamadas a funciones.
      using_sql := pg_catalog.pg_get_expr(p.polqual,table_oid,false);
      IF p.polcmd IS DISTINCT FROM 'r'
         OR p.polpermissive IS DISTINCT FROM true
         OR p.polroles IS DISTINCT FROM ARRAY[reader_oid]::oid[]
         OR (using_sql IN ('true','(true)')) IS DISTINCT FROM true
         OR p.polwithcheck IS NOT NULL THEN
        RAISE EXCEPTION 'Politica backend_select incompatible; revision manual requerida: %',t;
      END IF;
    ELSE
      EXECUTE format('CREATE POLICY backend_select ON dwh.%I FOR SELECT TO wwi_backend_reader USING (true)',t);
    END IF;
  END LOOP;
END $policies$;
COMMIT;
