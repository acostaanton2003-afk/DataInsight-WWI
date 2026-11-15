/*
DataInsight WWI - Validación propuesta de KPI y calidad.
Estado de todos los resultados nuevos: PENDIENTE DE EJECUCIÓN EN SSMS.
Seleccionar WideWorldImporters en SSMS. Ejecutar sección 0 primero.
Confirmar las columnas y tipos antes de ejecutar las otras secciones.
Solo lectura. Cada CTE forma parte de su SELECT y debe ejecutarse completa.
Sin filtro temporal: se examina toda la fuente visible.
KPI monetarios provisionales: IsCreditNote = 0, sin convertir signos ni nulos.
SUM omite NULL: validar sección 1 antes de interpretar totales.
*/

-- 0. Contexto y columnas requeridas. Una fila por columna esperada.
-- Un tipo NULL puede indicar columna ausente o metadatos no visibles por permisos.
SELECT DB_NAME() AS base_de_datos, SYSDATETIMEOFFSET() AS momento_servidor;

SELECT e.esquema, e.tabla, e.columna,
    CASE WHEN c.column_id IS NULL THEN N'REVISAR' ELSE N'VISIBLE' END AS estado,
    ty.name AS tipo, c.precision, c.scale, c.is_nullable,
    CONVERT(nvarchar(4000), ep.value) AS descripcion
FROM (VALUES
    (N'Sales', N'Orders', N'OrderID'),
    (N'Sales', N'Orders', N'CustomerID'),
    (N'Sales', N'Orders', N'OrderDate'),
    (N'Sales', N'OrderLines', N'OrderLineID'),
    (N'Sales', N'OrderLines', N'OrderID'),
    (N'Sales', N'OrderLines', N'StockItemID'),
    (N'Sales', N'OrderLines', N'Quantity'),
    (N'Sales', N'OrderLines', N'UnitPrice'),
    (N'Sales', N'Invoices', N'InvoiceID'),
    (N'Sales', N'Invoices', N'OrderID'),
    (N'Sales', N'Invoices', N'CustomerID'),
    (N'Sales', N'Invoices', N'BillToCustomerID'),
    (N'Sales', N'Invoices', N'InvoiceDate'),
    (N'Sales', N'Invoices', N'IsCreditNote'),
    (N'Sales', N'InvoiceLines', N'InvoiceLineID'),
    (N'Sales', N'InvoiceLines', N'InvoiceID'),
    (N'Sales', N'InvoiceLines', N'StockItemID'),
    (N'Sales', N'InvoiceLines', N'PackageTypeID'),
    (N'Sales', N'InvoiceLines', N'Quantity'),
    (N'Sales', N'InvoiceLines', N'UnitPrice'),
    (N'Sales', N'InvoiceLines', N'TaxAmount'),
    (N'Sales', N'InvoiceLines', N'TaxRate'),
    (N'Sales', N'InvoiceLines', N'ExtendedPrice'),
    (N'Sales', N'Customers', N'CustomerID'),
    (N'Sales', N'Customers', N'CustomerName'),
    (N'Warehouse', N'StockItems', N'StockItemID'),
    (N'Warehouse', N'StockItems', N'StockItemName')
) AS e(esquema, tabla, columna)
LEFT JOIN sys.schemas AS s ON s.name = e.esquema
LEFT JOIN sys.tables AS t ON t.schema_id = s.schema_id AND t.name = e.tabla
LEFT JOIN sys.columns AS c ON c.object_id = t.object_id AND c.name = e.columna
LEFT JOIN sys.types AS ty ON ty.user_type_id = c.user_type_id
LEFT JOIN sys.extended_properties AS ep
    ON ep.class = 1 AND ep.major_id = c.object_id
    AND ep.minor_id = c.column_id AND ep.name = N'Description'
ORDER BY e.esquema, e.tabla, e.columna;

