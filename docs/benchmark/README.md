# Controlled synthetic benchmark

Baseline: 40,000 rows, seed 7, snapshot date 2026-08-03; original v1.0.0 engine and harness.
`results.json` records the measured run, including machine-dependent runtime.
Accuracy counts must match exactly; elapsed time is measured separately, never asserted equal.

```sh
python data/generate.py --rows 40000 --seed 7 --snapshot-date 2026-08-03 --out data/out/snapshot.jsonl
python scripts/evaluate.py --snapshot data/out/snapshot.jsonl
python scripts/benchmark_counts.py data/out/snapshot.jsonl
```

The harness calls false positives / reported incidents its false-positive rate.
This denominator differs from the conventional false positives / clean negatives.
Both are zero in this run; neither establishes accuracy on external data.
Near-miss categories overlap and may occur on containers with other injected families.
The `_clean` counts explicitly exclude every container with an injected family.
The generator and detectors share an author; this is reproducibility evidence, not independent validation.
