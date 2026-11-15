"""Explicit application permissions; JWT claims never assign these roles."""
from enum import Enum
from typing import Callable, TypeVar


class Role(str, Enum):
    ADMIN = 'ADMIN'
    ANALYST = 'ANALYST'
    VIEWER = 'VIEWER'


class Permission(str, Enum):
    PROFILE_READ = 'profile:read'
    GENERAL_READ = 'general:read'
    CUSTOMERS_READ = 'customers:read'
    PREDICTIONS_READ = 'predictions:read'
    ASSISTANT_USE = 'assistant:use'
    ROLES_MANAGE = 'roles:manage'  # Reserved: no HTTP administration in this phase.


ROLE_PERMISSIONS = {
    Role.VIEWER: frozenset({Permission.PROFILE_READ, Permission.GENERAL_READ}),
    Role.ANALYST: frozenset({Permission.PROFILE_READ, Permission.GENERAL_READ, Permission.CUSTOMERS_READ,
                            Permission.PREDICTIONS_READ, Permission.ASSISTANT_USE}),
    Role.ADMIN: frozenset(Permission),
}
Endpoint = TypeVar('Endpoint', bound=Callable)


def requires_permission(permission: Permission) -> Callable[[Endpoint], Endpoint]:
    """Attach a policy without wrapping the endpoint or changing its signature."""
    def declare(endpoint: Endpoint) -> Endpoint:
        setattr(endpoint, '__business_permission__', permission)
        return endpoint
    return declare
