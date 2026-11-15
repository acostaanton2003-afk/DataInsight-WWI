"""Trusted Supabase Auth configuration; independent of PostgreSQL credentials."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class AuthSettings:
    supabase_url: str = ''

    def __post_init__(self) -> None:
        normalized = self.supabase_url.rstrip('/')
        if normalized and not re.fullmatch(r'https://[a-z0-9]{20}\.supabase\.co', normalized):
            raise ValueError('SUPABASE_AUTH_URL debe ser la URL HTTPS oficial del proyecto.')
        object.__setattr__(self, 'supabase_url', normalized)

    @property
    def issuer(self) -> str:
        return self.supabase_url + '/auth/v1'

    @property
    def jwks_url(self) -> str:
        return self.issuer + '/.well-known/jwks.json'

    @property
    def audience(self) -> str:
        return 'authenticated'
