from contextlib import contextmanager
from decimal import Decimal
import sqlite3
from unittest.mock import MagicMock

import pytest

from backend.app import analytics
from backend.app.database import DatabaseReadError
from backend.app.routers.analytics import get_repository


@pytest.fixture
def repository(client):
    repo=MagicMock()
    repo.kpis.return_value=dict(ventas_sin_impuestos=Decimal('0.30'),impuestos=Decimal('0.03'),
        total_facturado=Decimal('0.33'),cantidad_facturas=1,cantidad_pedidos=2,cantidad_clientes=2)
    repo.monthly.return_value=[dict(anio=2013,mes=1,importe=Decimal('0.30'),cantidad_facturas=1)]
    repo.products.return_value=[dict(producto_key=1,stock_item_id=7,stock_item_name='Producto ficticio',ventas_sin_impuestos=Decimal('0.30'))]
    repo.customers.return_value=[dict(cliente_key=1,customer_id=9,customer_name='Cliente ficticio',ventas_sin_impuestos=Decimal('0.30'))]
    client.app.dependency_overrides[get_repository]=lambda: repo
    yield repo
    client.app.dependency_overrides.clear()


def test_kpis_exact_decimal_contract(client,repository):
    response=client.get('/api/v1/kpis')
    assert response.status_code==200
    assert response.json()==dict(ventas_sin_impuestos='0.30',impuestos='0.03',total_facturado='0.33',
        cantidad_facturas=1,cantidad_pedidos=2,cantidad_clientes=2)


def test_monthly_contract(client,repository):
    assert client.get('/api/v1/ventas/por-mes').json()==[
        dict(anio=2013,mes=1,importe='0.30',cantidad_facturas=1)]


@pytest.mark.parametrize('resource,method',[('productos','products'),('clientes','customers')])
@pytest.mark.parametrize('query,limit',[('',10),('?limit=1',1),('?limit=50',50)])
def test_top_limits_and_contract(client,repository,resource,method,query,limit):
    response=client.get('/api/v1/'+resource+'/top'+query)
    assert response.status_code==200
    assert response.json()[0]['ventas_sin_impuestos']=='0.30'
    getattr(repository,method).assert_called_once_with(limit)


@pytest.mark.parametrize('resource',['productos','clientes'])
@pytest.mark.parametrize('limit',['0','51','-1','1.5','abc','1; DROP TABLE dwh.fact_ventas'])
def test_invalid_limits_never_query(client,repository,resource,limit):
    response=client.get('/api/v1/'+resource+'/top',params={'limit':limit})
    assert response.status_code==422
    repository.products.assert_not_called()
    repository.customers.assert_not_called()


@pytest.mark.parametrize('path,method',[
    ('kpis','kpis'),('ventas/por-mes','monthly'),('productos/top','products'),('clientes/top','customers')])
@pytest.mark.parametrize('error',[DatabaseReadError('secret-host-password'),ValueError('secret-host-password')])
def test_errors_are_safe(client,repository,path,method,error):
    getattr(repository,method).side_effect=error
    response=client.get('/api/v1/'+path)
    assert response.status_code==503
    assert response.json()=={'detail':'No se pudo consultar el Data Warehouse.'}
    assert 'secret' not in response.text


@pytest.mark.parametrize('path',['kpis','ventas/por-mes','productos/top','clientes/top'])
def test_no_writes(client,path):
    assert client.post('/api/v1/'+path,json={}).status_code==405


def test_unconfigured_backend_is_safe_without_network(client):
    assert client.get('/api/v1/kpis').status_code==503
    assert client.get('/api/v1/health').status_code==200


def test_openapi_money_is_string(client):
    schema=client.get('/openapi.json').json()
    properties=schema['components']['schemas']['KpisResponse']['properties']
    assert properties['ventas_sin_impuestos']['type']=='string'


def test_empty_results_and_unknown_month(client,repository):
    repository.products.return_value=[]
    assert client.get('/api/v1/productos/top').json()==[]
    repository.monthly.return_value=[dict(anio=None,mes=None,importe=Decimal('1.00'),cantidad_facturas=1)]
    assert client.get('/api/v1/ventas/por-mes').json()[0]['anio'] is None


