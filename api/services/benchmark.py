"""Fixed, synthetic-only evaluation input. Ground truth never enters detection."""
from functools import lru_cache
import random
from threading import Lock
from data.generate import build_accounts, generate_record
from api.detectors import detect
from api.providers.simulated import SNAPSHOT

_lock = Lock()


@lru_cache(maxsize=1)
def _run():
    rng = random.Random(7)
    accounts = build_accounts(rng, 180)
    rates = {'routing_change': .012, 'vessel_swap': .015, 'dwell': .010, 'eta_drift': .020, 'transit_time': .010}
    records = (generate_record(rng, accounts, SNAPSHOT, rates, False)[0] for _ in range(40000))
    result = detect(records)
    def compact(incident):
        return {'container_id': incident.container_id, 'families': incident.families}
    return {'rows': result.rows, 'reported': [compact(i) for i in result.incidents],
        'suppressed': [compact(i) for i in result.suppressed], 'family_counts': result.family_counts,
        'runtime_seconds': round(result.runtime_seconds, 2), 'benchmark': 'controlled synthetic benchmark',
        'seed': 7, 'snapshot_date': '2026-08-03'}


def run_benchmark():
    with _lock:
        return _run()
