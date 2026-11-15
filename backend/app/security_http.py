"""Bound real request bytes before parsing; add safe response headers."""
import asyncio
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger('backend.security')
SECURITY_HEADERS = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'}


class BodyTooLarge(Exception):
    pass


async def bounded_body(receive: Receive, maximum: int) -> bytes | None:
    body = bytearray()
    while True:
        message = await receive()
        if message['type'] == 'http.disconnect':
            return None
        chunk = message.get('body', b'')
        if len(body) + len(chunk) > maximum:
            raise BodyTooLarge()
        body.extend(chunk)
        if not message.get('more_body', False):
            return bytes(body)


class SecurityHTTPMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = 16384, body_timeout: float = 10) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.body_timeout = body_timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        response_started = False

        async def secure_send(message: Message) -> None:
            nonlocal response_started
            if message['type'] == 'http.response.start':
                response_started = True
                headers = [(key, value) for key, value in message.get('headers', [])
                           if key.lower() not in {name.lower().encode() for name in SECURITY_HEADERS}]
                headers.extend((name.lower().encode(), value.encode()) for name, value in SECURITY_HEADERS.items())
                message = {**message, 'headers': headers}
            await send(message)

        try:
            lengths = [value for key, value in scope.get('headers', []) if key.lower() == b'content-length']
            if lengths and (len(lengths) != 1 or not lengths[0].isdigit()):
                raise ValueError()
            if lengths and int(lengths[0]) > self.max_body_bytes:
                raise BodyTooLarge()
            body = await asyncio.wait_for(bounded_body(receive, self.max_body_bytes), self.body_timeout)
        except (BodyTooLarge, TimeoutError, ValueError) as error:
            status = 413 if isinstance(error, BodyTooLarge) else 408 if isinstance(error, TimeoutError) else 400
            logger.info('request_rejected status=%s', status)
            await JSONResponse({'detail': 'Solicitud no aceptada.'}, status_code=status)(scope, receive, secure_send)
            return
        if body is None:
            return
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        try:
            await self.app(scope, replay, secure_send)
        except Exception:
            # Handle before ServerErrorMiddleware/Uvicorn can log raw exception data.
            logger.error('request_failed reason=internal_error')
            if not response_started:
                await JSONResponse({'detail': 'Servicio temporalmente no disponible.'},
                                   status_code=500)(scope, receive, secure_send)
            else:
                # Cannot replace a started response. No exception details in the stream.
                try:
                    await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
                except Exception:
                    logger.error('response_termination_failed')
