"""Liveness local: no consulta bases de datos."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from backend import __version__

router = APIRouter(prefix='/api/v1',tags=['health'])


class HealthResponse(BaseModel):
    status: Literal['ok']
    name: Literal['DataInsight WWI']
    version: str


@router.get('/health',response_model=HealthResponse)
def health():
    return HealthResponse(status='ok',name='DataInsight WWI',version=__version__)
