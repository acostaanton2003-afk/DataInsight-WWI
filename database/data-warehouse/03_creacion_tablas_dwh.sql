-- DataInsight WWI: instalacion inicial en PostgreSQL 17 / Supabase SQL Editor.
-- EJECUCION MANUAL FUTURA. Este archivo NO se ha ejecutado desde el repositorio.
-- Requiere dwh existente y vacio de relaciones, propiedad del rol ejecutor.
-- No crea esquemas, no carga datos, no modifica configuracion de Data API.
-- Las cuatro claves BIGINT llegan de READY: sin IDENTITY, DEFAULT ni secuencias.
-- No se usa CREATE TABLE IF NOT EXISTS: no garantiza compatibilidad de objetos.
-- Una segunda ejecucion se rechaza antes de cambios; no es una migracion repetible.
-- Ejecutar el archivo completo, no partes aisladas. Cualquier error revierte el bloque.
BEGIN;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $preflight$
DECLARE
    schema_oid oid;
    schema_owner oid;
    executor_oid oid;
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 17 THEN
        RAISE EXCEPTION 'Se requiere PostgreSQL 17; version actual: %', version();
    END IF;
    SELECT oid,nspowner INTO schema_oid,schema_owner FROM pg_namespace WHERE nspname = 'dwh';
    SELECT oid INTO executor_oid FROM pg_roles WHERE rolname = current_user;
    IF schema_oid IS NULL THEN
        RAISE EXCEPTION 'El esquema dwh debe existir; no se crea automaticamente';
    END IF;
    -- Politica intencionalmente estricta: el rol activo debe ser el propietario exacto.
    -- USAGE/CREATE o pertenecer al rol propietario no reemplazan esta comprobacion.
    IF schema_owner IS DISTINCT FROM executor_oid
       OR current_user IN ('anon','authenticated') THEN
        RAISE EXCEPTION 'Ejecutar como propietario de dwh (%); current_user=%, session_user=%', pg_get_userbyid(schema_owner),current_user,session_user;
    END IF;
    IF (SELECT COUNT(*) FROM pg_roles WHERE rolname IN ('anon','authenticated')) <> 2 THEN
        RAISE EXCEPTION 'No se encontraron los roles Supabase anon y authenticated';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='dwh' AND c.relkind IN ('r','p','v','m','f','S')
    ) THEN
        RAISE EXCEPTION 'dwh contiene relaciones existentes: inspeccionar con 04_verificacion_dwh.sql; no se omiten ni alteran';
    END IF;
    -- Un REVOKE por esquema no puede neutralizar un GRANT por defecto GLOBAL.
    -- Bloquear, no cambiar defaults globales que afectarian otros esquemas.
    IF EXISTS (
        SELECT 1 FROM pg_default_acl d
        CROSS JOIN LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclrole=(SELECT oid FROM pg_roles WHERE rolname=current_user)
          AND d.defaclnamespace=0 AND d.defaclobjtype IN ('r','S')
          AND (a.grantee=0 OR a.grantee IN (SELECT oid FROM pg_roles WHERE rolname IN ('anon','authenticated')))
    ) THEN
        RAISE EXCEPTION 'Defaults GLOBALES conceden tablas/secuencias a PUBLIC/anon/authenticated; revisar su alcance antes de continuar';
    END IF;
END
$preflight$;

-- Solo roles de clientes API; no se revoca al propietario ni a administradores.
REVOKE ALL ON SCHEMA dwh FROM PUBLIC, anon, authenticated;
-- Aplican a objetos FUTUROS creados por CURRENT_USER, solo dentro de dwh.
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
-- Defensa para eventuales secuencias futuras; esta instalacion no crea ninguna.
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;

