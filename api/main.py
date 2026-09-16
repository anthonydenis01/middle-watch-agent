from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.responses import JSONResponse
from api.config import FEED_NOTICE, Settings, VERSION
from api.db import connect
from api.services.validation import validate_number


class Numbers(BaseModel):
    model_config = ConfigDict(extra='forbid')
    numbers: list[Annotated[str, StringConstraints(max_length=40)]] = Field(min_length=1, max_length=100)


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine, sessions = connect(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title='Middle Watch API', version=VERSION, description=FEED_NOTICE, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions

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

    return app


app = create_app()
