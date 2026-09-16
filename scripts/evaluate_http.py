"""Reproduce the original benchmark through HTTP, comparing every accuracy field.

Use --url https://api.themiddlewatch.com for the release check; default is TestClient.
The HTTP service sees synthetic inputs only, never ground-truth labels.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from middlewatch import FAMILIES
from data.generate import main as generate


def evaluate_http(client, snapshot):
    response = client.post('/api/benchmark')
    response.raise_for_status()
    result = response.json()
    truth = json.loads(Path(str(snapshot) + '.ground_truth.json').read_text())['containers']
    reported = {i['container_id']: i for i in result['reported']}
    suppressed = {i['container_id']: i for i in result['suppressed']}
    dirty = set(truth)
    caught = dirty & set(reported)
    false_positives = [cid for cid in reported if cid not in dirty]
    totals, caught_families = Counter(), Counter()
    for cid, families in truth.items():
        incident = reported.get(cid) or suppressed.get(cid) or {'families': []}
        for family in families:
            totals[family] += 1
            caught_families[family] += family in incident['families']
    return {'rows': result['rows'], 'dirty_containers': len(dirty), 'clean_containers': result['rows'] - len(dirty),
        'reported': len(reported), 'suppressed_below_severity_floor': len(suppressed),
        'caught': len(caught), 'missed': len(dirty - set(reported)), 'injected': len(dirty),
        'recall_pct': round(len(caught) / len(dirty) * 100, 2),
        'family_recall_pct': round(sum(caught_families.values()) / sum(totals.values()) * 100, 2),
        'false_positives': len(false_positives), 'false_positive_pct': round(len(false_positives) / max(len(reported), 1) * 100, 2),
        'per_family': [{'family': f, 'injected': totals[f], 'caught': caught_families[f],
            'recall_pct': round(caught_families[f] / totals[f] * 100, 2), 'reported_findings_total': result['family_counts'][f]} for f in FAMILIES],
        'missed_container_ids': sorted(dirty - set(reported))[:25],
        'missed_only_because_suppressed': sorted((dirty - set(reported)) & set(suppressed))[:25],
        'false_positive_container_ids': false_positives[:25]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        snapshot = Path(directory) / 'benchmark.jsonl'
        generate(['--rows', '40000', '--seed', '7', '--snapshot-date', '2026-08-03', '--out', str(snapshot)])
        if args.url:
            import httpx
            client = httpx.Client(base_url=args.url.rstrip('/'), timeout=120)
        else:
            from fastapi.testclient import TestClient
            from api.main import create_app
            from api.config import Settings
            client = TestClient(create_app(Settings(database_url='sqlite:///:memory:')))
        started = time.perf_counter()
        with client:
            actual = evaluate_http(client, snapshot)
        expected = json.loads((ROOT / 'docs/benchmark/results.json').read_text())
        differences = {key: {'expected': expected[key], 'actual': value} for key, value in actual.items() if expected[key] != value}
        print(json.dumps({'benchmark': 'controlled synthetic benchmark', 'http_seconds': round(time.perf_counter() - started, 2), 'metrics': actual, 'differences': differences}, indent=2))
        if differences:
            raise SystemExit('HTTP accuracy differs from P0; investigate before proceeding.')
        print('PASS: every HTTP accuracy count matches P0. Runtime is machine-dependent.')


if __name__ == '__main__':
    main()
