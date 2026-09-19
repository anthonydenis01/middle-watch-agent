import asyncio
from datetime import timedelta
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from api.config import Settings
from api.db.models import Base, Container, Event, ExceptionRecord, Watchlist, now
from api.guardrails import RequestGuard, RunLimiter
from api.main import create_app
from api.services.retention import cleanup, scheduled_cleanup


def test_run_limit_shared_between_routes_and_not_spoofed(client):
    client.app.state.limiter.limit = 2
    assert client.post('/api/watchlists/sample').status_code == 201
    assert client.post('/api/watchlists', json={'numbers': ['BAD']}).status_code == 201
    denied = client.post('/api/benchmark', headers={'X-Forwarded-For': '192.0.2.1'})
    assert denied.status_code == 429
    assert 1 <= int(denied.headers['retry-after']) <= 3600
    assert denied.json()['error']['code'] == 'rate_limited'
    assert client.get('/health').status_code == 200


def test_limiter_expiry_isolation_and_bounded_storage():
    stamp = [0]
    limiter = RunLimiter(1, clock=lambda: stamp[0], capacity=2)
    assert limiter.allow('a') == 0
    assert limiter.allow('b') == 0
    assert limiter.allow('a') == 3600
    assert limiter.allow('c') == 60
    stamp[0] = 3600
    assert limiter.allow('a') == 0
    assert len(limiter.buckets) == 1


def test_body_caps_and_sanitized_errors(client):
    assert client.post('/api/watchlists', content='x' * 16001).status_code == 413
    assert client.post('/api/watchlists/csv', content='x' * 210001).status_code == 413
    assert client.post('/api/watchlists', content='{}', headers={'Content-Length': '-1'}).status_code == 400
    response = client.post('/api/watchlists', json={'numbers': ['private-input' * 10]})
    assert response.status_code == 422
    assert 'private-input' not in response.text
    assert response.json()['error']['issues']
    assert client.get('/missing').json()['error']['code'] == 'http_404'


def test_chunked_body_cannot_bypass_cap():
    async def scenario():
        async def inner(scope, receive, send):
            pytest.fail('oversize body reached parser')
        messages = iter([{'type': 'http.request', 'body': b'x' * 8000, 'more_body': True},
            {'type': 'http.request', 'body': b'x' * 8001, 'more_body': False}])
        sent = []
        async def receive():
            return next(messages)
        async def send(message):
            sent.append(message)
        await RequestGuard(inner, RunLimiter(20))({'type': 'http', 'method': 'POST',
            'path': '/api/validate', 'headers': []}, receive, send)
        assert sent[0]['status'] == 413
        assert json.loads(sent[1]['body'])['error']['code'] == 'body_too_large'
    asyncio.run(scenario())


def test_cors_only_configured_site_and_its_previews():
    app = create_app(Settings(database_url='sqlite:///:memory:', netlify_site_name='middle-watch-demo'))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        for origin in ('https://themiddlewatch.com', 'http://localhost:5173',
                'https://middle-watch-demo.netlify.app', 'https://deploy-preview-42--middle-watch-demo.netlify.app'):
            response = client.options('/api/watchlists', headers={'Origin': origin,
                'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'content-type'})
            assert response.status_code == 200
            assert response.headers['access-control-allow-origin'] == origin
            assert 'access-control-allow-credentials' not in response.headers
        for origin in ('https://unrelated.netlify.app', 'https://middle-watch-demo.netlify.app.evil.test', 'null'):
            response = client.options('/api/watchlists', headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'})
            assert response.status_code == 400
            assert 'access-control-allow-origin' not in response.headers
        app.state.limiter.limit = 1
        client.post('/api/watchlists/sample')
        response = client.post('/api/watchlists/sample', headers={'Origin': 'https://themiddlewatch.com'})
        assert response.status_code == 429
        assert response.headers['access-control-allow-origin'] == 'https://themiddlewatch.com'


def test_localhost_cors_is_development_only(monkeypatch):
    monkeypatch.delenv('CORS_ORIGINS', raising=False)
    monkeypatch.delenv('RENDER', raising=False)
    dev = Settings().cors_origins
    assert 'http://localhost:5173' in dev and 'http://127.0.0.1:5173' in dev
    monkeypatch.setenv('RENDER', 'true')
    prod = Settings().cors_origins
    assert prod == ['https://themiddlewatch.com', 'https://www.themiddlewatch.com']
    assert not any('localhost' in origin or '127.0.0.1' in origin for origin in prod)


def test_normalized_duplicates_are_one_row(client):
    response = client.post('/api/watchlists', json={'numbers': ['CSQU3054383', ' csqu3054383 ', 'CSQU3054383']})
    assert response.status_code == 201
    assert response.json()['summary']['total'] == 1


def test_cleanup_cascades_only_expired_data(client):
    expired = client.post('/api/watchlists/sample').json()
    active = client.post('/api/watchlists', json={'numbers': ['BAD']}).json()
    with client.app.state.sessions() as session:
        session.get(Watchlist, expired['id']).expires_at = now() - timedelta(seconds=1)
        session.commit()
    assert cleanup(client.app.state.sessions) == 1
    assert cleanup(client.app.state.sessions) == 0
    with client.app.state.sessions() as session:
        assert session.get(Watchlist, active['id']) is not None
        assert session.scalar(select(func.count()).select_from(Container)) == 1
        assert session.scalar(select(func.count()).select_from(Event)) == 0
        assert session.scalar(select(func.count()).select_from(ExceptionRecord)) == 0


def test_scheduler_retries_and_runs_without_reads(monkeypatch):
    from api.services import retention
    from sqlalchemy.exc import SQLAlchemyError
    calls = []
    def fake_cleanup(sessions):
        calls.append(True)
        if len(calls) == 1:
            raise SQLAlchemyError('do not expose')
    monkeypatch.setattr(retention, 'cleanup', fake_cleanup)
    async def scenario():
        task = asyncio.create_task(scheduled_cleanup(None, interval=.001))
        for _ in range(100):
            if len(calls) >= 2:
                break
            await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert len(calls) >= 2


def test_database_failure_response_never_echoes_exception(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    def broken(*args, **kwargs):
        raise SQLAlchemyError('private-connection-details')
    monkeypatch.setattr(client.app.state.provider, 'journey', broken)
    response = client.post('/api/watchlists/sample')
    assert response.status_code == 503
    assert 'private-connection-details' not in response.text
