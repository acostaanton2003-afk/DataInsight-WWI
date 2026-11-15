# Creación física del DWH en Supabase PostgreSQL 17

## Estado y alcance

Según el contexto del proyecto, Supabase ya existe y `dwh` fue creado manualmente; todavía no existen sus cinco tablas ni hay cargas. Esta preparación **no abrió conexiones a Supabase ni ejecutó DDL en ningún servidor**. No se cargaron CSV, crearon conexiones externas, implementaron staging ni hicieron commits.

Archivos de esta etapa:

- `database/data-warehouse/03_creacion_tablas_dwh.sql`: instalación inicial ejecutable para PostgreSQL 17, en una transacción.
- `database/data-warehouse/04_verificacion_dwh.sql`: consultas separadas de solo lectura para inspección antes/después.
- `database/data-warehouse/verificar_ready_ddl.py`: inspección local por lotes de cabeceras y tipos CSV, sin base de datos.
- `tests/test_ddl_fisico.py`: pruebas locales del contrato físico y de las instrucciones de seguridad declaradas.

El DDL lógico histórico `01_modelo_logico.sql` permanece comentado y no se modifica. Se revisaron además el modelo de 09, la transformación de 10, el código READY y el perfil de referencias. No se altera la transformación ni se regeneran datos.

## Decisiones físicas y correspondencia READY

El nombre físico solicitado es **dwh.fact_pedidos**. Es la estructura que el diseño lógico anterior llamaba `fact_seguimiento_pedidos`: se conserva exactamente su orden de columnas, tipos, claves y grano; no se crean ambas tablas. FactVentas sigue teniendo una fila por InvoiceLineID y FactPedidos una por OrderID. InvoiceID y OrderID de ventas son identificadores degenerados, sin FK entre hechos ni dimensiones factura/pedido.

| CSV READY | Tabla física | Columnas | Filas inspeccionadas localmente |
| --- | --- | ---: | ---: |
| DimFecha.csv | dwh.dim_fecha | 6 | 1249 |
| DimCliente.csv | dwh.dim_cliente | 11 | 664 |
| DimProducto.csv | dwh.dim_producto | 13 | 228 |
| FactVentas.csv | dwh.fact_ventas | 17 | 228265 |
| FactPedidos.csv | dwh.fact_pedidos | 9 | 73595 |

Las **56 columnas**, incluido su orden, coinciden con el contrato de READY. Las filas inspeccionadas pertenecen a `data/ready/20261115T051935Z-5599dca545214174bc721b3a016daafd/`. La lectura comprobó hashes contra reconciliacion.json, conteos, rangos de enteros, DATE ISO y calendario, booleanos, precisión/escala NUMERIC y nulabilidad. No se modificaron los CSV. Esto no significa que se hayan importado a PostgreSQL.

Se mantienen integer/bigint para claves, DATE para fechas, text para atributos, boolean para indicadores, NUMERIC(18,2) para precio/importes registrados, NUMERIC(18,3) para TaxRate y NUMERIC(28,2) para la base Quantity × UnitPrice. No se supone moneda ni se introducen reglas de signo, una tasa máxima o conteos históricos como CHECK permanentes.

DimFecha conserva YYYYMMDD y el miembro 0 con fecha/atributos NULL. DimCliente y DimProducto admiten clave 0 con clave de negocio NULL. **No se insertan los miembros 0 en este DDL**: sus filas vendrán de los CSV de dimensiones en una futura carga autorizada. Los hechos no tienen DEFAULT 0 en sus FK y no se asignan desconocidos automáticamente.

**Revisión del diseño físico:** cliente_key, producto_key, venta_key y pedido_key son ahora **BIGINT PRIMARY KEY sin IDENTITY ni DEFAULT**. Las cuatro claves llegan explícitas y reproducibles desde READY, por lo que no se necesita generación automática. Esto evita asignaciones accidentales y elimina la necesidad de sincronizar secuencias. Se conserva la clave 0 de dimensiones y la unicidad de las claves de negocio. No cambian nombres, tipos, columnas ni granos.

La instalación crea **cero secuencias**. No se necesitan OVERRIDING SYSTEM VALUE, setval ni permisos de secuencias para cargar estas claves. `01_modelo_logico.sql` conserva sus identidades como borrador histórico; la definición física vigente es 03. El inspector y las pruebas reconocen esta diferencia deliberada, sin ignorar otras discrepancias del contrato.

