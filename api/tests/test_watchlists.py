from datetime import timedelta
from uuid import uuid4
from api.db.models import Container, Watchlist, now
from api.providers.simulated import SAMPLE_NUMBERS, SimulatedProvider


def test_provider_is_deterministic():
    provider = SimulatedProvider()
    assert provider.journey(SAMPLE_NUMBERS[0]) == provider.journey(SAMPLE_NUMBERS[0])
    assert provider.journey(SAMPLE_NUMBERS[0]) != provider.journey(SAMPLE_NUMBERS[1])


def test_sample_persists_timeline_and_evidence(client):
    response = client.post('/api/watchlists/sample')
    assert response.status_code == 201
    data = response.json()
    assert data['summary']['total'] == 25
    assert data['summary']['invalid'] == 0
    assert data['summary']['flagged'] > 0
    assert client.get('/api/watchlists/' + data['id']).json() == data
    flagged = next(row for row in data['containers'] if row['exceptions'])
    detail = client.get('/api/containers/' + flagged['id']).json()
    assert detail['events'] and detail['exceptions'][0]['evidence']
    assert detail['explanation']['source'] == 'template'
    assert detail['events'] == sorted(detail['events'], key=lambda e: e['ts'])


def test_invalid_number_never_calls_provider(client):
    class NoCalls:
        def journey(self, number):
            raise AssertionError('invalid input reached provider')
    client.app.state.provider = NoCalls()
    response = client.post('/api/watchlists', json={'numbers': ['BAD', 'CSQU3054384']})
    assert response.status_code == 201
    assert response.json()['summary']['invalid'] == 2
    assert client.post('/api/watchlists', json={'numbers': SAMPLE_NUMBERS * 5}).status_code == 422


def test_csv_limits_and_format(client):
    def upload(content):
        return client.post('/api/watchlists/csv', files={'file': ('sample.csv', content, 'text/csv')})
    assert upload('container_number\nCSQU3054383\nBAD').status_code == 201
    assert upload('wrong_header\nCSQU3054383').status_code == 422
    assert upload('container_number\n' + 'CSQU3054383\n' * 101).status_code == 422
    assert upload('x' * 200001).status_code == 413
    assert upload(b'container_number\n\xff').status_code == 422
    assert upload('container_number\n"unfinished').status_code == 422
    assert upload('container_number\na,b').status_code == 422
    assert upload('container_number\n').status_code == 422


def test_expired_watchlist_cascades_and_disappears(client):
    data = client.post('/api/watchlists/sample').json()
    with client.app.state.sessions() as session:
        session.get(Watchlist, data['id']).expires_at = now() - timedelta(seconds=1)
        session.commit()
    assert client.get('/api/containers/' + data['containers'][0]['id']).status_code == 404
    with client.app.state.sessions() as session:
        assert session.get(Container, data['containers'][0]['id']) is None
    assert client.get('/api/watchlists/' + str(uuid4())).status_code == 404


def test_eval_metadata(client):
    data = client.get('/api/meta/eval').json()
    assert data['benchmark'] == 'controlled synthetic benchmark'
    assert data['metrics']['caught'] == 2393
    assert data['near_misses']['dwell_not_injected'] == 12460
