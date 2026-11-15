"""Synthetic ES256 keys and mocked JWKS; never uses real users or data."""
import json
import time
from uuid import UUID, uuid4
from unittest.mock import Mock

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends
from fastapi.testclient import TestClient
import jwt
import pytest

from backend.app import authentication
from backend.app.auth_config import AuthSettings
from backend.app.auth_dependencies import get_authenticated_user
from backend.app.authentication import AuthenticationUnavailable, InvalidSession, SessionVerifier
from backend.app.config import Settings, load_settings
from backend.app.main import create_app

AUTH = AuthSettings('https://abcdefghijklmnopqrst.supabase.co')
PATHS = ['/api/v1/kpis', '/api/v1/ventas/por-mes', '/api/v1/productos/top',
         '/api/v1/clientes/top', '/api/v1/predicciones/ventas', '/api/v1/asistente/consultar']


@pytest.fixture
def signing(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    public = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
    public.update(kid='synthetic-key', alg='ES256', use='sig')
    fetch = Mock(return_value={'keys': [public]})
    monkeypatch.setattr(authentication, 'fetch_jwks', fetch)
    return private, fetch, public


def token(private, changes=None, headers=None):
    now = int(time.time())
    claims = dict(iss=AUTH.issuer, aud='authenticated', exp=now+300, iat=now-1,
                  sub=str(uuid4()), session_id=str(uuid4()), role='authenticated',
                  aal='aal1', is_anonymous=False)
    claims.update(changes or {})
    return jwt.encode(claims, private, algorithm='ES256',
                      headers=headers or {'kid': 'synthetic-key', 'typ': 'JWT'})


@pytest.fixture
def protected_client(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Rejected requests must not access business resources')
    monkeypatch.setattr('backend.app.analytics.AnalyticsRepository', forbidden)
    monkeypatch.setattr('backend.app.database.psycopg.connect', forbidden)
    monkeypatch.setattr('backend.app.routers.analytics.get_repository', forbidden)
    monkeypatch.setattr('backend.app.routers.assistant.AnalyticsRepository', forbidden)
    monkeypatch.setattr('backend.app.routers.assistant.provider_for', forbidden)
    monkeypatch.setattr('backend.app.routers.predictions.read_predictions', forbidden)
    monkeypatch.setattr('backend.app.assistant_provider.OllamaProvider.generate', forbidden)
    with TestClient(create_app(Settings(auth=AUTH))) as client:
        yield client


def request(client, path, headers=None):
    if path.endswith('/consultar'):
        return client.post(path, json={'pregunta': 'Resumen de ventas'}, headers=headers)
    return client.get(path, headers=headers)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('kind', ['anonymous', 'malformed', 'valid'])
def test_all_business_routes_fail_closed(protected_client, signing, path, kind):
    private, fetch, _ = signing
    headers = None if kind == 'anonymous' else {'Authorization': 'Bearer ' + (
        token(private) if kind == 'valid' else 'not-a-token')}
    response = request(protected_client, path, headers)
    assert response.status_code == (403 if kind == 'valid' else 401)
    if kind != 'valid':
        assert response.headers['www-authenticate'] == 'Bearer'
        fetch.assert_not_called()
    assert 'synthetic-key' not in response.text


@pytest.mark.parametrize('changes', [
    {'exp': 1}, {'iss': 'https://attacker.invalid'}, {'aud': 'anon'},
    {'aud': ['authenticated', 'other']}, {'role': 'service_role'}, {'role': 'anon'},
    {'is_anonymous': True}, {'is_anonymous': 'false'}, {'aal': 'invalid'},
    {'sub': 'not-a-uuid'}, {'session_id': 'not-a-session'}, {'sub': str(UUID(int=0))},
    {'iat': int(time.time()) + 1000}, {'nbf': int(time.time()) + 1000},
    {'exp': True}, {'session_id': None},
])
def test_invalid_claims_are_401(protected_client, signing, changes):
    response = protected_client.get(PATHS[0], headers={'Authorization': 'Bearer ' + token(signing[0], changes)})
    assert response.status_code == 401


def test_wrong_signature_is_401(protected_client, signing):
    wrong_key = ec.generate_private_key(ec.SECP256R1())
    response = protected_client.get(PATHS[0], headers={'Authorization': 'Bearer ' + token(wrong_key)})
    assert response.status_code == 401


@pytest.mark.parametrize('algorithm', ['HS256', 'none'])
def test_unexpected_algorithms_never_fetch_keys(protected_client, signing, algorithm):
    encoded = jwt.encode({'sub': str(uuid4())}, 'x'*32 if algorithm == 'HS256' else None, algorithm=algorithm)
    assert protected_client.get(PATHS[0], headers={'Authorization': 'Bearer '+encoded}).status_code == 401
    signing[1].assert_not_called()


@pytest.mark.parametrize('headers', [
    {'kid': 'synthetic-key', 'jku': 'https://attacker.invalid'},
    {'kid': 'synthetic-key', 'x5u': 'https://attacker.invalid'},
    {'kid': 'synthetic-key', 'typ': 'at+jwt'}, {'kid': 'synthetic-key', 'crit': []}, {'kid': ''},
])
def test_untrusted_headers_are_rejected(signing, headers):
    with pytest.raises(InvalidSession):
        SessionVerifier(AUTH).verify(token(signing[0], headers=headers))
    signing[1].assert_not_called()


def test_missing_session_claim(signing):
    encoded = token(signing[0])
    claims = jwt.decode(encoded, options={'verify_signature': False})
    del claims['session_id']
    encoded = jwt.encode(claims, signing[0], algorithm='ES256', headers={'kid': 'synthetic-key'})
    with pytest.raises(InvalidSession):
        SessionVerifier(AUTH).verify(encoded)


def test_identity_dependency_and_no_token_retention(signing):
    app = create_app(Settings(auth=AUTH))
    @app.get('/identity', dependencies=[])
    def identity(user=Depends(get_authenticated_user)):
        return {'user_id': str(user.user_id), 'session_id': str(user.session_id)}
    encoded = token(signing[0])
    with TestClient(app) as client:
        response = client.get('/identity', headers={'Authorization': 'Bearer '+encoded})
    assert response.status_code == 200
    assert set(response.json()) == {'user_id', 'session_id'}
    assert encoded not in response.text


def test_cache_rotation_and_unknown_key_cooldown(signing, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(authentication, 'monotonic', lambda: clock[0])
    verifier = SessionVerifier(AUTH)
    verifier.verify(token(signing[0])); verifier.verify(token(signing[0]))
    assert signing[1].call_count == 1
    encoded = token(signing[0], headers={'kid': 'rotated'})
    with pytest.raises(InvalidSession):
        verifier.verify(encoded)
    assert signing[1].call_count == 1
    rotated = dict(signing[2], kid='rotated')
    signing[1].return_value = {'keys': [rotated]}
    clock[0] += 31
    verifier.verify(encoded)
    assert signing[1].call_count == 2
    clock[0] += 301
    verifier.verify(encoded)
    assert signing[1].call_count == 3


def test_unknown_key_is_401(signing):
    with pytest.raises(InvalidSession):
        SessionVerifier(AUTH).verify(token(signing[0], headers={'kid': 'unknown'}))


@pytest.mark.parametrize('bad_jwks', [{'keys': []}, {}, {'keys': [None]}, {'keys': 'invalid'}])
def test_invalid_jwks_fails_closed(signing, bad_jwks):
    signing[1].return_value = bad_jwks
    with pytest.raises(AuthenticationUnavailable):
        SessionVerifier(AUTH).verify(token(signing[0]))


def test_jwks_unavailable_has_safe_503(protected_client, signing):
    signing[1].side_effect = OSError('sensitive internal path')
    response = protected_client.get(PATHS[0], headers={'Authorization': 'Bearer '+token(signing[0])})
    assert response.status_code == 503
    assert 'sensitive' not in response.text


def test_health_public_without_keys_or_database(protected_client, signing):
    assert protected_client.get('/api/v1/health').status_code == 200
    signing[1].assert_not_called()


@pytest.mark.parametrize('origin, status', [('http://localhost:5173', 200),
    ('http://127.0.0.1:5173', 200), ('https://attacker.invalid', 400)])
def test_authorization_cors(protected_client, origin, status):
    response = protected_client.options(PATHS[0], headers={'Origin': origin,
        'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'Authorization'})
    assert response.status_code == status
    if status == 200:
        assert response.headers['access-control-allow-origin'] == origin
        assert 'access-control-allow-credentials' not in response.headers


def test_config_environment_precedence_and_empty_default(tmp_path):
    path = tmp_path/'example.env'
    path.write_text('SUPABASE_AUTH_URL=https://aaaaaaaaaaaaaaaaaaaa.supabase.co')
    assert load_settings(path, {'SUPABASE_AUTH_URL': AUTH.supabase_url}).auth == AUTH
    assert load_settings(None, {}).auth.supabase_url == ''
    assert AUTH.jwks_url == AUTH.issuer + '/.well-known/jwks.json'
    with pytest.raises(AuthenticationUnavailable):
        SessionVerifier(AuthSettings()).verify(token(ec.generate_private_key(ec.SECP256R1())))


@pytest.mark.parametrize('url', ['http://abcdefghijklmnopqrst.supabase.co',
    'https://attacker.invalid', 'https://user:password@abcdefghijklmnopqrst.supabase.co',
    'https://abcdefghijklmnopqrst.supabase.co/path', 'https://abcdefghijklmnopqrst.supabase.co?x=1'])
def test_untrusted_config_urls_rejected(url):
    with pytest.raises(ValueError):
        AuthSettings(url)


@pytest.mark.parametrize('missing', ['exp', 'iat', 'iss', 'aud', 'sub', 'is_anonymous'])
def test_missing_required_claims_are_401(protected_client, signing, missing):
    claims = jwt.decode(token(signing[0]), options={'verify_signature': False})
    del claims[missing]
    encoded = jwt.encode(claims, signing[0], algorithm='ES256', headers={'kid': 'synthetic-key'})
    assert protected_client.get(PATHS[0], headers={'Authorization': 'Bearer '+encoded}).status_code == 401


def test_bad_authentication_scheme_is_401(protected_client, signing):
    response = protected_client.get(PATHS[0], headers={'Authorization': 'Basic synthetic'})
    assert response.status_code == 401
    signing[1].assert_not_called()


def test_jwks_download_is_bounded_and_uses_no_redirects(monkeypatch):
    response = Mock()
    response.read.return_value = b'{"keys": []}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(authentication, 'build_opener', factory)
    assert authentication.fetch_jwks(AUTH.jwks_url) == {'keys': []}
    args, kwargs = opener.open.call_args
    assert args[0].full_url == AUTH.jwks_url
    assert kwargs['timeout'] == 5
    response.read.assert_called_once_with(65537)
    assert isinstance(factory.call_args.args[1], authentication.NoRedirect)
    response.read.return_value = b'x' * 65537
    with pytest.raises(ValueError):
        authentication.fetch_jwks(AUTH.jwks_url)


def test_jwks_network_failure_is_throttled(signing, monkeypatch):
    signing[1].side_effect = OSError('unavailable')
    verifier = SessionVerifier(AUTH)
    for _ in range(2):
        with pytest.raises(AuthenticationUnavailable):
            verifier.verify(token(signing[0]))
    signing[1].assert_called_once_with(AUTH.jwks_url)
