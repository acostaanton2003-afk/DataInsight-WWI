"""Pruebas de backend aisladas de la configuración privada de la raíz."""

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('BACKEND_HOST','127.0.0.1')
    monkeypatch.setenv('BACKEND_PORT','8000')
    monkeypatch.setenv('CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173')
    for name in ('HOST','PORT','NAME','USER','PASSWORD','SSLMODE'):
        monkeypatch.setenv('BACKEND_DB_'+name,'')
    from backend.app.main import create_app
    # Service contract tests bypass only authorization; security tests use a fresh app.
    from backend.app.auth_dependencies import require_business_access
    application = create_app(Settings())
    application.dependency_overrides[require_business_access] = lambda: None
    with TestClient(application) as test_client:
        yield test_client
