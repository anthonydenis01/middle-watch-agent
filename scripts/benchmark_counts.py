"""Count observable near-misses without changing the generator or eval harness."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from middlewatch.loader import Container, iter_records
from middlewatch.config import load_config


def count(snapshot):
    truth = json.loads(Path(str(snapshot) + '.ground_truth.json').read_text())['containers']
    groups = load_config().get('routing_change.equivalent_hubs').values()
    counts = Counter()
    for raw in iter_records(snapshot):
        c = Container(raw)
        clean = c.container_id not in truth
        def record(name):
            counts[name] += 1
            if clean:
                counts[name + '_clean'] += 1
        if abs((c.current_eta - c.booked_eta).total_seconds()) < 24 * 3600 and abs((c.current_eta - c.previous_eta).total_seconds()) < 12 * 3600:
            record('eta_jitter')
        if c.booked['vessel_name'] == c.current['vessel_name'] and c.booked['voyage'] != c.current['voyage']:
            record('voyage_renumber')
        booked_hubs = [leg['to_port'] for leg in c.booked['routing'][:-1]]
        current_hubs = [leg['to_port'] for leg in c.current['routing'][:-1]]
        if len(booked_hubs) == len(current_hubs) == 1 and booked_hubs != current_hubs and any(set(booked_hubs + current_hubs) <= set(g) for g in groups):
            record('equivalent_hub')
        limits = {'AT_ORIGIN_TERMINAL': 96, 'AT_TRANSSHIPMENT': 120, 'AT_DESTINATION_TERMINAL': 72}
        if c.status in limits:
            counts['dwell_eligible'] += 1
            if 'dwell' not in truth.get(c.container_id, []):
                record('dwell_not_injected')
            ts, _, kind = c.last_event()
            if kind in ('GATE_IN', 'DISCHARGED') and 0 <= c.hours_since(ts) < limits[c.status]:
                record('open_dwell_below_base_limit')
    return dict(counts)


if __name__ == '__main__':
    print(json.dumps(count(sys.argv[1]), indent=2))
