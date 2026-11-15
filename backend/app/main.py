"""Punto de entrada ASGI y fábrica para pruebas aisladas."""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.role_repository import RoleRepository
from backend.app.rate_limit import AssistantRateLimiter
from backend.app.security_http import SecurityHTTPMiddleware, SECURITY_HEADERS, logger

from backend import __version__
from backend.app.authentication import SessionVerifier
from backend.app.auth_dependencies import require_business_access
from backend.app.config import Settings, load_settings
from backend.app.routers.health import router as health_router
from backend.app.routers.identity import router as identity_router
from backend.app.routers.analytics import router as analytics_router
from backend.app.routers.predictions import router as predictions_router
from backend.app.routers.assistant import router as assistant_router


def create_app(settings: Settings | None=None):
    settings = load_settings() if settings is None else settings
    application = FastAPI(dependencies=[Depends(require_business_access)], title='DataInsight WWI',version=__version__,
                          description='Analítica de ventas del DWH con conexión de solo lectura; health independiente.')
    application.state.settings = settings
    application.state.session_verifier = SessionVerifier(settings.auth)
    application.state.role_repository = RoleRepository(settings.database)
    application.state.assistant_limiter = AssistantRateLimiter()
    application.add_middleware(SecurityHTTPMiddleware)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({'detail': 'Solicitud inválida.'}, status_code=422, headers=SECURITY_HEADERS)

    @application.exception_handler(Exception)
    async def internal_error(request, error):
        logger.error('request_failed reason=internal_error')
        return JSONResponse({'detail': 'Servicio temporalmente no disponible.'}, status_code=500,
                            headers=SECURITY_HEADERS)

    application.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),
                               allow_credentials=False,allow_methods=['GET','POST'],
                               allow_headers=['Accept','Content-Type','Authorization'])
    application.include_router(health_router)
    application.include_router(identity_router)
    application.include_router(analytics_router)
    application.include_router(predictions_router)
    application.include_router(assistant_router)
    return application


app = create_app()