-- 1. Nulos y duplicados de las seis claves candidatas.
SELECT N'Orders' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(OrderID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(CustomerID) AS cliente_nulo,
    COUNT_BIG(*) - COUNT_BIG(OrderDate) AS fecha_nula
FROM Sales.Orders;

SELECT N'Invoices' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(InvoiceID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(OrderID) AS pedido_nulo,
    COUNT_BIG(*) - COUNT_BIG(CustomerID) AS cliente_nulo,
    COUNT_BIG(*) - COUNT_BIG(BillToCustomerID) AS cliente_facturacion_nulo,
    COUNT_BIG(*) - COUNT_BIG(InvoiceDate) AS fecha_nula,
    COUNT_BIG(*) - COUNT_BIG(IsCreditNote) AS indicador_credito_nulo
FROM Sales.Invoices;

SELECT N'OrderLines' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(OrderLineID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(OrderID) AS pedido_nulo,
    COUNT_BIG(*) - COUNT_BIG(StockItemID) AS articulo_nulo,
    COUNT_BIG(*) - COUNT_BIG(Quantity) AS cantidad_nula,
    COUNT_BIG(*) - COUNT_BIG(UnitPrice) AS precio_nulo
FROM Sales.OrderLines;

SELECT N'InvoiceLines' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(InvoiceLineID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(InvoiceID) AS factura_nula,
    COUNT_BIG(*) - COUNT_BIG(StockItemID) AS articulo_nulo,
    COUNT_BIG(*) - COUNT_BIG(PackageTypeID) AS presentacion_nula,
    COUNT_BIG(*) - COUNT_BIG(Quantity) AS cantidad_nula,
    COUNT_BIG(*) - COUNT_BIG(UnitPrice) AS precio_nulo,
    COUNT_BIG(*) - COUNT_BIG(TaxAmount) AS impuesto_nulo,
    COUNT_BIG(*) - COUNT_BIG(TaxRate) AS tasa_nula,
    COUNT_BIG(*) - COUNT_BIG(ExtendedPrice) AS importe_extendido_nulo
FROM Sales.InvoiceLines;

SELECT N'Customers' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(CustomerID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(CustomerName) AS nombre_nulo
FROM Sales.Customers;

SELECT N'StockItems' AS tabla, COUNT_BIG(*) AS filas,
    COUNT_BIG(*) - COUNT_BIG(StockItemID) AS id_nulo,
    COUNT_BIG(*) - COUNT_BIG(StockItemName) AS nombre_nulo
FROM Warehouse.StockItems;

-- Salida vacía significa que no se encontraron grupos duplicados en esta consulta.
SELECT N'Orders.OrderID' AS clave, OrderID AS valor, COUNT_BIG(*) AS repeticiones
FROM Sales.Orders GROUP BY OrderID HAVING COUNT_BIG(*) > 1
UNION ALL
SELECT N'OrderLines.OrderLineID', OrderLineID, COUNT_BIG(*)
FROM Sales.OrderLines GROUP BY OrderLineID HAVING COUNT_BIG(*) > 1
UNION ALL
SELECT N'Invoices.InvoiceID', InvoiceID, COUNT_BIG(*)
FROM Sales.Invoices GROUP BY InvoiceID HAVING COUNT_BIG(*) > 1
UNION ALL
SELECT N'InvoiceLines.InvoiceLineID', InvoiceLineID, COUNT_BIG(*)
FROM Sales.InvoiceLines GROUP BY InvoiceLineID HAVING COUNT_BIG(*) > 1
UNION ALL
SELECT N'Customers.CustomerID', CustomerID, COUNT_BIG(*)
FROM Sales.Customers GROUP BY CustomerID HAVING COUNT_BIG(*) > 1
UNION ALL
SELECT N'StockItems.StockItemID', StockItemID, COUNT_BIG(*)
FROM Warehouse.StockItems GROUP BY StockItemID HAVING COUNT_BIG(*) > 1;

-- 2. Referencias no nulas sin padre. No se confunden con NULL permitidos.
SELECT N'OrderLines -> Orders' AS relacion, COUNT_BIG(*) AS referencias_sin_padre
FROM Sales.OrderLines AS l WHERE l.OrderID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Orders AS o WHERE o.OrderID = l.OrderID)
UNION ALL
SELECT N'InvoiceLines -> Invoices', COUNT_BIG(*)
FROM Sales.InvoiceLines AS l WHERE l.InvoiceID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Invoices AS i WHERE i.InvoiceID = l.InvoiceID)
UNION ALL
SELECT N'Invoices -> Orders', COUNT_BIG(*)
FROM Sales.Invoices AS i WHERE i.OrderID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Orders AS o WHERE o.OrderID = i.OrderID)
UNION ALL
SELECT N'Orders -> Customers', COUNT_BIG(*)
FROM Sales.Orders AS o WHERE o.CustomerID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Customers AS c WHERE c.CustomerID = o.CustomerID)
UNION ALL
SELECT N'Invoices.CustomerID -> Customers', COUNT_BIG(*)
FROM Sales.Invoices AS i WHERE i.CustomerID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Customers AS c WHERE c.CustomerID = i.CustomerID)
UNION ALL
SELECT N'Invoices.BillToCustomerID -> Customers', COUNT_BIG(*)
FROM Sales.Invoices AS i WHERE i.BillToCustomerID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Sales.Customers AS c WHERE c.CustomerID = i.BillToCustomerID)
UNION ALL
SELECT N'OrderLines -> StockItems', COUNT_BIG(*)
FROM Sales.OrderLines AS l WHERE l.StockItemID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Warehouse.StockItems AS s WHERE s.StockItemID = l.StockItemID)
UNION ALL
SELECT N'InvoiceLines -> StockItems', COUNT_BIG(*)
FROM Sales.InvoiceLines AS l WHERE l.StockItemID IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM Warehouse.StockItems AS s WHERE s.StockItemID = l.StockItemID);

