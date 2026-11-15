import os

import pytest

from backend.app.config import ReadOnlyDatabaseSettings, Settings, load_settings, parse_origins


def test_defaults_without_env_or_credentials():
    settings=load_settings(env_file=None,environ={})
    assert settings.host=='127.0.0.1'
    assert settings.port==8000
    assert settings.database.read_only is True
    assert settings.database.user==settings.database.password==''
    assert settings.cors_origins==('http://localhost:5173','http://127.0.0.1:5173')


def test_process_environment_overrides_file_without_mutation(tmp_path):
    path=tmp_path/'.env'
    path.write_text('BACKEND_PORT=9001\nCORS_ORIGINS=http://localhost:3000\nSQLSERVER_HOST=ficticio\n',encoding='utf-8')
    environment={'BACKEND_PORT':'9002','CORS_ORIGINS':''}
    before=dict(os.environ)
    settings=load_settings(path,environ=environment)
    assert settings.port==9002
    assert settings.cors_origins==()
    assert dict(os.environ)==before
    assert environment=={'BACKEND_PORT':'9002','CORS_ORIGINS':''}
    assert load_settings(path,environ={}).port==9001


def test_etl_administrative_credentials_are_never_reused(tmp_path):
    path=tmp_path/'.env'
    path.write_text('SUPABASE_DB_USER=postgres.ficticio\nSUPABASE_DB_PASSWORD=secreto-ficticio\nPOSTGRES_USER=postgres\n',encoding='utf-8')
    settings=load_settings(path,environ={})
    assert settings.database.user==''
    assert settings.database.password==''
    assert 'secreto-ficticio' not in repr(settings)


def test_future_reader_config_is_literal_and_secret_hidden(tmp_path):
    path=tmp_path/'.env'
    path.write_text("BACKEND_DB_HOST=host.example.invalid\nBACKEND_DB_USER=wwi_reader\nBACKEND_DB_PASSWORD='literal-${TOKEN}-ficticio'\nBACKEND_DB_SSLMODE=verify-full\n",encoding='utf-8')
    settings=load_settings(path,environ={})
    assert settings.database.password=='literal-${TOKEN}-ficticio'
    assert settings.database.sslmode=='verify-full'
    assert settings.database.read_only
    assert 'literal-' not in repr(settings.database)
    assert 'literal-' not in repr(settings)


@pytest.mark.parametrize('role',['postgres','postgres.project','supabase_admin','service_role','authenticator'])
def test_administrative_roles_are_rejected(role):
    with pytest.raises(ValueError,match='rol lector'):
        load_settings(None,environ={'BACKEND_DB_USER':role})


@pytest.mark.parametrize('origin',['*','https://*.example.com','null','https://example.com/path','https://user:secret@example.com','http://localhost:invalid','ftp://localhost','https://example.com?query=1','http://local\\nhost:5173'.replace('\\n','\n')])
def test_invalid_cors_is_rejected_without_echoing_values(origin):
    with pytest.raises(ValueError) as error:
        Settings(cors_origins=(origin,))
    assert origin not in str(error.value)


def test_origins_are_explicit_normalized_and_deduplicated():
    assert parse_origins('http://localhost:5173/, http://127.0.0.1:5173,http://localhost:5173')==('http://localhost:5173','http://127.0.0.1:5173')
    assert parse_origins('')==()


@pytest.mark.parametrize('port',[0,65536,'invalid','8000.0'])
def test_invalid_backend_port_is_rejected(port):
    with pytest.raises(ValueError):
        Settings(port=port)


@pytest.mark.parametrize('mode',['disable','allow','prefer'])
def test_future_database_requires_encryption(mode):
    with pytest.raises(ValueError,match='SSL'):
        ReadOnlyDatabaseSettings(sslmode=mode)
