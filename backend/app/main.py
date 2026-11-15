"""Punto de entrada ASGI y fábrica para pruebas aisladas."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend import __version__
from backend.app.config import Settings, load_settings
from backend.app.routers.health import router as health_router
from backend.app.routers.analytics import router as analytics_router
from backend.app.routers.predictions import router as predictions_router


def create_app(settings: Settings | None=None):
    settings = load_settings() if settings is None else settings
    application = FastAPI(title='DataInsight WWI',version=__version__,
                          description='Analítica de ventas del DWH con conexión de solo lectura; health independiente.')
    application.state.settings = settings
    application.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),
                               allow_credentials=False,allow_methods=['GET'],
                               allow_headers=['Accept','Content-Type'])
    application.include_router(health_router)
    application.include_router(analytics_router)
    application.include_router(predictions_router)
    return application


app = create_app()
