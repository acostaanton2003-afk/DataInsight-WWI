"""HTTP limits tested at the ASGI boundary, including chunked and lying lengths."""
import asyncio
from uuid import uuid4
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from starlette.responses import JSONResponse

from backend.app.main import create_app
from backend.app.config import Settings
from backend.app.security_http import SecurityHTTPMiddleware
from backend.app.rate_limit import AssistantRateLimiter


def run_body(chunks, headers=(), timeout=1):
    reached=Mock()
    messages=[]
    async def endpoint(scope,receive,send):
        reached(await receive())
        await JSONResponse({'ok':True})(scope,receive,send)
    chunks=iter(chunks)
    async def receive():return next(chunks)
    async def send(message):messages.append(message)
    scope={'type':'http','method':'POST','path':'/','headers':headers}
    asyncio.run(SecurityHTTPMiddleware(endpoint,max_body_bytes=16,body_timeout=timeout)(scope,receive,send))
    return messages,reached


@pytest.mark.parametrize('headers',[[],[(b'content-length',b'1')]])
def test_actual_chunked_bytes_limited_even_with_false_length(headers):
    messages,reached=run_body([{'type':'http.request','body':b'a'*10,'more_body':True},
                              {'type':'http.request','body':b'b'*7,'more_body':False}],headers)
    assert messages[0]['status']==413
    reached.assert_not_called()


def test_exact_limit_is_accepted_and_replayed():
    messages,reached=run_body([{'type':'http.request','body':b'a'*8,'more_body':True},
                              {'type':'http.request','body':b'b'*8,'more_body':False}])
    assert messages[0]['status']==200
    assert reached.call_args.args[0]['body']==b'a'*8+b'b'*8


@pytest.mark.parametrize('headers,status',[
    ([(b'content-length',b'17')],413), ([(b'content-length',b'-1')],400),
    ([(b'content-length',b'1'),(b'content-length',b'1')],400),
])
def test_content_length_rejects_without_reading(headers,status):
    messages,reached=run_body([],headers)
    assert messages[0]['status']==status
    reached.assert_not_called()


def test_body_timeout_is_controlled():
    reached=Mock();messages=[]
    async def slow_receive():await asyncio.sleep(1)
    async def send(message):messages.append(message)
    asyncio.run(SecurityHTTPMiddleware(reached,body_timeout=0.001)(
        {'type':'http','headers':[]},slow_receive,send))
    assert messages[0]['status']==408
    reached.assert_not_called()


def test_disconnect_never_enters_application():
    messages,reached=run_body([{'type':'http.disconnect'}])
    assert messages==[]
    reached.assert_not_called()


def test_large_http_body_never_authenticates_or_queries_roles():
    app=create_app(Settings())
    app.state.session_verifier=Mock()
    app.state.role_repository=Mock()
    with TestClient(app) as client:
        response=client.post('/api/v1/asistente/consultar',content=b'x'*16385,
                             headers={'Authorization':'Bearer synthetic'})
    assert response.status_code==413
    app.state.session_verifier.verify.assert_not_called()
    app.state.role_repository.find.assert_not_called()
    assert response.headers['cache-control']=='no-store'


def test_security_headers_on_public_and_rejected_routes():
    with TestClient(create_app(Settings())) as client:
        for path in ('/api/v1/health','/api/v1/kpis','/not-found'):
            response=client.get(path)
            assert response.headers['cache-control']=='no-store'
            assert response.headers['x-content-type-options']=='nosniff'
            assert response.headers['x-frame-options']=='DENY'
            assert response.headers['referrer-policy']=='no-referrer'


def test_rate_limiter_resets_bounds_and_does_not_evict_active_users(monkeypatch):
    clock=[1000.0]
    monkeypatch.setattr('backend.app.rate_limit.monotonic',lambda:clock[0])
    limiter=AssistantRateLimiter(limit=2,window=60,capacity=1)
    user=uuid4()
    assert limiter.allow(user)
    assert limiter.allow(user)
    assert not limiter.allow(user)
    assert not limiter.allow(uuid4())
    assert len(limiter._buckets)==1
    clock[0]+=60
    assert limiter.allow(uuid4())
    assert len(limiter._buckets)==1


def test_security_middleware_does_not_intercept_lifespan():
    reached=Mock()
    async def app(scope,receive,send):reached(scope['type'])
    asyncio.run(SecurityHTTPMiddleware(app)({'type':'lifespan'},None,None))
    reached.assert_called_once_with('lifespan')


@pytest.mark.parametrize('mechanism',['mount','raw','included_raw'])
def test_unsupported_routes_fail_closed_before_handlers(mechanism):
    from fastapi import APIRouter, FastAPI
    from starlette.routing import Route
    app=create_app(Settings())
    reached=Mock()
    async def probe(request):reached();return JSONResponse({'synthetic':True})
    if mechanism=='mount':
        child=FastAPI()
        child.add_route('/probe',probe)
        app.mount('/unreviewed',child)
        path='/unreviewed/probe'
    elif mechanism=='raw':
        app.add_route('/unreviewed',probe);path='/unreviewed'
    else:
        app.include_router(APIRouter(routes=[Route('/unreviewed',probe)]));path='/unreviewed'
    app.state.session_verifier=Mock()
    app.state.role_repository=Mock()
    with TestClient(app) as client:
        response=client.get(path)
    assert response.status_code==503
    reached.assert_not_called()
    app.state.role_repository.find.assert_not_called()
    app.state.session_verifier.verify.assert_not_called()
    assert response.headers['cache-control']=='no-store'


def test_websocket_without_approved_security_is_closed():
    from starlette.websockets import WebSocketDisconnect
    app=create_app(Settings())
    reached=Mock()
    @app.websocket('/unreviewed-ws')
    async def probe(socket):reached();await socket.accept()
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect('/unreviewed-ws'):pass
    assert caught.value.code==1008
    reached.assert_not_called()


def test_documentation_can_be_disabled_without_affecting_health():
    with TestClient(create_app(Settings(docs_enabled=False))) as client:
        for path in ('/docs','/redoc','/openapi.json'):
            assert client.get(path).status_code==404
        assert client.get('/api/v1/health').status_code==200
        assert client.get('/api/v1/kpis').status_code==401
