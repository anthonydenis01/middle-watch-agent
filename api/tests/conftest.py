import pytest
from fastapi.testclient import TestClient
from api.config import Settings
from api.db.models import Base
from api.main import create_app


@pytest.fixture
def client():
    app = create_app(Settings(database_url='sqlite:///:memory:'))
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as client:
        yield client
