"""Operator-invoked email only; no public send endpoint or visitor recipients."""
import httpx
from api.config import FEED_NOTICE


def send_alert(watchlist, settings, transport=None):
    if not all((settings.resend_api_key, settings.alert_from, settings.alert_to)):
        return {'status': 'disabled', 'message': 'Email is not configured; inspect the watchlist in the demo.'}
    summary = watchlist['summary']
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.post('https://api.resend.com/emails', headers={
                'Authorization': f'Bearer {settings.resend_api_key}',
                'Idempotency-Key': f'watchlist-{watchlist["id"]}'}, json={
                'from': settings.alert_from, 'to': [settings.alert_to],
                'subject': 'Middle Watch simulated watchlist summary',
                'text': f'{FEED_NOTICE}\n\n{summary["total"]} containers; {summary["flagged"]} flagged; '
                    f'{summary["invalid"]} invalid. Review the rule evidence before taking action.'})
            response.raise_for_status()
            return {'status': 'sent', 'message': 'Simulated summary sent to the configured recipient.'}
    except httpx.HTTPError:
        return {'status': 'unavailable', 'message': 'Email unavailable; the watchlist remains available in the demo.'}