SELECT N'Pedidos sin lineas' AS control, COUNT_BIG(*) AS cabeceras
FROM Sales.Orders AS o
WHERE NOT EXISTS (SELECT 1 FROM Sales.OrderLines AS l WHERE l.OrderID = o.OrderID)
UNION ALL
SELECT N'Facturas sin lineas', COUNT_BIG(*)
FROM Sales.Invoices AS i
WHERE NOT EXISTS (SELECT 1 FROM Sales.InvoiceLines AS l WHERE l.InvoiceID = i.InvoiceID);

-- 3. Notas de crédito, cantidades, precios y signos. No se aplica corrección.
-- Conteo de cabeceras separado del de líneas para evitar multiplicaciones.
SELECT IsCreditNote, COUNT_BIG(*) AS documentos,
    MIN(InvoiceDate) AS primera_fecha, MAX(InvoiceDate) AS ultima_fecha
FROM Sales.Invoices
GROUP BY IsCreditNote;

SELECT i.IsCreditNote,
    CASE WHEN i.InvoiceID IS NULL THEN N'Sin cabecera' ELSE N'Con cabecera' END AS vinculo,
    COUNT_BIG(*) AS lineas,
    COUNT_BIG(CASE WHEN l.Quantity < 0 THEN 1 END) AS cantidad_negativa,
    COUNT_BIG(CASE WHEN l.Quantity = 0 THEN 1 END) AS cantidad_cero,
    COUNT_BIG(CASE WHEN l.UnitPrice < 0 THEN 1 END) AS precio_negativo,
    COUNT_BIG(CASE WHEN l.UnitPrice = 0 THEN 1 END) AS precio_cero,
    COUNT_BIG(CASE WHEN l.TaxAmount < 0 THEN 1 END) AS impuesto_negativo,
    COUNT_BIG(CASE WHEN l.TaxAmount = 0 THEN 1 END) AS impuesto_cero,
    COUNT_BIG(CASE WHEN l.ExtendedPrice < 0 THEN 1 END) AS extendido_negativo,
    COUNT_BIG(CASE WHEN l.ExtendedPrice = 0 THEN 1 END) AS extendido_cero,
    MIN(l.UnitPrice) AS precio_minimo, MAX(l.UnitPrice) AS precio_maximo,
    SUM(CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4))) AS base_candidata,
    SUM(CAST(l.TaxAmount AS decimal(28,4))) AS impuesto_registrado,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4))) AS extendido_registrado
