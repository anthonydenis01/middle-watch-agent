"""HTTP boundary checks for the public demo's input contract."""
import pytest
from api.providers.simulated import SAMPLE_NUMBERS


@pytest.mark.parametrize('number', SAMPLE_NUMBERS)
def test_each_sample_number_passes_http_validation(client, number):
    result = client.post('/api/validate', json={'numbers': [number]})
    assert result.status_code == 200
    assert result.json()['results'][0]['valid'] is True


@pytest.mark.parametrize('endpoint', ['/api/validate', '/api/watchlists'])
@pytest.mark.parametrize('body', [{}, {'numbers': []}, {'numbers': None},
    {'numbers': 'CSQU3054383'}, {'numbers': [None]}, {'numbers': ['x' * 41]},
    {'numbers': ['CSQU3054383'], 'unexpected': True}])
def test_http_body_rejects_invalid_shapes(client, endpoint, body):
    assert client.post(endpoint, json=body).status_code == 422
