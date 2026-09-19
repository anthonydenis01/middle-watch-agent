import pytest
from api.services.validation import validate_number


@pytest.mark.parametrize('number,valid', [
    ('CSQU3054383', True), ('CSQU3054384', False), (' csqu3054383 ', True),
    ('CSQA3054383', False), ('', False), ('CSQU305438', False),
    ('CSQU30543833', False), ('CSQU３０５４３８３', False),
])
def test_iso6346(number, valid):
    result = validate_number(number)
    assert result['valid'] is valid
    assert bool(result['reason']) is not valid


def test_validate_endpoint(client):
    response = client.post('/api/validate', json={'numbers': ['CSQU3054383', 'CSQU3054384']})
    assert response.status_code == 200
    assert [x['valid'] for x in response.json()['results']] == [True, False]
    for numbers in ([], ['CSQU3054383'] * 101, ['x' * 41], [123]):
        assert client.post('/api/validate', json={'numbers': numbers}).status_code == 422


def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.json()['db'] == 'ok'
    assert response.json()['version'] == '2.0.0'
