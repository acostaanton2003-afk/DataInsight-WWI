"""Reject routing mechanisms that bypass FastAPI's global authorization dependency."""
from collections.abc import Sequence
from fastapi import APIRouter
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


def routes_are_guarded(routes: Sequence[BaseRoute], framework_routes: Sequence[BaseRoute]) -> bool:
    for route in routes:
        if any(route is public for public in framework_routes):
            continue
        if type(route) is APIRoute:
            continue
        # FastAPI 0.163 includes routers lazily. Unknown wrappers fail closed.
        nested = getattr(route, 'original_router', None)
        if isinstance(nested, APIRouter) and routes_are_guarded(nested.routes, ()):
            continue
        # Mount, raw Starlette Route, WebSocketRoute and custom handlers need review.
        return False
    return True