CREATE TABLE dwh.dim_fecha (
    fecha_key integer PRIMARY KEY,
    fecha date UNIQUE,
    anio smallint,
    mes smallint,
    trimestre smallint,
    dia smallint,
    CONSTRAINT fecha_conocida_o_desconocida CHECK (
        (fecha_key = 0 AND fecha IS NULL AND anio IS NULL AND mes IS NULL AND trimestre IS NULL AND dia IS NULL)
        OR
        (fecha_key > 0 AND fecha IS NOT NULL AND anio IS NOT NULL AND mes IS NOT NULL AND trimestre IS NOT NULL AND dia IS NOT NULL
         AND fecha_key = EXTRACT(YEAR FROM fecha)::integer * 10000 + EXTRACT(MONTH FROM fecha)::integer * 100 + EXTRACT(DAY FROM fecha)::integer
         AND anio = EXTRACT(YEAR FROM fecha) AND mes = EXTRACT(MONTH FROM fecha)
         AND trimestre = EXTRACT(QUARTER FROM fecha) AND dia = EXTRACT(DAY FROM fecha))
    )
);

-- SCD tipo 1: una fila actual por CustomerID, no reconstruccion historica.
CREATE TABLE dwh.dim_cliente (
    cliente_key bigint PRIMARY KEY,
    customer_id integer UNIQUE,
    customer_name text NOT NULL,
    bill_to_customer_id_actual integer,
    customer_category_id integer,
    buying_group_id integer,
    account_opened_date date,
    payment_days integer,
    is_on_credit_hold boolean,
    delivery_postal_code text,
    raw_run_id text,
    CONSTRAINT cliente_desconocido CHECK (
        (cliente_key = 0 AND customer_id IS NULL)
        OR (cliente_key > 0 AND customer_id IS NOT NULL)
    )
);

-- Solo atributos disponibles en Warehouse.StockItems, sin nombres de catalogos.
CREATE TABLE dwh.dim_producto (
    producto_key bigint PRIMARY KEY,
    stock_item_id integer UNIQUE,
    stock_item_name text NOT NULL,
    brand text,
    size text,
    barcode text,
    supplier_id integer,
    color_id integer,
    unit_package_id integer,
    outer_package_id integer,
    quantity_per_outer integer,
    is_chiller_stock boolean,
    raw_run_id text,
    CONSTRAINT producto_desconocido CHECK (
        (producto_key = 0 AND stock_item_id IS NULL)
        OR (producto_key > 0 AND stock_item_id IS NOT NULL)
    )
);

-- GRANO: exactamente una fila por Sales.InvoiceLines.InvoiceLineID.
-- No deduplicar por InvoiceID+StockItemID, que no identifica una linea.
CREATE TABLE dwh.fact_ventas (
    venta_key bigint PRIMARY KEY,
    invoice_line_id integer NOT NULL UNIQUE,
    fecha_factura_key integer NOT NULL REFERENCES dwh.dim_fecha(fecha_key),
    cliente_key bigint NOT NULL REFERENCES dwh.dim_cliente(cliente_key),
    producto_key bigint NOT NULL REFERENCES dwh.dim_producto(producto_key),
    invoice_id integer NOT NULL,              -- identificador degenerado, no UNIQUE
    order_id integer,                        -- identificador degenerado, nullable
    bill_to_customer_id_factura integer NOT NULL, -- trazabilidad del rol alternativo
    package_type_id integer NOT NULL,         -- presentacion de la linea, no la actual del maestro
    is_credit_note boolean NOT NULL,
    quantity integer NOT NULL,
    unit_price numeric(18,2) NOT NULL,         -- NULL de fuente debe quedar en cuarentena
    tax_rate numeric(18,3) NOT NULL,
    tax_amount numeric(18,2) NOT NULL,
    extended_price numeric(18,2) NOT NULL,
    ventas_sin_impuestos numeric(28,2) GENERATED ALWAYS AS
        (quantity::numeric * unit_price) STORED,
    raw_run_id text NOT NULL
    -- No CHECK de signo ni tasas; no se han aprobado esas politicas.
    -- No fijar 228265 ni totales de la muestra como restricciones de tabla.
    -- ABS(extended_price - (ventas_sin_impuestos + tax_amount)) <= 0.01
    -- es control de calidad PROVISIONAL, no restriccion permanente aprobada.
);

