"""Configuración aislada del ETL; no abre conexiones ni modifica os.environ."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
from backend.app.auth_config import AuthSettings

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / '.env'
DEFAULT_ORIGINS = ('http://localhost:5173','http://127.0.0.1:5173')
ADMIN_ROLES = {'postgres','supabase_admin','service_role','authenticator'}


def parse_origins(value):
    entries = value.split(',') if isinstance(value,str) else value
    origins = []
    for entry in entries:
        origin = entry.strip()
        if not origin:
            continue
        try:
            if any(character.isspace() or ord(character)<32 or ord(character)==127 for character in origin):
                raise ValueError
            parsed = urlsplit(origin)
            port = parsed.port  # Comprobar rango/formato, sin exponer el valor recibido.
            valid = (parsed.scheme in ('http','https') and parsed.hostname and '*' not in origin
                     and parsed.username is None and parsed.password is None
                     and parsed.path in ('','/') and not parsed.query and not parsed.fragment)
            if not valid or (port is not None and port==0):
                raise ValueError
        except ValueError:
            raise ValueError('CORS_ORIGINS debe contener orígenes HTTP(S) explícitos, sin comodines ni credenciales.') from None
        normalized = urlunsplit((parsed.scheme,parsed.netloc,'','',''))
        if normalized not in origins:
            origins.append(normalized)
    return tuple(origins)


def port_number(value):
    try:
        result = int(value)
        if str(result)!=str(value).strip() or not 1<=result<=65535:
            raise ValueError
    except (ValueError,TypeError):
        raise ValueError('Puerto de configuración inválido.') from None
    return result


@dataclass(frozen=True)
class ReadOnlyDatabaseSettings:
    """Configuracion exclusiva del rol lector, sin conexiones al importar."""
    host: str = field(default='',repr=False)
    port: int = field(default=5432,repr=False)
    name: str = field(default='',repr=False)
    user: str = field(default='',repr=False)
    password: str = field(default='',repr=False)
    sslmode: str = field(default='require',repr=False)
    read_only: bool = field(default=True,init=False)

    def validate_for_connection(self):
        if not all(value.strip() for value in (self.host,self.name,self.user,self.password)):
            raise ValueError('Falta configuracion BACKEND_DB_* para el rol lector.')
        if self.user.split('.',1)[0] != 'wwi_backend_reader':
            raise ValueError('La conexion requiere el rol exclusivo wwi_backend_reader.')

    def __post_init__(self):
        object.__setattr__(self,'port',port_number(self.port))
        # También rechaza el formato de usuario compartido postgres.<project-ref>.
        if self.user.strip().split('.',1)[0].casefold() in ADMIN_ROLES:
            raise ValueError('El backend requiere un rol lector dedicado; no admite roles administrativos.')
        if self.sslmode not in ('require','verify-ca','verify-full'):
            raise ValueError('La futura configuración PostgreSQL requiere SSL obligatorio.')


@dataclass(frozen=True)
class AssistantSettings:
    provider: str = 'local'
    model: str = field(default='',repr=False)
    url: str = field(default='http://127.0.0.1:11434/api/chat',repr=False)
    timeout: int = 30

    def __post_init__(self):
        if self.provider not in ('local','ollama') or type(self.timeout) is not int or not 1<=self.timeout<=60:
            raise ValueError('Configuración del asistente inválida.')
        parsed=urlsplit(self.url)
        if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','::1') or parsed.username or parsed.password or parsed.path!='/api/chat' or parsed.query or parsed.fragment:
            raise ValueError('El proveedor opcional solo admite Ollama en loopback, sin credenciales.')
        try:port=parsed.port
        except ValueError:raise ValueError('Puerto del proveedor inválido.') from None
        if port==0:raise ValueError('Puerto del proveedor inválido.')
        if self.provider=='ollama' and (not self.model or len(self.model)>80 or any(c.isspace() for c in self.model) or ':cloud' in self.model.lower() or '-cloud' in self.model.lower()):
            raise ValueError('Configurar el nombre de un modelo local ya instalado.')


@dataclass(frozen=True)
class Settings:
    auth: AuthSettings = field(default_factory=AuthSettings)
    host: str = '127.0.0.1'
    port: int = 8000
    cors_origins: tuple[str,...] = DEFAULT_ORIGINS
    database: ReadOnlyDatabaseSettings = field(default_factory=ReadOnlyDatabaseSettings,repr=False)
    forecast_path: str = field(default='artifacts/machine_learning/published/resumen.json',repr=False)
    assistant: AssistantSettings = field(default_factory=AssistantSettings,repr=False)

    def __post_init__(self):
        object.__setattr__(self,'port',port_number(self.port))
        object.__setattr__(self,'cors_origins',parse_origins(self.cors_origins))
        if not self.host or any(character.isspace() for character in self.host) or '://' in self.host:
            raise ValueError('BACKEND_HOST debe ser una dirección de escucha válida.')


def load_settings(env_file=ENV_FILE,environ: Mapping[str,str] | None=None):
    """Entorno del proceso > .env > defaults; solo se consumen claves del backend."""
    values = {}
    if env_file is not None and Path(env_file).is_file():
        logger = logging.getLogger('dotenv.main')
        silent = lambda record: False
        logger.addFilter(silent)
        try:
            values = dotenv_values(env_file,encoding='utf-8-sig',interpolate=False)
        finally:
            logger.removeFilter(silent)
    environment = os.environ if environ is None else environ
    def get(name,default=''):
        value = environment[name] if name in environment else values.get(name,default)
        return default if value is None else value
    def db(name,default=''):
        return get('BACKEND_DB_'+name,default) or default
    database = ReadOnlyDatabaseSettings(host=db('HOST'),port=db('PORT','5432'),name=db('NAME'),
                                       user=db('USER'),password=db('PASSWORD'),sslmode=db('SSLMODE','require'))
    return Settings(auth=AuthSettings(supabase_url=get('SUPABASE_AUTH_URL','')),host=get('BACKEND_HOST','127.0.0.1'),port=get('BACKEND_PORT','8000'),
                    cors_origins=parse_origins(get('CORS_ORIGINS',','.join(DEFAULT_ORIGINS))),database=database,
                    forecast_path=get('BACKEND_FORECAST_PATH','artifacts/machine_learning/published/resumen.json') or 'artifacts/machine_learning/published/resumen.json',
                    assistant=AssistantSettings(provider=get('ASSISTANT_PROVIDER','local'),model=get('ASSISTANT_OLLAMA_MODEL') or ('qwen3:1.7b' if get('ASSISTANT_PROVIDER','local')=='ollama' else ''),
                        url=get('ASSISTANT_OLLAMA_URL','http://127.0.0.1:11434/api/chat'),timeout=int(get('ASSISTANT_LLM_TIMEOUT','30'))))
