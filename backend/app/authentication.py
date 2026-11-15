"""ES256 session verification with bounded, rotating public-key cache."""
from dataclasses import dataclass
import json
from threading import Lock
from time import monotonic
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

import jwt
from jwt import PyJWK

from backend.app.auth_config import AuthSettings


class InvalidSession(Exception):
    """Untrusted, expired or unsupported session token."""


class AuthenticationUnavailable(Exception):
    """Trusted configuration or public keys unavailable."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    session_id: UUID


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_jwks(url: str) -> dict:
    """Only called with the server-configured HTTPS URL, without credentials."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(url, headers={'Accept': 'application/json'}), timeout=5) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError('JWKS demasiado grande.')
    return json.loads(payload)


class SessionVerifier:
    """One instance per app; refresh TTL 300s, unknown-key cooldown 30s."""
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self._keys: dict[str, PyJWK] = {}
        self._expires = 0.0
        self._last_attempt = float('-inf')
        self._lock = Lock()

    def _key(self, kid: str) -> PyJWK:
        if not self.settings.supabase_url:
            raise AuthenticationUnavailable()
        with self._lock:
            now = monotonic()
            if now < self._expires and kid in self._keys:
                return self._keys[kid]
            if now - self._last_attempt < 30:
                if now >= self._expires:
                    raise AuthenticationUnavailable()
                raise InvalidSession()
            self._last_attempt = now
            try:
                document = fetch_jwks(self.settings.jwks_url)
                if not isinstance(document, dict) or not isinstance(document.get('keys'), list):
                    raise ValueError('JWKS inválido.')
                keys = {}
                for entry in document['keys']:
                    if not isinstance(entry, dict):
                        raise ValueError('Clave pública inválida.')
                    if (entry.get('kty') == 'EC' and entry.get('crv') == 'P-256'
                            and entry.get('alg') == 'ES256' and entry.get('use', 'sig') == 'sig'
                            and entry.get('key_ops', ['verify']) == ['verify'] and 'd' not in entry):
                        identifier = entry['kid']
                        if not isinstance(identifier, str) or not identifier or identifier in keys:
                            raise ValueError('JWKS ambiguo.')
                        keys[identifier] = PyJWK.from_dict(entry, algorithm='ES256')
                if not keys:
                    raise ValueError('JWKS sin claves ES256.')
            except (OSError, ValueError, KeyError, TypeError, RecursionError, jwt.PyJWTError):
                raise AuthenticationUnavailable() from None
            self._keys = keys
            self._expires = monotonic() + 300
            if kid not in keys:
                raise InvalidSession()
            return keys[kid]

    def verify(self, token: str) -> AuthenticatedUser:
        try:
            if not token or len(token) > 16384:
                raise InvalidSession()
            header = jwt.get_unverified_header(token)
            kid = header.get('kid')
            if (header.get('alg') != 'ES256' or header.get('typ') != 'JWT'
                    or not isinstance(kid, str) or not 1 <= len(kid) <= 200
                    or any(name in header for name in ('jku', 'x5u', 'jwk', 'crit'))):
                raise InvalidSession()
            key = self._key(kid)
            claims = jwt.decode(token, key.key, algorithms=['ES256'],
                issuer=self.settings.issuer, audience=self.settings.audience,
                options={'require': ['iss', 'aud', 'exp', 'iat', 'sub', 'role',
                                     'session_id', 'aal', 'is_anonymous'], 'strict_aud': True})
            if (claims['role'] != 'authenticated' or claims['is_anonymous'] is not False
                    or claims['aal'] not in ('aal1', 'aal2')
                    or type(claims['exp']) is not int or type(claims['iat']) is not int
                    or ('nbf' in claims and type(claims['nbf']) is not int)
                    or claims['exp'] <= claims['iat']):
                raise InvalidSession()
            user_id = UUID(claims['sub'])
            session_id = UUID(claims['session_id'])
            if user_id.int == 0 or session_id.int == 0:
                raise InvalidSession()
            return AuthenticatedUser(user_id=user_id, session_id=session_id)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise InvalidSession() from None