FROM Sales.InvoiceLines AS l
LEFT JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
GROUP BY i.IsCreditNote,
    CASE WHEN i.InvoiceID IS NULL THEN N'Sin cabecera' ELSE N'Con cabecera' END;

-- Distribución conjunta para investigar signos sin ocultarlos en una suma neta.
SELECT i.IsCreditNote,
    SIGN(l.Quantity) AS signo_cantidad, SIGN(l.UnitPrice) AS signo_precio,
    SIGN(l.TaxAmount) AS signo_impuesto, SIGN(l.ExtendedPrice) AS signo_extendido,
    COUNT_BIG(*) AS lineas
FROM Sales.InvoiceLines AS l
LEFT JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
GROUP BY i.IsCreditNote, SIGN(l.Quantity), SIGN(l.UnitPrice),
    SIGN(l.TaxAmount), SIGN(l.ExtendedPrice);

SELECT COUNT_BIG(*) AS lineas_pedido,
    COUNT_BIG(CASE WHEN Quantity < 0 THEN 1 END) AS cantidad_negativa,
    COUNT_BIG(CASE WHEN Quantity = 0 THEN 1 END) AS cantidad_cero,
    COUNT_BIG(CASE WHEN UnitPrice < 0 THEN 1 END) AS precio_negativo,
    COUNT_BIG(CASE WHEN UnitPrice = 0 THEN 1 END) AS precio_cero,
    MIN(UnitPrice) AS precio_minimo, MAX(UnitPrice) AS precio_maximo
FROM Sales.OrderLines;

-- Muestra de créditos. Cero filas es un resultado posible, pendiente de ejecución.
SELECT TOP (50) i.InvoiceID, i.OrderID, i.InvoiceDate, i.IsCreditNote,
    l.InvoiceLineID, l.StockItemID, l.Quantity, l.UnitPrice, l.TaxRate,
    l.TaxAmount, l.ExtendedPrice
FROM Sales.Invoices AS i
LEFT JOIN Sales.InvoiceLines AS l ON l.InvoiceID = i.InvoiceID
WHERE i.IsCreditNote = 1
ORDER BY i.InvoiceID, l.InvoiceLineID;

-- 4. Hipótesis monetarias. Comparaciones por línea, sin invertir signos.
-- Tolerancia exploratoria 0.01, pendiente de aprobación según moneda y precisión.
-- Solo líneas completas entran en cada comparación monetaria principal.
;WITH calculos AS (
    SELECT l.*, i.IsCreditNote,
        CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4)) AS base_candidata
    FROM Sales.InvoiceLines AS l
    LEFT JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
), diferencias AS (
    SELECT *,
        CAST(ExtendedPrice AS decimal(32,4)) - base_candidata AS diferencia_sin_impuesto,
        CAST(ExtendedPrice AS decimal(32,4)) - base_candidata - TaxAmount AS diferencia_con_impuesto,
        TaxAmount - ROUND(base_candidata * TaxRate / 100.0, 2) AS diferencia_impuesto
    FROM calculos
)
SELECT IsCreditNote, COUNT_BIG(*) AS lineas,
    COUNT_BIG(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL THEN 1 END) AS lineas_completas,
    COUNT_BIG(CASE WHEN Quantity IS NULL OR UnitPrice IS NULL
        OR TaxAmount IS NULL OR ExtendedPrice IS NULL THEN 1 END) AS lineas_incompletas,
    COUNT_BIG(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL
        AND diferencia_sin_impuesto <> 0 THEN 1 END) AS dif_base_exacta,
    COUNT_BIG(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL
        AND ABS(diferencia_sin_impuesto) > 0.01 THEN 1 END) AS dif_base_mayor_tolerancia,
    COUNT_BIG(CASE WHEN diferencia_con_impuesto <> 0 THEN 1 END) AS dif_base_mas_impuesto_exacta,
    COUNT_BIG(CASE WHEN ABS(diferencia_con_impuesto) > 0.01 THEN 1 END) AS dif_base_mas_impuesto_mayor_tolerancia,
    COUNT_BIG(diferencia_impuesto) AS lineas_comparables_impuesto,
    COUNT_BIG(CASE WHEN diferencia_impuesto <> 0 THEN 1 END) AS dif_impuesto_exacta,
    COUNT_BIG(CASE WHEN ABS(diferencia_impuesto) > 0.01 THEN 1 END) AS dif_impuesto_mayor_tolerancia,
    SUM(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL THEN base_candidata END) AS base_completa,
    SUM(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL THEN ExtendedPrice - TaxAmount END) AS base_alternativa_completa,
    SUM(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL THEN base_candidata + TaxAmount END) AS total_reconstruido_completo,
    SUM(CASE WHEN Quantity IS NOT NULL AND UnitPrice IS NOT NULL
        AND TaxAmount IS NOT NULL AND ExtendedPrice IS NOT NULL THEN ExtendedPrice END) AS total_extendido_completo
