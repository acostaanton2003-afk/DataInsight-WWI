"""HTTP authentication and temporary fail-closed business authorization."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.authentication import (
    AuthenticatedUser, AuthenticationUnavailable, InvalidSession,
)

bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticated_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(401, 'Se requiere una sesión válida.', headers={'WWW-Authenticate': 'Bearer'})
    try:
        return request.app.state.session_verifier.verify(credentials.credentials)
    except InvalidSession:
        raise HTTPException(401, 'Sesión inválida o expirada.', headers={'WWW-Authenticate': 'Bearer'}) from None
    except AuthenticationUnavailable:
        raise HTTPException(503, 'Autenticación temporalmente no disponible.') from None


def require_business_access(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
) -> None:
    """Do not infer application permissions from JWT role=authenticated."""
    raise HTTPException(403, 'Acceso a datos deshabilitado hasta implementar permisos.')
