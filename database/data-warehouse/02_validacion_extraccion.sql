-- Consultas analíticas SQLite sobre la extracción completa, NO sobre el DWH.
-- Ejecutadas por validar_modelo_local.py sobre representaciones efímeras :memory:.
-- No se crean tablas físicas ni se modifican CSV, SQL Server o PostgreSQL.
-- decimal_sum/line_base/monetary_invalid son funciones Decimal del script.

-- name: pk_integridad
SELECT 'orders' AS tabla, COUNT(*) AS filas, COUNT(*)-COUNT(order_id) AS claves_nulas,
       COUNT(order_id)-COUNT(DISTINCT order_id) AS repeticiones FROM src_orders
UNION ALL SELECT 'invoices', COUNT(*),COUNT(*)-COUNT(invoice_id),COUNT(invoice_id)-COUNT(DISTINCT invoice_id) FROM src_invoices
UNION ALL SELECT 'lines', COUNT(*),COUNT(*)-COUNT(invoice_line_id),COUNT(invoice_line_id)-COUNT(DISTINCT invoice_line_id) FROM src_lines
UNION ALL SELECT 'customers', COUNT(*),COUNT(*)-COUNT(customer_id),COUNT(customer_id)-COUNT(DISTINCT customer_id) FROM src_customers
UNION ALL SELECT 'products', COUNT(*),COUNT(*)-COUNT(stock_item_id),COUNT(stock_item_id)-COUNT(DISTINCT stock_item_id) FROM src_products;

-- name: relaciones
SELECT 'InvoiceLines.InvoiceID -> Invoices' AS relacion,
 COUNT(*) AS filas, SUM(l.invoice_id IS NULL) AS nulos,
 SUM(l.invoice_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_invoices p WHERE p.invoice_id=l.invoice_id)) AS huerfanas FROM src_lines l
UNION ALL SELECT 'InvoiceLines.StockItemID -> StockItems',COUNT(*),SUM(l.stock_item_id IS NULL),
 SUM(l.stock_item_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_products p WHERE p.stock_item_id=l.stock_item_id)) FROM src_lines l
UNION ALL SELECT 'Invoices.CustomerID -> Customers',COUNT(*),SUM(i.customer_id IS NULL),
 SUM(i.customer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_customers c WHERE c.customer_id=i.customer_id)) FROM src_invoices i
UNION ALL SELECT 'Invoices.BillToCustomerID -> Customers',COUNT(*),SUM(i.bill_to_customer_id IS NULL),
 SUM(i.bill_to_customer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_customers c WHERE c.customer_id=i.bill_to_customer_id)) FROM src_invoices i
UNION ALL SELECT 'Invoices.OrderID -> Orders (nullable)',COUNT(*),SUM(i.order_id IS NULL),
 SUM(i.order_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_orders o WHERE o.order_id=i.order_id)) FROM src_invoices i
UNION ALL SELECT 'Orders.CustomerID -> Customers',COUNT(*),SUM(o.customer_id IS NULL),
 SUM(o.customer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_customers c WHERE c.customer_id=o.customer_id)) FROM src_orders o
UNION ALL SELECT 'Orders.BackorderOrderID -> Orders (nullable)',COUNT(*),SUM(o.backorder_order_id IS NULL),
 SUM(o.backorder_order_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_orders p WHERE p.order_id=o.backorder_order_id)) FROM src_orders o
UNION ALL SELECT 'Customers.BillToCustomerID -> Customers',COUNT(*),SUM(c.bill_to_customer_id IS NULL),
 SUM(c.bill_to_customer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM src_customers p WHERE p.customer_id=c.bill_to_customer_id)) FROM src_customers c;