FROM diferencias
GROUP BY IsCreditNote;

-- Muestra de diferencias o datos incompletos. Se vuelve a definir la CTE.
;WITH calculos AS (
    SELECT l.*, i.IsCreditNote,
        CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4)) AS base_candidata
    FROM Sales.InvoiceLines AS l
    LEFT JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
)
SELECT TOP (50) InvoiceLineID, InvoiceID, IsCreditNote,
    Quantity, UnitPrice, TaxRate, TaxAmount, ExtendedPrice, base_candidata,
    ExtendedPrice - base_candidata AS diferencia_sin_impuesto,
    ExtendedPrice - base_candidata - TaxAmount AS diferencia_con_impuesto,
    TaxAmount - ROUND(base_candidata * TaxRate / 100.0, 2) AS diferencia_impuesto
FROM calculos
WHERE Quantity IS NULL OR UnitPrice IS NULL OR TaxAmount IS NULL
    OR TaxRate IS NULL OR ExtendedPrice IS NULL
    OR ABS(ExtendedPrice - base_candidata) > 0.01
    OR ABS(ExtendedPrice - base_candidata - TaxAmount) > 0.01
    OR ABS(TaxAmount - ROUND(base_candidata * TaxRate / 100.0, 2)) > 0.01
ORDER BY InvoiceLineID;

-- 5. Fechas. GETDATE utiliza el reloj del servidor SQL, que debe revisarse.
SELECT N'Orders' AS tabla, MIN(OrderDate) AS primera_fecha, MAX(OrderDate) AS ultima_fecha,
    COUNT_BIG(*) - COUNT_BIG(OrderDate) AS fechas_nulas,
    COUNT_BIG(CASE WHEN OrderDate > CAST(GETDATE() AS date) THEN 1 END) AS fechas_futuras
FROM Sales.Orders
UNION ALL
SELECT N'Invoices', MIN(InvoiceDate), MAX(InvoiceDate),
    COUNT_BIG(*) - COUNT_BIG(InvoiceDate),
    COUNT_BIG(CASE WHEN InvoiceDate > CAST(GETDATE() AS date) THEN 1 END)
FROM Sales.Invoices;

SELECT COUNT_BIG(*) AS facturas_con_fecha_anterior_al_pedido
FROM Sales.Invoices AS i
INNER JOIN Sales.Orders AS o ON o.OrderID = i.OrderID
WHERE i.InvoiceDate < o.OrderDate;

SELECT TOP (50) i.InvoiceID, i.OrderID, o.OrderDate, i.InvoiceDate, i.IsCreditNote
FROM Sales.Invoices AS i
INNER JOIN Sales.Orders AS o ON o.OrderID = i.OrderID
WHERE i.InvoiceDate < o.OrderDate
ORDER BY i.InvoiceID;

-- 6. KPI candidatos. Toda la historia, filtro provisional de créditos.
-- 6.1 Ventas totales. Las sumas pueden ser parciales si existen NULL.
SELECT COUNT_BIG(*) AS lineas,
    SUM(CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4))) AS base_por_cantidad_precio,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4)) - l.TaxAmount) AS base_por_extendido_menos_impuesto,
    SUM(CAST(l.TaxAmount AS decimal(28,4))) AS impuestos,
    SUM(CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4)) + l.TaxAmount) AS total_reconstruido_con_impuestos,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4))) AS total_extendido_por_validar
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
WHERE i.IsCreditNote = 0;

