-- SOLO LECTURA. Antes/despues de ejecutar manualmente 03_creacion_tablas_dwh.sql.
-- No ejecutar junto con el DDL si se desea inspeccionar sin crear objetos.
SELECT current_database(), current_user, session_user, version();
SELECT nspname, pg_get_userbyid(nspowner) AS propietario, current_user AS rol_activo,
       nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) AS propietario_exacto,
       has_schema_privilege(current_user,oid,'USAGE') AS usage_rol_activo,
       has_schema_privilege(current_user,oid,'CREATE') AS crear_rol_activo, nspacl
FROM pg_namespace WHERE nspname='dwh';

-- Cinco tablas, RLS activado, sin FORCED RLS sobre el propietario.
SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner) AS propietario,
       c.relrowsecurity,c.relforcerowsecurity
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='dwh' AND c.relkind IN ('r','p','v','m','f') ORDER BY c.relname;

-- Tipos exactos: attidentity debe estar vacio en TODAS las columnas; attgenerated=s solo en las dos calculadas.
SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod) AS tipo,
       a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid) AS expresion
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
WHERE n.nspname='dwh' AND c.relkind='r' ORDER BY c.relname,a.attnum;

SELECT c.relname,k.conname,k.contype,k.convalidated,k.condeferrable,k.condeferred,
       pg_get_constraintdef(k.oid,true) AS definicion
FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='dwh'
ORDER BY c.relname,k.contype,k.conname;

SELECT t.relname AS tabla,i.relname AS indice,x.indisunique,x.indisvalid,
       pg_get_indexdef(i.oid) AS definicion
FROM pg_index x JOIN pg_class t ON t.oid=x.indrelid
JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE n.nspname='dwh' ORDER BY t.relname,i.relname;

-- Deben ser FALSE ambos privilegios efectivos para anon/authenticated.
SELECT r.rolname,has_schema_privilege(r.oid,'dwh','USAGE') AS usage,
       has_schema_privilege(r.oid,'dwh','CREATE') AS crear
FROM pg_roles r WHERE r.rolname IN ('anon','authenticated');

-- Debe ser FALSE acceso de clientes a tablas, incluso por herencia de roles.
SELECT r.rolname,c.relname,
       has_table_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') AS cualquier_permiso,
       has_any_column_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,REFERENCES') AS permiso_en_columnas
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN pg_roles r
WHERE n.nspname='dwh' AND c.relkind='r' AND r.rolname IN ('anon','authenticated')
ORDER BY r.rolname,c.relname;

-- Esperado: CERO secuencias, porque las claves se suministran desde READY.
SELECT c.relname AS secuencia,pg_get_userbyid(c.relowner) AS propietario
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='dwh' AND c.relkind='S';
SELECT r.rolname,c.relname,
       has_sequence_privilege(r.oid,c.oid,'USAGE,SELECT,UPDATE') AS cualquier_permiso
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN pg_roles r
WHERE n.nspname='dwh' AND c.relkind='S' AND r.rolname IN ('anon','authenticated')
ORDER BY r.rolname,c.relname;

-- ACL explicitas, incluido pseudo-rol PUBLIC (OID 0). Buscar grants no previstos.
SELECT n.nspname,c.relname,CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS beneficiario,
       acl.privilege_type,acl.is_grantable
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
CROSS JOIN LATERAL aclexplode(c.relacl) acl
WHERE n.nspname='dwh' AND c.relkind IN ('r','S') ORDER BY c.relname,beneficiario,acl.privilege_type;

-- Columnas: ninguna concesion a clientes/PUBLIC (normalmente cero filas).
SELECT c.relname,a.attname,CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS beneficiario,acl.privilege_type
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL aclexplode(a.attacl) acl
WHERE n.nspname='dwh' ORDER BY c.relname,a.attnum;

-- Defaults globales y por esquema, para TODOS los creadores potenciales.
-- La ejecucion solo corrige defaults por esquema de CURRENT_USER.
SELECT pg_get_userbyid(d.defaclrole) AS creador,
       CASE WHEN d.defaclnamespace=0 THEN '<GLOBAL>' ELSE n.nspname END AS alcance,
       d.defaclobjtype,CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS beneficiario,
       acl.privilege_type
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) acl
WHERE d.defaclnamespace=0 OR n.nspname='dwh'
ORDER BY creador,alcance,d.defaclobjtype,beneficiario;

-- Debe devolver cero politicas; este DDL no ofrece acceso API.
SELECT schemaname,tablename,policyname,roles,cmd FROM pg_policies WHERE schemaname='dwh';

-- Conteos deben ser cero: no se insertaron ni siquiera los desconocidos 0.
-- Ejecutar este SELECT solo DESPUES de que existan las tablas.
SELECT 'dim_fecha' AS tabla,COUNT(*) AS filas FROM dwh.dim_fecha
UNION ALL SELECT 'dim_cliente',COUNT(*) FROM dwh.dim_cliente
UNION ALL SELECT 'dim_producto',COUNT(*) FROM dwh.dim_producto
UNION ALL SELECT 'fact_ventas',COUNT(*) FROM dwh.fact_ventas
UNION ALL SELECT 'fact_pedidos',COUNT(*) FROM dwh.fact_pedidos;

-- Diagnostico opcional, NO prueba suficiente de la configuracion Data API.
-- Un resultado NULL no significa que dwh no este expuesto. Verificar en API settings.
SELECT current_setting('pgrst.db_schemas',true) AS configuracion_visible_en_sesion;