-- name: cobertura_cabeceras
SELECT COUNT(*) AS facturas, SUM(is_credit_note=0) AS ordinarias,
 SUM(is_credit_note=1) AS notas_credito, SUM(order_id IS NULL) AS sin_order_id,
 SUM(NOT EXISTS(SELECT 1 FROM src_lines l WHERE l.invoice_id=i.invoice_id)) AS sin_lineas,
 SUM(customer_id<>bill_to_customer_id) AS cliente_distinto_facturacion,
 MIN(invoice_date) AS fecha_min, MAX(invoice_date) AS fecha_max FROM src_invoices i;

-- name: conservacion_grano
SELECT 'lineas_originales' AS etapa, COUNT(*) AS filas, COUNT(DISTINCT invoice_line_id) AS claves FROM src_lines
UNION ALL
SELECT 'enlace_cabecera_cliente_producto',COUNT(*),COUNT(DISTINCT l.invoice_line_id)
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id
JOIN src_customers c ON c.customer_id=i.customer_id
JOIN src_products p ON p.stock_item_id=l.stock_item_id;

-- name: importes_originales
SELECT COUNT(*) AS lineas, SUM(quantity) AS cantidad_facturada, decimal_sum(line_base(quantity,unit_price)) AS ventas_sin_impuestos,
 decimal_sum(tax_amount) AS impuestos, decimal_sum(extended_price) AS ventas_con_impuestos,
 SUM(monetary_invalid(quantity,unit_price,tax_amount,extended_price)) AS diferencias_o_incompletas
FROM src_lines;

-- name: importes_enlazados_todos
SELECT COUNT(*) AS lineas, decimal_sum(line_base(l.quantity,l.unit_price)) AS ventas_sin_impuestos,
 decimal_sum(l.tax_amount) AS impuestos, decimal_sum(l.extended_price) AS ventas_con_impuestos
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id
JOIN src_customers c ON c.customer_id=i.customer_id
JOIN src_products p ON p.stock_item_id=l.stock_item_id;
-- name: ventas_enlazadas
SELECT COUNT(*) AS lineas, COUNT(DISTINCT i.invoice_id) AS facturas,
 decimal_sum(line_base(l.quantity,l.unit_price)) AS ventas_sin_impuestos,
 decimal_sum(l.tax_amount) AS impuestos, decimal_sum(l.extended_price) AS ventas_con_impuestos
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id
JOIN src_customers c ON c.customer_id=i.customer_id
JOIN src_products p ON p.stock_item_id=l.stock_item_id WHERE i.is_credit_note=0;

-- name: top_productos
SELECT l.stock_item_id,l.package_type_id,SUM(l.quantity) AS cantidad
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id WHERE i.is_credit_note=0
GROUP BY l.stock_item_id,l.package_type_id ORDER BY cantidad DESC,l.stock_item_id,l.package_type_id LIMIT 10;

-- name: top_clientes_completo
SELECT i.customer_id,decimal_sum(line_base(l.quantity,l.unit_price)) AS ventas_sin_impuestos
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id WHERE i.is_credit_note=0 GROUP BY i.customer_id;

-- name: meses
SELECT substr(i.invoice_date,1,7) AS mes,COUNT(*) AS lineas,
 decimal_sum(line_base(l.quantity,l.unit_price)) AS ventas_sin_impuestos
FROM src_lines l JOIN src_invoices i ON i.invoice_id=l.invoice_id WHERE i.is_credit_note=0
GROUP BY substr(i.invoice_date,1,7) ORDER BY mes;

-- name: pedidos
SELECT COUNT(*) AS total,
 SUM(EXISTS(SELECT 1 FROM src_invoices i WHERE i.order_id=o.order_id)) AS con_factura,
 SUM(NOT EXISTS(SELECT 1 FROM src_invoices i WHERE i.order_id=o.order_id)) AS sin_factura,
 SUM((SELECT COUNT(*) FROM src_invoices i WHERE i.order_id=o.order_id)>1) AS con_varias_facturas
FROM src_orders o;

-- name: fechas
SELECT COUNT(*) AS facturas_anteriores_al_pedido FROM src_invoices i
JOIN src_orders o ON o.order_id=i.order_id WHERE i.invoice_date<o.order_date;
