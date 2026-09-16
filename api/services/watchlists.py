from datetime import timedelta
from api.config import FEED_NOTICE
from api.db.models import Container, Event, ExceptionRecord, Watchlist, now
from api.detectors import detect
from api.services.validation import validate_number

NEXT = {'AT_ORIGIN_TERMINAL': 'Vessel departure', 'ON_WATER': 'Next port arrival',
        'AT_TRANSSHIPMENT': 'Onward vessel loading', 'AT_DESTINATION_TERMINAL': 'Gate out'}


def create_watchlist(session, provider, numbers, source):
    watchlist = Watchlist(expires_at=now() + timedelta(hours=24), source=source)
    session.add(watchlist)
    for value in dict.fromkeys(numbers):
        validation = validate_number(value)
        container = Container(number=validation['number'], valid=validation['valid'], invalid_reason=validation['reason'])
        watchlist.containers.append(container)
        if not container.valid:
            continue
        raw = provider.journey(container.number)
        result = detect([raw])
        container.status = raw['status']
        container.eta = raw['current']['eta']
        container.next_milestone = NEXT.get(container.status, 'Journey update')
        container.journey = {'snapshot_date': raw['snapshot_date'], 'origin': raw['booked']['origin_port'],
            'destination': raw['current']['destination_port'], 'booked_eta': raw['booked']['eta'],
            'explanation': {'source': 'template', 'text': 'No exception crossed the reporting threshold.', 'draft_message': ''}}
        for event in raw['port_events']:
            container.events.append(Event(ts=event['timestamp'], code=event['event'], location_unlocode=event['port'],
                vessel=raw['current']['vessel_name'], voyage=raw['current']['voyage'], raw=event))
        for incident in result.incidents:
            container.journey['explanation'] = {'source': 'template', 'text': incident.why_it_matters,
                'action': incident.recommended_action, 'draft_message': f'Simulated update for {container.number}: {incident.what_changed} Please review the evidence before taking action.'}
            for finding in incident.findings:
                container.exceptions.append(ExceptionRecord(family=finding.family, severity=incident.severity,
                    title=finding.headline, evidence_json=[item.to_dict() for item in finding.evidence],
                    rule_id=f'config/thresholds.toml#{finding.family}'))
    session.commit()
    return watchlist_payload(watchlist)


def container_payload(container, detail=False):
    result = {name: getattr(container, name) for name in ('id', 'number', 'valid', 'invalid_reason', 'carrier_label', 'status', 'eta', 'next_milestone')}
    result['exceptions'] = [{name: getattr(e, name) for name in ('family', 'severity', 'title', 'rule_id')} |
        ({'evidence': e.evidence_json} if detail else {}) for e in container.exceptions]
    result['severity'] = max((e.severity for e in container.exceptions), default=0)
    result['band'] = ('critical' if result['severity'] >= 80 else 'high' if result['severity'] >= 60 else 'medium' if result['severity'] >= 40 else 'clear')
    result['feed_notice'] = FEED_NOTICE
    if detail:
        result.update(container.journey)
        result['events'] = [{name: getattr(e, name) for name in ('ts', 'code', 'location_unlocode', 'vessel', 'voyage')} for e in sorted(container.events, key=lambda e: e.ts)]
    return result


def watchlist_payload(watchlist):
    rows = sorted((container_payload(c) for c in watchlist.containers), key=lambda c: (-c['severity'], c['number']))
    return {'id': watchlist.id, 'created_at': watchlist.created_at.isoformat() + 'Z',
        'expires_at': watchlist.expires_at.isoformat() + 'Z', 'source': watchlist.source,
        'summary': {'total': len(rows), 'invalid': sum(not c['valid'] for c in rows), 'flagged': sum(bool(c['exceptions']) for c in rows)},
        'containers': rows, 'feed_notice': FEED_NOTICE}
