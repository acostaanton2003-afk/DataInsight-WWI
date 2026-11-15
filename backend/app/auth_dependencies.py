"""HTTP authentication and fail-closed, server-owned business authorization."""
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.authentication import (
    AuthenticatedUser, AuthenticationUnavailable, InvalidSession,
)

from backend.app.permissions import Permission, Role, ROLE_PERMISSIONS
from backend.app.role_repository import RoleRepository, RoleSourceUnavailable
from backend.app.routers.health import health

logger = logging.getLogger('backend.security')
bearer_scheme = HTTPBearer(auto_error=False)


def get_authenticated_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    if credentials is None or len(request.headers.getlist('authorization')) != 1:
        logger.info('authentication_denied reason=missing_session')
        raise HTTPException(401, 'Se requiere una sesión válida.', headers={'WWW-Authenticate': 'Bearer'})
    try:
        return request.app.state.session_verifier.verify(credentials.credentials)
    except InvalidSession:
        logger.info('authentication_denied reason=invalid_session')
        raise HTTPException(401, 'Sesión inválida o expirada.', headers={'WWW-Authenticate': 'Bearer'}) from None
    except AuthenticationUnavailable:
        logger.warning('authentication_unavailable')
        raise HTTPException(503, 'Autenticación temporalmente no disponible.') from None


def get_role_repository(request: Request) -> RoleRepository:
    return request.app.state.role_repository


def require_business_access(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    repository: Annotated[RoleRepository, Depends(get_role_repository)],
) -> None:
    """Global dependency: only health is public; undeclared policies deny access."""
    endpoint = request.scope.get('endpoint')
    if endpoint is health:
        return
    user = get_authenticated_user(request, credentials)
    permission = getattr(endpoint, '__business_permission__', None)
    if not isinstance(permission, Permission):
        logger.info('authorization_denied reason=missing_policy')
        raise HTTPException(403, 'Acceso no autorizado.')
    try:
        assignment = repository.find(user.user_id)
    except RoleSourceUnavailable:
        logger.warning('authorization_unavailable')
        raise HTTPException(503, 'Autorización temporalmente no disponible.') from None
    try:
        role = Role(assignment.role) if assignment is not None else None
    except (ValueError, TypeError):
        role = None
    if (assignment is None or assignment.user_id != user.user_id or assignment.enabled is not True
            or permission not in ROLE_PERMISSIONS.get(role, frozenset())):
        logger.info('authorization_denied reason=insufficient_permission')
        raise HTTPException(403, 'Acceso no autorizado.')
    if permission is Permission.ASSISTANT_USE and not request.app.state.assistant_limiter.allow(user.user_id):
        logger.info('request_rejected reason=assistant_rate_limit')
        raise HTTPException(429, 'Límite temporal de solicitudes alcanzado.', headers={'Retry-After': '60'})
    request.state.effective_identity = {
        'user_id': user.user_id, 'role': role,
        'permissions': sorted(ROLE_PERMISSIONS[role], key=lambda item: item.value),
    }
    logger.info('authorization_allowed permission=%s', permission.value)
