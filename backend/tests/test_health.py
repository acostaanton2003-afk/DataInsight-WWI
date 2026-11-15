import socket

import pytest
from fastapi.testclient import TestClient

from backend import __version__
from backend.app.config import ReadOnlyDatabaseSettings, Settings


def test_health_contract(client):
    response=client.get('/api/v1/health')
    assert response.status_code==200
    assert response.json()=={'status':'ok','name':'DataInsight WWI','version':__version__}


def test_swagger_and_openapi(client):
    assert client.get('/docs').status_code==200
    schema=client.get('/openapi.json').json()
    assert schema['info']['title']=='DataInsight WWI'
    assert schema['info']['version']==__version__
    assert set(schema['paths'])=={'/api/v1/health','/api/v1/kpis','/api/v1/ventas/por-mes','/api/v1/productos/top','/api/v1/clientes/top','/api/v1/predicciones/ventas'}


@pytest.mark.parametrize('path',['/api/v1/sales','/api/v1/clientes','/api/v1/productos'])
def test_business_endpoints_are_not_implemented(client,path):
    assert client.get(path).status_code==404


def test_health_does_not_accept_writes(client):
    assert client.post('/api/v1/health',json={}).status_code==405


def test_cors_allowed_origin_has_no_credentials(client):
    response=client.get('/api/v1/health',headers={'Origin':'http://localhost:5173'})
    assert response.headers['access-control-allow-origin']=='http://localhost:5173'
    assert 'access-control-allow-credentials' not in response.headers
    assert 'Origin' in response.headers['vary']


def test_cors_untrusted_origin_has_no_allow_header(client):
    response=client.get('/api/v1/health',headers={'Origin':'https://untrusted.example'})
    assert response.status_code==200  # CORS no es autenticación: el navegador controla la lectura.
    assert 'access-control-allow-origin' not in response.headers


def test_cors_preflight_allows_only_get(client):
    headers={'Origin':'http://127.0.0.1:5173','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Content-Type'}
    response=client.options('/api/v1/health',headers=headers)
    assert response.status_code==200
    assert response.headers['access-control-allow-origin']==headers['Origin']
    headers['Access-Control-Request-Method']='POST'
    assert client.options('/api/v1/health',headers=headers).status_code==400


def test_cors_preflight_rejects_untrusted_origin(client):
    response=client.options('/api/v1/health',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'GET'})
    assert response.status_code==400
    assert 'access-control-allow-origin' not in response.headers


def test_health_with_future_config_needs_no_database_or_network(client,monkeypatch):
    from backend.app.main import create_app
    def no_network(*args,**kwargs):
        raise AssertionError('No se permiten conexiones de red en este test')
    monkeypatch.setattr(socket,'create_connection',no_network)
    settings=Settings(database=ReadOnlyDatabaseSettings(host='nonexistent.example.invalid',user='reader',password='ficticio-secreto'))
    with TestClient(create_app(settings)) as isolated:
        response=isolated.get('/api/v1/health')
        assert response.status_code==200
        assert 'ficticio-secreto' not in response.text