Se mantienen REVOKE sobre secuencias y sus privilegios por defecto exclusivamente como defensa ante objetos futuros. No conceden permisos, no crean secuencias y no tocan capacidades administrativas. El preflight sigue rechazando secuencias preexistentes y defaults globales de secuencias para clientes/PUBLIC: es una política conservadora de privacidad futura, no una dependencia de las tablas actuales. Las consultas de secuencias deben devolver cero filas en esta instalación.

Se mantienen dos columnas generadas STORED:

- `fact_ventas.ventas_sin_impuestos = quantity::numeric * unit_price`.
- `fact_pedidos.tiene_factura = cantidad_facturas > 0`.

Aunque sus nombres aparecen en los CSV READY, **no se deben enviar sus valores como columnas ordinarias de escritura**. La futura carga deberá omitirlas de la lista de destino y conciliar sus valores calculados con READY. No convertirlas en columnas ordinarias ni introducir generación automática de claves para facilitar un importador genérico. PostgreSQL 17 solo implementa columnas generadas almacenadas y limita su escritura directa. [Columnas generadas PostgreSQL 17](https://www.postgresql.org/docs/17/ddl-generated-columns.html).

### Contrato de escritura futura: 56 columnas físicas, 54 campos suministrados

Los CSV READY conservan 56 columnas en total porque incluyen los dos resultados materializados. Las tablas también conservan las mismas 56 columnas, pero PostgreSQL genera dos de ellas. La futura carga deberá **proyectar tanto cabecera como cada fila**, no solo omitir nombres del SQL:

- DimFecha, DimCliente y DimProducto: 6, 11 y 13 columnas de entrada, todas explícitas.
- FactVentas: 17 físicas; enviar 16, excluyendo ventas_sin_impuestos.
- FactPedidos: 9 físicas; enviar 8, excluyendo tiene_factura.

El inspector local informa `columnas_escritura` y sus `posiciones_csv_base_0`, sin escribir una proyección ni implementar la carga. Además comprueba en cada registro READY que las dos columnas materializadas coincidan exactamente con las expresiones generadas (la base no usa tolerancia: Quantity × UnitPrice debe ser exacto).

Un COPY con lista de destino reducida **no descarta los campos sobrantes del archivo**: un CSV de 17 campos no se puede enviar intacto a 16 columnas. Usar únicamente HEADER tampoco hace un mapeo por nombres. En la futura etapa, un lector cliente deberá quitar los dos campos respectivos, procesar UTF-8 con BOM y preservar NULL sin comillas frente a texto vacío entre comillas. Los archivos READY originales no se modificarán. [COPY PostgreSQL 17](https://www.postgresql.org/docs/17/sql-copy.html).

La elección de INSERT/COPY se revisará junto con el rol de carga: PostgreSQL no admite COPY FROM cuando se aplica RLS al ejecutor; el propietario normalmente la elude si no se fuerza RLS. No se desactiva RLS ni se conceden permisos a clientes para resolver un futuro importador. No hay código ni conexión de carga en esta revisión.
## Instalación inicial y objetos preexistentes

El script exige PostgreSQL 17, `dwh` existente, propiedad exacta de CURRENT_USER y sin tablas, vistas o secuencias preexistentes. También comprueba que existan los roles Supabase `anon` y `authenticated`.

No se usa CREATE TABLE IF NOT EXISTS en estas cinco tablas: **no es adecuado para esta instalación inicial con contrato estricto**, porque no prueba que un objeto existente sea compatible. El preflight aborta ante cualquier relación preexistente, incluso si parece compatible; no la adopta, modifica ni elimina. Así tampoco se ocultan estructuras parciales ni una antigua fact_seguimiento_pedidos. Una segunda ejecución correcta será rechazada y deberá inspeccionarse, no tratarse como migración idempotente. PostgreSQL advierte expresamente que IF NOT EXISTS no garantiza similitud con la estructura esperada. [CREATE TABLE PostgreSQL 17](https://www.postgresql.org/docs/17/sql-createtable.html).

El preflight resuelve el OID de dwh y de CURRENT_USER, y exige igualdad con nspowner. Tener USAGE/CREATE o pertenecer al rol propietario no basta para este guarda deliberadamente estricto. No supone que el propietario se llame postgres y muestra propietario, CURRENT_USER y SESSION_USER en el error. No ejecuta SET ROLE ni cambia la propiedad; ante diferencia, un administrador deberá elegir explícitamente el rol propietario autorizado. La consulta 04 muestra propietario_exacto y los permisos de esquema por separado; que estos últimos sean TRUE no sustituye propietario_exacto=TRUE.

No se crea de nuevo `dwh`, no se crean tablas en `public` y no hay operaciones de borrado, vaciado ni carga. Los nombres de tablas y FK están completamente cualificados. Se usa search_path local pg_catalog para evitar resolución accidental de objetos de public. El script incluye BEGIN/COMMIT, límites de espera y excepciones que impiden continuar si fallan los controles; ejecutarlo completo en SQL Editor, sin quitar los guardas.

## Permisos y aislamiento de Data API

El DDL contiene explícitamente:

```sql
REVOKE ALL ON SCHEMA dwh FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA dwh FROM PUBLIC, anon, authenticated;

ALTER DEFAULT PRIVILEGES IN SCHEMA dwh
REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA dwh
REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
```

Los defaults se aplican a objetos futuros creados por **CURRENT_USER**, exclusivamente en dwh. Ejecutar con el rol propietario administrativo previsto para crear los objetos (normalmente postgres en SQL Editor). No se revocan permisos a postgres, al propietario, supabase_admin o service_role; tampoco se hacen concesiones nuevas a esos roles. Se mantienen las capacidades administrativas del propietario y no se cambian propietarios, membresías de roles ni permisos de otros esquemas.

**Límite importante:** un REVOKE por esquema no neutraliza un GRANT por defecto global. El preflight consulta pg_default_acl y aborta si el rol creador tiene defaults globales de tablas/secuencias para PUBLIC/anon/authenticated. No altera esos defaults globales, porque podría afectar otros componentes del proyecto. Si aparece esa excepción, revisar los resultados de 04 y decidir con el administrador el alcance de la corrección o el rol creador adecuado; no eliminar el guarda ni ejecutar una revocación global genérica. Los defaults de otro rol creador se revisan aparte antes de que ese rol cree objetos en dwh. [ALTER DEFAULT PRIVILEGES PostgreSQL 17](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html).

Se activa RLS en las cinco tablas, sin políticas de cliente y sin FORCE RLS sobre el propietario. Esto es una defensa adicional, no una concesión de acceso. Después de los REVOKE se comprueban permisos efectivos de anon/authenticated sobre esquema, tablas, columnas y secuencias, incluida la herencia que reflejan las funciones de privilegios; si quedan permisos, se aborta. Las consultas usan firmas de PostgreSQL 17 con OID de rol/objeto: has_schema_privilege, has_table_privilege, has_any_column_privilege y has_sequence_privilege. Las listas de privilegios separadas por comas significan «cualquiera de ellos», por lo que el resultado esperado es FALSE. has_any_column_privilege detecta concesiones por columna que has_table_privilege por sí sola no detectaría. Las comprobaciones de catálogo están disponibles en el archivo separado. [Funciones de privilegios PostgreSQL 17](https://www.postgresql.org/docs/17/functions-info.html).

**No añadir dwh a los esquemas expuestos por Data API.** El SQL no cambia esa configuración. Confirmarlo manualmente en API settings → Exposed schemas: la configuración de exposición es independiente de la mera existencia del esquema. No ejecutar los ejemplos de GRANT de la guía de exposición pública de esquemas. [Esquemas personalizados en Supabase](https://supabase.com/docs/guides/api/using-custom-schemas).

La consulta current_setting('pgrst.db_schemas',true) de 04 es solo un diagnóstico de lo visible en la sesión: un NULL no certifica que dwh no esté expuesto. Revisar la configuración del proyecto en el panel. Esta etapa no audita todos los roles, funciones SECURITY DEFINER o rutas de acceso preexistentes del proyecto; no agrega ninguna de ellas.

## Pasos manuales futuros en Supabase SQL Editor

1. Revisar el DDL y estas decisiones. Confirmar proyecto correcto, PostgreSQL 17 y rol administrativo propietario de dwh. No usar roles anon/authenticated ni compartir credenciales.
2. Revisar en API settings que **dwh no figure en Exposed schemas**. No agregarlo para esta etapa.
3. Abrir SQL Editor en el proyecto. Ejecutar primero solo las consultas de contexto/esquema/defaults del archivo 04 que no referencian tablas físicas. Confirmar propietario y estado de dwh; el SELECT final de conteos se reserva para después de crear tablas.
4. Abrir una consulta nueva y pegar **todo** `database/data-warehouse/03_creacion_tablas_dwh.sql`. No pegar `01_modelo_logico.sql` ni las consultas SQLite de extracción. Ejecutar manualmente una vez, cuando la revisión esté aprobada.
5. Si hay excepción, detenerse y revisar su causa. El bloque transaccional revierte la instalación; no intentar corregir mediante borrados ni repetir fragmentos. Si SQL Editor deja una transacción abortada abierta, cerrarla con ROLLBACK antes de una nueva revisión. Si el mensaje indica relaciones preexistentes o defaults globales, inspeccionarlos y acordar la corrección antes de otra ejecución.
6. Tras un resultado correcto, ejecutar `04_verificacion_dwh.sql` completo. Es de solo lectura. Guardar la evidencia sin credenciales ni datos en Git.
7. Confirmar los resultados esperados siguientes. **No importar CSV todavía**, ni siquiera los miembros desconocidos.

Resultados esperados tras la futura ejecución, aún pendientes de comprobar en Supabase:

- Cinco tablas únicamente en dwh, con 56 columnas; fact_pedidos como nombre físico final.
- Cinco PK, cinco UNIQUE, seis FK y cuatro CHECK del modelo; restricciones validadas. Los NOT NULL también se inspeccionan en pg_attribute.
- Dieciocho índices: diez de PK/UNIQUE y ocho adicionales. Estos últimos cubren las FK de hechos y acceso por factura/pedido; producto_paquete tiene producto_key como primera columna y sirve también para su FK.
- Cero secuencias; attidentity vacío en las 56 columnas y sin DEFAULT en las cuatro claves BIGINT. attgenerated=s solo en ventas_sin_impuestos y tiene_factura.
- RLS activado en las cinco tablas y ninguna política para clientes.
- FALSE en todos los permisos efectivos de esquema/tablas/secuencias para anon/authenticated; ninguna ACL de esos roles o PUBLIC sobre tablas, secuencias o columnas.
- Ningún default por esquema para clientes/PUBLIC del rol creador; revisar también defaults globales y de otros creadores.
- **Cero filas en las cinco tablas**. Los números 228265/73595 y los importes de READY no deben aparecer como filas cargadas en esta etapa.
- dwh ausente de Exposed schemas, comprobado en el panel; permisos administrativos del propietario conservados.

No se ha verificado ninguno de esos resultados remotos desde esta tarea. Si faltan permisos para inspeccionar un catálogo o los conteos difieren, dejarlo registrado y revisar antes de cualquier carga.

## Orden de carga posterior, solo documentado

Cuando se autorice una etapa de carga: primero DimFecha, DimCliente y DimProducto, incluidos los miembros 0; después FactPedidos y FactVentas. Los dos hechos son independientes entre sí y podrían cargarse en el orden inverso una vez que todas las dimensiones estén disponibles. No hay FK factura→pedido de hecho ni requisito de crear una dimensión de pedidos.

Preservar las claves estables READY, tratar correctamente NULL frente a texto vacío y utilizar listas de columnas explícitas. Excluir ventas_sin_impuestos y tiene_factura de las columnas de escritura, y comprobar sus resultados generados. Las claves deben enviarse explícitamente, sin generación automática ni gestión de secuencias; no se entrega aún una conexión o importador. La inspección de tipos no sustituye la posterior conciliación de filas, claves y métricas en el servidor.

## Verificación local y resultados

Comandos desde PowerShell en la raíz:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v

.\.venv\Scripts\python.exe .\database\data-warehouse\verificar_ready_ddl.py --ready-dir '.\data\ready\20261115T051935Z-5599dca545214174bc721b3a016daafd'
$LASTEXITCODE
```

Resultado: **66 pruebas aprobadas**, incluidas 16 del contrato físico, nombres/granos, precisión, miembros 0, índices de FK, protección ante objetos existentes, transacción, permisos declarados/defaults, ausencia de operaciones destructivas y tipos/inspección con datos ficticios. La inspección de los cinco CSV reales terminó con código 0: las 56 columnas físicas, tipos y las dos expresiones generadas son compatibles, con hashes/conteos correctos. Las pruebas añadidas cubren claves sin generación automática, preflight de propietario exacto, permisos por columnas, proyección de 54 campos de escritura y discrepancias en resultados generados.

Las pruebas locales no se conectan a servicios, no ejecutan el DDL en PostgreSQL y no son una compilación integral del PL/pgSQL ni una prueba de integración con el SQL Editor. El inspector interpreta el formato concreto de este archivo DDL para contrastar su contrato; no es un parser SQL genérico. Siguen pendientes la ejecución manual aprobada, comprobación de catálogos/permisos reales y validación posterior de una futura carga. No se añadieron dependencias.
