"""Arranque local: python -m backend (sin recarga automática)."""

import uvicorn

from backend.app.main import app


if __name__=='__main__':
    settings = app.state.settings
    uvicorn.run(app,host=settings.host,port=settings.port)