-- Proceso separado. GRANO: una fila por OrderID en el estado de extraccion.
-- No apilar ejecuciones como si fueran pedidos nuevos. No contiene ventas.
CREATE TABLE dwh.fact_pedidos (
    pedido_key bigint PRIMARY KEY,
    order_id integer NOT NULL UNIQUE,
    fecha_pedido_key integer NOT NULL REFERENCES dwh.dim_fecha(fecha_key),
    fecha_entrega_prevista_key integer NOT NULL REFERENCES dwh.dim_fecha(fecha_key),
    cliente_key bigint NOT NULL REFERENCES dwh.dim_cliente(cliente_key),
    backorder_order_id integer,
    cantidad_facturas bigint NOT NULL CHECK (cantidad_facturas >= 0),
    tiene_factura boolean GENERATED ALWAYS AS (cantidad_facturas > 0) STORED,
    raw_run_id text NOT NULL
);


-- Indices de acceso: FK de hechos y agrupaciones frecuentes; PK/UNIQUE ya indexan.
CREATE INDEX ix_fact_ventas_fecha ON dwh.fact_ventas (fecha_factura_key);
CREATE INDEX ix_fact_ventas_cliente ON dwh.fact_ventas (cliente_key);
CREATE INDEX ix_fact_ventas_producto_paquete ON dwh.fact_ventas (producto_key, package_type_id);
CREATE INDEX ix_fact_ventas_invoice ON dwh.fact_ventas (invoice_id);
CREATE INDEX ix_fact_ventas_order ON dwh.fact_ventas (order_id);
CREATE INDEX ix_fact_pedidos_fecha ON dwh.fact_pedidos (fecha_pedido_key);
CREATE INDEX ix_fact_pedidos_entrega ON dwh.fact_pedidos (fecha_entrega_prevista_key);
CREATE INDEX ix_fact_pedidos_cliente ON dwh.fact_pedidos (cliente_key);

-- Defensa adicional: RLS sin politicas de cliente. Propietario conserva administracion.
ALTER TABLE dwh.dim_fecha ENABLE ROW LEVEL SECURITY;
ALTER TABLE dwh.dim_cliente ENABLE ROW LEVEL SECURITY;
ALTER TABLE dwh.dim_producto ENABLE ROW LEVEL SECURITY;
ALTER TABLE dwh.fact_ventas ENABLE ROW LEVEL SECURITY;
ALTER TABLE dwh.fact_pedidos ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON ALL TABLES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;

-- No se insertan miembros desconocidos ni CSV: los tres miembros 0 vendran de READY.
-- No DEFAULT 0 en FK. No FK de hecho a hecho. No dimensiones factura/pedido.
DO $permissions$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles r WHERE r.rolname IN ('anon','authenticated')
          AND has_schema_privilege(r.oid,'dwh','USAGE,CREATE')
    ) THEN
        RAISE EXCEPTION 'Permisos efectivos de cliente sobre dwh; revisar pertenencias de roles';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_roles r
        WHERE n.nspname='dwh' AND c.relkind='r' AND r.rolname IN ('anon','authenticated')
          AND (has_table_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
               OR has_any_column_privilege(r.oid,c.oid,'SELECT,INSERT,UPDATE,REFERENCES'))
    ) THEN
        RAISE EXCEPTION 'Permisos efectivos de cliente en tablas dwh; revisar grants heredados';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN pg_roles r
        WHERE n.nspname='dwh' AND c.relkind='S' AND r.rolname IN ('anon','authenticated')
          AND has_sequence_privilege(r.oid,c.oid,'USAGE,SELECT,UPDATE')
    ) THEN
        RAISE EXCEPTION 'Permisos efectivos de cliente en secuencias dwh';
    END IF;
END
$permissions$;
COMMIT;
-- Verificacion posterior de solo lectura en 04_verificacion_dwh.sql (archivo separado).
