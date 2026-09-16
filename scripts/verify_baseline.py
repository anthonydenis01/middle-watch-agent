"""Compare the unchanged engine/harness and observable near-misses with P0."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.generate import main as generate
from scripts.evaluate import evaluate
from scripts.benchmark_counts import count

with tempfile.TemporaryDirectory() as directory:
    snapshot = Path(directory) / 'snapshot.jsonl'
    generate(['--rows', '40000', '--seed', '7', '--snapshot-date', '2026-08-03', '--out', str(snapshot)])
    actual = evaluate(str(snapshot))
    expected = json.loads((ROOT / 'docs/benchmark/results.json').read_text())
    differences = {key: value for key, value in actual.items() if key not in ('snapshot', 'runtime_seconds') and value != expected[key]}
    assert not differences, f'Baseline differences: {differences}'
    assert count(snapshot) == json.loads((ROOT / 'docs/benchmark/near-misses.json').read_text())
    print('PASS: controlled synthetic benchmark: 40,000 rows; 2,393/2,393 caught; 0 false positives; all family and near-miss counts equal P0.')