-- 6.2 Facturas emitidas. El desglose incluye todos los valores del indicador.
SELECT IsCreditNote, COUNT_BIG(*) AS documentos
FROM Sales.Invoices GROUP BY IsCreditNote;

SELECT COUNT_BIG(*) AS facturas_emitidas_candidatas
FROM Sales.Invoices WHERE IsCreditNote = 0;

-- 6.3 Productos más vendidos. No combinar presentaciones sin conversión validada.
-- TOP 10 es una muestra. Orden estable por identificadores para los empates.
SELECT TOP (10) l.StockItemID, s.StockItemName, l.PackageTypeID,
    SUM(CAST(l.Quantity AS bigint)) AS cantidad_facturada
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
LEFT JOIN Warehouse.StockItems AS s ON s.StockItemID = l.StockItemID
WHERE i.IsCreditNote = 0
GROUP BY l.StockItemID, s.StockItemName, l.PackageTypeID
ORDER BY cantidad_facturada DESC, l.StockItemID, l.PackageTypeID;

-- 6.4 Ventas por cliente comercial, pendiente elegir CustomerID o BillToCustomerID.
SELECT i.CustomerID, c.CustomerName, COUNT_BIG(*) AS lineas,
    SUM(CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4))) AS base_por_cantidad_precio,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4)) - l.TaxAmount) AS base_alternativa,
    SUM(CAST(l.TaxAmount AS decimal(28,4))) AS impuestos,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4))) AS total_extendido_por_validar
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
LEFT JOIN Sales.Customers AS c ON c.CustomerID = i.CustomerID
WHERE i.IsCreditNote = 0
GROUP BY i.CustomerID, c.CustomerName
ORDER BY i.CustomerID;

-- 6.5 Ventas mensuales. No rellena meses ausentes. NULL queda en grupo propio.
SELECT YEAR(i.InvoiceDate) AS anio, MONTH(i.InvoiceDate) AS mes,
    COUNT_BIG(*) AS lineas,
    SUM(CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4))) AS base_por_cantidad_precio,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4)) - l.TaxAmount) AS base_alternativa,
    SUM(CAST(l.TaxAmount AS decimal(28,4))) AS impuestos,
    SUM(CAST(l.ExtendedPrice AS decimal(28,4))) AS total_extendido_por_validar
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
WHERE i.IsCreditNote = 0
GROUP BY YEAR(i.InvoiceDate), MONTH(i.InvoiceDate)
ORDER BY anio, mes;

-- 6.6 Pedidos sin factura. Misma cohorte para numerador y denominador.
-- Se considera cualquier cabecera vinculada, preservando el criterio anterior.
;WITH pedidos AS (
    SELECT o.OrderID,
        CASE WHEN EXISTS (SELECT 1 FROM Sales.Invoices AS i WHERE i.OrderID = o.OrderID)
            THEN 0 ELSE 1 END AS sin_factura
    FROM Sales.Orders AS o
)
SELECT COUNT_BIG(*) AS total_pedidos,
    COUNT_BIG(CASE WHEN sin_factura = 1 THEN 1 END) AS pedidos_sin_factura,
    COUNT_BIG(CASE WHEN sin_factura = 0 THEN 1 END) AS pedidos_con_factura,
    100.0 * COUNT_BIG(CASE WHEN sin_factura = 1 THEN 1 END)
        / NULLIF(COUNT_BIG(*), 0) AS porcentaje_sin_factura,
    100.0 * COUNT_BIG(CASE WHEN sin_factura = 0 THEN 1 END)
        / NULLIF(COUNT_BIG(*), 0) AS porcentaje_con_factura
FROM pedidos;

SELECT TOP (50) o.OrderID, o.OrderDate, o.CustomerID
FROM Sales.Orders AS o
WHERE NOT EXISTS (SELECT 1 FROM Sales.Invoices AS i WHERE i.OrderID = o.OrderID)
ORDER BY o.OrderDate, o.OrderID;

