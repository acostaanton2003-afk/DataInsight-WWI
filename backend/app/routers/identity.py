"""Effective web identity: no JWT echo, no additional role or DWH query."""
from uuid import UUID
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from backend.app.permissions import Permission, Role, requires_permission

router = APIRouter(prefix='/api/v1/auth', tags=['sesión'])


class IdentityResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID
    role: Role
    permissions: list[Permission]


@router.get('/me', response_model=IdentityResponse, summary='Identidad y permisos efectivos de la sesión')
@requires_permission(Permission.PROFILE_READ)
def identity(request: Request) -> IdentityResponse:
    return IdentityResponse.model_validate(request.state.effective_identity)
