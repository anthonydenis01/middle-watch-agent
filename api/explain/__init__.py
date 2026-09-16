"""Optional explanation of existing evidence; never alters detector decisions."""
import json
import httpx


def explain(template, evidence, settings, transport=None):
    if not settings.anthropic_api_key or not settings.anthropic_model:
        return dict(template)
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.post('https://api.anthropic.com/v1/messages', headers={
                'x-api-key': settings.anthropic_api_key, 'anthropic-version': '2023-06-01'}, json={
                'model': settings.anthropic_model, 'max_tokens': 600,
                'system': 'Explain only the supplied synthetic rule evidence. Do not invent facts, claim live tracking, '
                    'or change severity. Return only a JSON object with text, action, and draft_message strings. '
                    'The draft must say this is a simulated update requiring human review.',
                'messages': [{'role': 'user', 'content': json.dumps({'template': template, 'evidence': evidence})}]})
            response.raise_for_status()
            blocks = response.json()['content']
            result = json.loads(''.join(b['text'] for b in blocks if b.get('type') == 'text'))
            if not isinstance(result, dict) or any(not isinstance(result.get(k), str) or
                    not result[k].strip() or len(result[k]) > 3000 for k in ('text', 'action', 'draft_message')):
                return dict(template)
            return {'source': 'model', 'text': result['text'], 'action': result['action'],
                'draft_message': 'Simulated update — human review required. ' + result['draft_message']}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return dict(template)