-- 7. Conciliación. Misma población y signos almacenados.
-- Comparar filas y sumas entre etapas. Cambios revelan pérdida o multiplicación.
-- Los LEFT JOIN a maestros conservan referencias sin coincidencia.
;WITH por_factura AS (
    SELECT InvoiceID, COUNT_BIG(*) AS lineas,
        SUM(CAST(ExtendedPrice AS decimal(28,4))) AS extendido
    FROM Sales.InvoiceLines GROUP BY InvoiceID
)
SELECT N'Lineas originales' AS etapa, COUNT_BIG(*) AS lineas,
    SUM(CAST(ExtendedPrice AS decimal(28,4))) AS extendido
FROM Sales.InvoiceLines
UNION ALL
SELECT N'Agregadas por InvoiceID', SUM(lineas), SUM(extendido) FROM por_factura
UNION ALL
SELECT N'Enlace a cabeceras', COUNT_BIG(*), SUM(CAST(l.ExtendedPrice AS decimal(28,4)))
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
UNION ALL
SELECT N'Enlace a cabeceras y clientes', COUNT_BIG(*), SUM(CAST(l.ExtendedPrice AS decimal(28,4)))
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
LEFT JOIN Sales.Customers AS c ON c.CustomerID = i.CustomerID
UNION ALL
SELECT N'Enlace a cabeceras y articulos', COUNT_BIG(*), SUM(CAST(l.ExtendedPrice AS decimal(28,4)))
FROM Sales.InvoiceLines AS l
INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
LEFT JOIN Warehouse.StockItems AS s ON s.StockItemID = l.StockItemID;

-- Conciliación del escenario IsCreditNote = 0 con los KPI por cliente y mes.
-- Comparar cada fila con Total candidato para todas las medidas.
;WITH base AS (
    SELECT i.CustomerID, i.InvoiceDate,
        CAST(l.Quantity AS decimal(12,0)) * CAST(l.UnitPrice AS decimal(19,4)) AS importe_base,
        CAST(l.ExtendedPrice AS decimal(28,4)) - l.TaxAmount AS base_alternativa,
        CAST(l.TaxAmount AS decimal(28,4)) AS impuesto,
        CAST(l.ExtendedPrice AS decimal(28,4)) AS extendido
    FROM Sales.InvoiceLines AS l
    INNER JOIN Sales.Invoices AS i ON i.InvoiceID = l.InvoiceID
    WHERE i.IsCreditNote = 0
), por_cliente AS (
    SELECT b.CustomerID, c.CustomerName, COUNT_BIG(*) AS lineas,
        SUM(b.importe_base) AS importe_base, SUM(b.base_alternativa) AS base_alternativa,
        SUM(b.impuesto) AS impuesto, SUM(b.extendido) AS extendido
    FROM base AS b
    LEFT JOIN Sales.Customers AS c ON c.CustomerID = b.CustomerID
    GROUP BY b.CustomerID, c.CustomerName
), por_mes AS (
    SELECT YEAR(InvoiceDate) AS anio, MONTH(InvoiceDate) AS mes, COUNT_BIG(*) AS lineas,
        SUM(importe_base) AS importe_base, SUM(base_alternativa) AS base_alternativa,
        SUM(impuesto) AS impuesto, SUM(extendido) AS extendido
    FROM base GROUP BY YEAR(InvoiceDate), MONTH(InvoiceDate)
)
SELECT N'Total candidato' AS etapa, COUNT_BIG(*) AS lineas,
    SUM(importe_base) AS base_candidata, SUM(base_alternativa) AS base_alternativa,
    SUM(impuesto) AS impuestos, SUM(extendido) AS extendido
FROM base
UNION ALL
SELECT N'Suma por cliente', SUM(lineas), SUM(importe_base), SUM(base_alternativa), SUM(impuesto), SUM(extendido)
FROM por_cliente
UNION ALL
SELECT N'Suma por mes', SUM(lineas), SUM(importe_base), SUM(base_alternativa), SUM(impuesto), SUM(extendido)
FROM por_mes;