def test_repository_uses_reader_and_parameterized_limit(monkeypatch):
    settings=object()
    connection=MagicMock()
    cursor=connection.cursor.return_value.__enter__.return_value
    cursor.fetchmany.side_effect=[[{'ventas_sin_impuestos':Decimal('0.10')}],[]]
    @contextmanager
    def reader(actual):
        assert actual is settings
        yield connection
    monkeypatch.setattr(analytics,'read_connection',reader)
    repo=analytics.AnalyticsRepository(settings)
    assert repo.products(7)==[{'ventas_sin_impuestos':Decimal('0.10')}]
    cursor.execute.assert_called_once_with(analytics.PRODUCTS_SQL,(7,))
    connection.cursor.return_value.__exit__.assert_called_once()


def test_sql_grains_credit_filter_order_and_no_join_inflation():
    # Motor local solo para comprobar agregaciones con datos enteros ficticios;
    # no sustituye la prueba PostgreSQL ni se usa para importes de producción.
    with sqlite3.connect(':memory:') as db:
        db.row_factory=sqlite3.Row
        db.execute("ATTACH DATABASE ':memory:' AS dwh")
        db.executescript("""
        CREATE TABLE dwh.dim_cliente(cliente_key INTEGER PRIMARY KEY,customer_id INTEGER,customer_name TEXT);
        INSERT INTO dwh.dim_cliente VALUES(0,NULL,'Desconocido'),(1,9,'C1'),(2,10,'C2');
        CREATE TABLE dwh.dim_producto(producto_key INTEGER PRIMARY KEY,stock_item_id INTEGER,stock_item_name TEXT);
        INSERT INTO dwh.dim_producto VALUES(1,7,'P1'),(2,8,'P2');
        CREATE TABLE dwh.dim_fecha(fecha_key INTEGER PRIMARY KEY,anio INTEGER,mes INTEGER);
        INSERT INTO dwh.dim_fecha VALUES(1,2013,2),(2,2013,1);
        CREATE TABLE dwh.fact_pedidos(order_id INTEGER PRIMARY KEY);
        INSERT INTO dwh.fact_pedidos VALUES(1),(2);
        CREATE TABLE dwh.fact_ventas(invoice_id INTEGER,cliente_key INTEGER,producto_key INTEGER,
          fecha_factura_key INTEGER,ventas_sin_impuestos INTEGER,tax_amount INTEGER,extended_price INTEGER,is_credit_note BOOLEAN);
        INSERT INTO dwh.fact_ventas VALUES
          (10,1,1,1,10,1,11,false),(10,1,1,1,10,1,11,false),
          (11,2,2,2,20,2,22,false),(12,1,1,1,100,10,110,true);
        """)
        kpi=dict(db.execute(analytics.KPIS_SQL).fetchone())
        assert kpi==dict(ventas_sin_impuestos=40,impuestos=4,total_facturado=44,
            cantidad_facturas=2,cantidad_pedidos=2,cantidad_clientes=2)
        months=[dict(r) for r in db.execute(analytics.MONTHLY_SQL)]
        assert [r['mes'] for r in months]==[1,2]
        assert sum(r['importe'] for r in months)==40
        assert [r['cantidad_facturas'] for r in months]==[1,1]
        for query,key in [(analytics.PRODUCTS_SQL,'stock_item_id'),(analytics.CUSTOMERS_SQL,'customer_id')]:
            rows=[dict(r) for r in db.execute(query.replace('%s','?'),(2,))]
            assert sum(r['ventas_sin_impuestos'] for r in rows)==40
            assert rows[0][key]<rows[1][key]  # empate estable
            assert len(list(db.execute(query.replace('%s','?'),(1,))))==1


def test_large_monetary_value_never_becomes_float(client,repository):
    repository.kpis.return_value['ventas_sin_impuestos']=Decimal('9007199254740993.01')
    assert client.get('/api/v1/kpis').json()['ventas_sin_impuestos']=='9007199254740993.01'
