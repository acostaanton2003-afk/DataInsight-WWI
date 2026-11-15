-- SOLO LECTURA. Ejecutar primero en SQL Editor administrativo para inspeccion.
SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit
FROM pg_roles WHERE rolname='wwi_backend_reader';
SELECT granted.rolname AS rol_otorgado FROM pg_auth_members m
JOIN pg_roles granted ON granted.oid=m.roleid
JOIN pg_roles member ON member.oid=m.member WHERE member.rolname='wwi_backend_reader';
SELECT has_database_privilege('wwi_backend_reader',current_database(),'CONNECT') AS connect,
       has_database_privilege('wwi_backend_reader',current_database(),'CREATE') AS create_database,
       has_schema_privilege('wwi_backend_reader','dwh','USAGE') AS usage,
       has_schema_privilege('wwi_backend_reader','dwh','CREATE') AS create_schema;
SELECT nspname FROM pg_namespace WHERE has_schema_privilege('wwi_backend_reader',oid,'CREATE');
SELECT c.relname,c.relrowsecurity,pg_get_userbyid(c.relowner) AS owner,
 has_table_privilege('wwi_backend_reader',c.oid,'SELECT') AS can_select,
 has_table_privilege('wwi_backend_reader',c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') AS extra_privileges
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='dwh' AND c.relkind='r';
SELECT * FROM pg_policies WHERE schemaname='dwh' ORDER BY tablename,policyname;
-- Verificacion efectiva: ejecutar las siguientes consultas conectado COMO wwi_backend_reader,
-- no como postgres (el propietario puede eludir RLS). El probe Python exige este rol real.
SELECT current_user,current_database();
SELECT c.relname,row_security_active(c.oid) FROM pg_class c
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='dwh' AND c.relkind='r';
SELECT 'dim_fecha' AS tabla,count(*) FROM dwh.dim_fecha UNION ALL
SELECT 'dim_cliente',count(*) FROM dwh.dim_cliente UNION ALL
SELECT 'dim_producto',count(*) FROM dwh.dim_producto UNION ALL
SELECT 'fact_ventas',count(*) FROM dwh.fact_ventas UNION ALL
SELECT 'fact_pedidos',count(*) FROM dwh.fact_pedidos;
