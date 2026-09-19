from contextlib import asynccontextmanager, suppress
import asyncio
from typing import Annotated
from fastapi import FastAPI, File, HTTPException, UploadFile
import csv
import io
import json
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from api.guardrails import RequestGuard, RunLimiter, error_response
from api.services.retention import scheduled_cleanup
from api.explain import explain
from api.config import FEED_NOTICE, ROOT, Settings, VERSION
from api.db import connect
from api.db.models import Container, Watchlist, now
from api.providers.simulated import SAMPLE_NUMBERS, SimulatedProvider
from api.services.watchlists import create_watchlist, container_payload, watchlist_payload
from api.services.benchmark import run_benchmark
from api.services.validation import validate_number


class Numbers(BaseModel):
    model_config = ConfigDict(extra='forbid')
    numbers: list[Annotated[str, StringConstraints(max_length=40)]] = Field(min_length=1, max_length=100)


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = connect(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(scheduled_cleanup(sessions, settings.cleanup_interval))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            engine.dispose()

    app = FastAPI(title='Middle Watch API', version=VERSION, description=FEED_NOTICE, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.provider = SimulatedProvider()
    app.state.limiter = RunLimiter(settings.runs_per_hour)
    app.add_middleware(RequestGuard, limiter=app.state.limiter, render_proxy=settings.render_proxy)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
        allow_origin_regex=settings.preview_origin_regex, allow_credentials=False,
        allow_methods=['GET', 'POST'], allow_headers=['Content-Type'], expose_headers=['Retry-After'])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error_response(exc.status_code, f'http_{exc.status_code}', str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        issues = [{'location': list(e['loc']), 'type': e['type']} for e in exc.errors()]
        return error_response(422, 'invalid_request', 'Check the request format and input limits.', issues=issues)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return error_response(503, 'database_unavailable', 'The database is temporarily unavailable. Try again shortly.')

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return error_response(500, 'internal_error', 'The request could not be completed. Try again shortly.')

    @app.get('/health')
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
            return {'status': 'ok', 'version': VERSION, 'db': 'ok', 'feed_notice': FEED_NOTICE}
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={'status': 'unavailable', 'version': VERSION, 'db': 'unavailable', 'feed_notice': FEED_NOTICE})

    @app.post('/api/validate')
    def validate(body: Numbers):
        return {'results': [validate_number(n) for n in body.numbers], 'feed_notice': FEED_NOTICE}

    @app.post('/api/watchlists', status_code=201)
    def create(body: Numbers):
        with sessions() as session:
            return create_watchlist(session, app.state.provider, body.numbers, 'paste')

    @app.post('/api/watchlists/sample', status_code=201)
    def sample():
        with sessions() as session:
            return create_watchlist(session, app.state.provider, SAMPLE_NUMBERS, 'sample')

    @app.post('/api/watchlists/csv', status_code=201)
    async def upload(file: UploadFile = File(...)):
        content = await file.read(200001)
        await file.close()
        if len(content) > 200000:
            raise HTTPException(413, 'CSV must be at most 200 KB.')
        try:
            reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')), strict=True)
            if reader.fieldnames != ['container_number']:
                raise ValueError('Use exactly one column named container_number.')
            numbers = []
            for row in reader:
                if None in row or not row.get('container_number') or len(row['container_number']) > 40:
                    raise ValueError('Every row must contain one container number of at most 40 characters.')
                numbers.append(row['container_number'])
                if len(numbers) > 100:
                    raise ValueError('Use at most 100 rows.')
            if not numbers:
                raise ValueError('The CSV contains no container numbers.')
        except (UnicodeDecodeError, csv.Error, ValueError) as exc:
            raise HTTPException(422, str(exc) if isinstance(exc, ValueError) else 'Use a valid UTF-8 CSV.') from None
        with sessions() as session:
            return create_watchlist(session, app.state.provider, numbers, 'csv')

    def active_watchlist(session, identifier):
        watchlist = session.get(Watchlist, str(identifier))
        if watchlist is None:
            raise HTTPException(404, 'Watchlist not found or expired. Run a new sample.')
        if watchlist.expires_at <= now():
            session.delete(watchlist)
            session.commit()
            raise HTTPException(404, 'Watchlist not found or expired. Run a new sample.')
        return watchlist

    @app.get('/api/watchlists/{identifier}')
    def watchlist(identifier: UUID):
        with sessions() as session:
            return watchlist_payload(active_watchlist(session, identifier))

    @app.get('/api/containers/{identifier}')
    def detail(identifier: UUID):
        with sessions() as session:
            container = session.get(Container, str(identifier))
            if container is None:
                raise HTTPException(404, 'Container not found or expired.')
            active_watchlist(session, container.watchlist_id)
            payload = container_payload(container, detail=True)
            if container.exceptions and not container.journey.get('explanation_attempted'):
                template = container.journey['explanation']
                enriched = explain(template, payload['exceptions'], settings)
                if settings.anthropic_api_key and settings.anthropic_model:
                    container.journey = {**container.journey, 'explanation': enriched, 'explanation_attempted': True}
                    session.commit()
                payload['explanation'] = enriched
            return payload

    @app.get('/api/meta/eval')
    def metrics():
        return {'benchmark': 'controlled synthetic benchmark', 'seed': 7, 'snapshot_date': '2026-08-03',
            'metrics': json.loads((ROOT / 'docs/benchmark/results.json').read_text()),
            'near_misses': json.loads((ROOT / 'docs/benchmark/near-misses.json').read_text()),
            'feed_notice': FEED_NOTICE}

    @app.post('/api/benchmark')
    def benchmark():
        return run_benchmark()

    return app


app = create_app()
