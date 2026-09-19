"""Exercise an ephemeral CI Postgres database after migrations; no external feed."""
from datetime import timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from api.config import Settings
from api.db.models import Container, Event, ExceptionRecord, Watchlist, now
from api.deploy import prepare
from api.main import create_app
from api.services.retention import cleanup


def main():
    settings = Settings()
    assert settings.database_url.startswith('postgresql+psycopg://'), 'This smoke check requires the CI Postgres database.'
    prepare()
    prepare()
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get('/health').json()['db'] == 'ok'
        response = client.post('/api/watchlists/sample')
        assert response.status_code == 201
        data = response.json()
        assert data['summary']['total'] == 25
        flagged = next(row for row in data['containers'] if row['exceptions'])
        detail = client.get('/api/containers/' + flagged['id']).json()
        assert detail['events'] and detail['exceptions'][0]['evidence']
        with app.state.sessions() as session:
            session.get(Watchlist, data['id']).expires_at = now() - timedelta(seconds=1)
            session.commit()
        assert cleanup(app.state.sessions) >= 1
        assert client.get('/api/watchlists/' + data['id']).status_code == 404
        with app.state.sessions() as session:
            for model in (Container, Event, ExceptionRecord):
                assert session.scalar(select(func.count()).select_from(model)) == 0
    print('PASS: Postgres repeatable migration, sample, evidence and cascading retention.')


if __name__ == '__main__':
    main()
