# Reglas de calidad de datos

## Estado y alcance

Se incorporan los resultados reales comunicados de las validaciones de WideWorldImporters. Rango observado: **2013-01-01 a 2016-05-31**. Esta edición no ejecutó consultas contra la base. No se dispone de fecha de ejecución ni de las salidas completas; esos datos de trazabilidad quedan pendientes de adjuntar.

El script `database/source/02_validacion_kpis_calidad.sql` contiene consultas de lectura. El bloque A reúne variantes optimizadas para SQL Server Express; el bloque B conserva las comprobaciones originales, secciones 0 a 7, como referencia. Ejecutar consultas seleccionadas, no todo el archivo indiscriminadamente. Los JOIN problemáticos utilizaron `LOOP JOIN` y `OPTION (MAXDOP 1)` por limitaciones de memoria; no se modificaron datos.

## Controles y resultados

| ID | Control | Resultado y alcance | Referencia SQL |
| --- | --- | --- | --- |
| Q01 | Metadatos | Sin resultado detallado comunicado; conservar contraste de columnas, tipos y nulabilidad antes de reutilizar las consultas. | B.0 |
| Q02 | Nulos | Perfil detallado pendiente de documentar. No deducir ausencia de nulos a partir de las sumas. | B.1 |
| Q03 | Duplicados de clave | No se detectaron claves duplicadas en las comprobaciones realizadas. El control original agrupa las claves de Orders, OrderLines, Invoices, InvoiceLines, Customers y StockItems. No implica que líneas repetidas de un artículo sean duplicados de negocio. | B.1 |
| Q04 | Integridad referencial | No se detectaron relaciones huérfanas en las comprobaciones realizadas. El control original revisa enlaces de líneas a cabeceras, facturas a pedidos, clientes comerciales y de facturación, y artículos. Referencias NULL requieren evaluación separada. | B.2 |
| Q05 | Cabeceras sin detalle | Sin resultado comunicado; pendiente de documentar. | B.2 |
| Q06 | Cantidades, precios y signos | Perfil detallado pendiente de documentar; no asumir ausencia de ceros o negativos. | B.3 |
| Q07 | Notas de crédito | 70510 facturas, todas con IsCreditNote = 0. Tratamiento de créditos para futuras cargas pendiente de decisión. | A.2 / B.3 |
| Q08 | Fórmulas monetarias | No se detectaron diferencias superiores a 0.01 en las comprobaciones realizadas del total extendido frente a base más impuesto. Validación detallada de impuestos pendiente. | A.7 / B.4 |
| Q09 | Fechas | Rango observado 2013-01-01 a 2016-05-31; cero facturas con fecha anterior al pedido. No se comunicaron resultados detallados de fechas nulas o futuras. | A.8 / B.5 |
| Q10 | Conciliación completa | **Pendiente**: no se da por completada la sección 7. Revisar población, filas e importes en todas las etapas y enlaces. | B.7 |
| Q11 | Coherencia de KPI | Total mensual de 172261341.20 en 41 meses, coincidente con ventas sin impuestos. Los restantes cruces de la conciliación completa siguen pendientes. | A.1, A.5 / B.7 |
| Q12 | Pedidos sin factura | 73595 pedidos: 70510 con factura y 3085 sin factura, equivalentes al 4.19%. No implica cancelación ni otro estado comercial. | A.6 / B.6.6 |

Los hallazgos se limitan a las comprobaciones realizadas y al estado de la fuente consultado. No constituyen una garantía de ausencia de otros problemas ni umbrales invariables para futuras cargas.

## Evidencia de los seis KPI

| KPI | Resultado comunicado |
| --- | --- |
| Ventas totales | 228265 líneas; sin impuestos 172261341.20; impuestos 25782098.25; con impuestos 198043439.45. |
| Facturas | 70510; todas con IsCreditNote = 0. |
| Top 10 productos por cantidad y PackageTypeID | Líder StockItemID 191, 207324 unidades. PackageTypeID del líder y otras nueve filas no proporcionados. |
| Top 10 clientes por ventas sin impuestos | Líder CustomerID 149, 381585.35. Otras nueve filas no proporcionadas. |
| Ventas mensuales | 41 meses, enero de 2013 a mayo de 2016; total sin impuestos 172261341.20. |
| Pedidos sin factura | 3085 de 73595, 4.19%; 70510 con factura. |

Las definiciones, granularidad, filtros y fórmulas se encuentran en `03_definicion_kpis.md`. No se reconstruyen las filas faltantes de los rankings ni los importes mensuales sin evidencia.

## Nulos, tolerancia e impuestos

`SUM` omite NULL. Si falta `UnitPrice`, la base `Quantity * UnitPrice` queda incompleta; no reemplazar nulos por cero para forzar coincidencias. Conservar los conteos de líneas completas e incompletas al revisar las fórmulas.

El control monetario usa diferencia absoluta **mayor que 0.01** entre `ExtendedPrice` y `Quantity * UnitPrice + TaxAmount`. El resultado comunicado no prueba igualdad exacta ni ausencia de diferencias de 0.01 o menores. La tolerancia definitiva depende de la moneda y de las reglas aprobadas.

La **validación detallada de impuestos permanece pendiente**, incluida la comparación de `TaxAmount` con `ROUND(Quantity * UnitPrice * TaxRate / 100, 2)`, base gravable, exenciones y redondeo por línea o documento. El agregado de impuestos de 25782098.25 no certifica esas reglas. Las hipótesis originales de B.4 se conservan para investigación; `ExtendedPrice` frente a la base sin impuestos no es un criterio de igualdad para un total que incluye impuestos.

## Conciliación y pendientes

La **conciliación completa de B.7 permanece pendiente**: comparar líneas originales, agregación por InvoiceID, enlaces a cabeceras y maestros, y sumas por cliente y mes sobre la misma población. La coincidencia entre el total mensual y el KPI 1 es evidencia parcial, no el cierre de esa sección. No se propone igualar todos los pedidos con todas las facturas, pues existen pedidos sin factura.

Pendiente adjuntar fecha y salidas de ejecución, completar los rankings y los perfiles sin resultados comunicados, y aprobar moneda, política de créditos, unidades, tolerancia y excepciones antes del ETL. Si la fuente cambia, repetir los controles sobre un mismo estado. No se crean procesos ETL ni se aplican correcciones a la base en esta actualización.

## Aplicación local sobre las muestras RAW

La etapa [RAW → VALIDATED](07_validacion_calidad.md) implementa controles basados en los metadatos reales, cuarentena y reportes locales. Este registro de validaciones de la fuente conserva su alcance histórico: la muestra local no completa la conciliación SQL de la sección 7 ni la validación detallada de impuestos. Ceros, negativos y fechas futuras se perfilan sin inventar reglas de rechazo. Las claves foráneas no se evalúan entre muestras independientes.
