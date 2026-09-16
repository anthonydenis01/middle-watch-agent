import json
import httpx
from api.config import Settings
from api.explain import explain
from api.notify import send_alert

TEMPLATE = {'source': 'template', 'text': 'Rule evidence.', 'action': 'Review evidence.', 'draft_message': 'Simulated update.'}
WATCHLIST = {'id': 'synthetic-watchlist', 'summary': {'total': 25, 'flagged': 7, 'invalid': 0}}


def configured():
    return Settings(anthropic_api_key='test-only', anthropic_model='test-model',
        resend_api_key='test-only', alert_from='sender@example.test', alert_to='recipient@example.test')


def test_no_keys_no_network():
    def forbidden(request):
        raise AssertionError('network attempted without keys')
    transport = httpx.MockTransport(forbidden)
    settings = Settings(anthropic_api_key='', resend_api_key='')
    assert explain(TEMPLATE, [], settings, transport) == TEMPLATE
    assert send_alert(WATCHLIST, settings, transport)['status'] == 'disabled'


def test_explanation_success_only_changes_narrative():
    def respond(request):
        data = json.loads(request.content)
        assert data['model'] == 'test-model'
        assert request.headers['anthropic-version'] == '2023-06-01'
        return httpx.Response(200, json={'content': [{'type': 'text', 'text': json.dumps({
            'text': 'Evidence summary.', 'action': 'Check evidence.', 'draft_message': 'Synthetic example.', 'severity': 0})}]})
    result = explain(TEMPLATE, [{'severity': 80}], configured(), httpx.MockTransport(respond))
    assert result['source'] == 'model'
    assert result['draft_message'].startswith('Simulated update')
    assert 'severity' not in result


def test_explanation_falls_back_on_timeout_bad_shape_and_error():
    def timeout(request):
        raise httpx.ReadTimeout('private-provider-detail')
    for handler in (timeout, lambda r: httpx.Response(429), lambda r: httpx.Response(200, json={'content': []}),
            lambda r: httpx.Response(200, json={'content': [{'type': 'text', 'text': '[]'}]})):
        assert explain(TEMPLATE, [], configured(), httpx.MockTransport(handler)) == TEMPLATE


def test_notification_uses_fixed_recipient_and_idempotency():
    def respond(request):
        data = json.loads(request.content)
        assert data['to'] == ['recipient@example.test']
        assert 'Simulated feed' in data['text']
        assert request.headers['idempotency-key'] == 'watchlist-synthetic-watchlist'
        return httpx.Response(200, json={'id': 'test-message'})
    assert send_alert(WATCHLIST, configured(), httpx.MockTransport(respond))['status'] == 'sent'
    result = send_alert(WATCHLIST, configured(), httpx.MockTransport(lambda r: httpx.Response(503)))
    assert result['status'] == 'unavailable'


def test_detail_caches_optional_explanation(client, monkeypatch):
    calls = []
    client.app.state.settings.anthropic_api_key = 'test-only'
    client.app.state.settings.anthropic_model = 'test-model'
    def fake(template, evidence, settings):
        calls.append(evidence)
        return {**template, 'source': 'model'}
    monkeypatch.setattr('api.main.explain', fake)
    rows = client.post('/api/watchlists/sample').json()['containers']
    row = next(r for r in rows if r['exceptions'])
    for _ in range(2):
        response = client.get('/api/containers/' + row['id'])
        assert response.json()['explanation']['source'] == 'model'
    assert len(calls) == 1
