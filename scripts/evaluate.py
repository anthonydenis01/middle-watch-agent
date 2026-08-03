#!/usr/bin/env python3
"""
Measure detection quality against the generator's ground truth.

    python scripts/evaluate.py --snapshot data/out/snapshot.jsonl

Definitions used here — stated up front, because a recall number without its
definition is marketing:

  * A container is DIRTY if the generator injected at least one exception into it,
    CLEAN otherwise. The ground-truth file is never read by the detection path.
  * **Detection recall** — dirty containers that produced a reported incident,
    over all dirty containers. This is the "did we catch it" number.
  * **Family recall** — injected (container, family) pairs where that family
    appears among the incident's signals, over all injected pairs. Stricter: it
    checks we caught it *for the right reason*.
  * **False-positive rate** — reported incidents on CLEAN containers, over all
    reported incidents. Extra families firing on a DIRTY container are not
    counted as false positives: a routing change that adds six days genuinely
    does move the ETA, and reporting that is correct behaviour, not noise.
  * **Benign near-miss rows** — the generator deliberately fills the file with
    sub-threshold noise (ETA jitter, voyage renumbering, equivalent-hub swaps,
    long-but-legal dwell). Every one of those is a CLEAN container, so anything
    the detector raises on them lands in the false-positive count.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from middlewatch import FAMILIES                     # noqa: E402
from middlewatch.config import load_config           # noqa: E402
from middlewatch.engine import analyze               # noqa: E402


def evaluate(snapshot: str, config_path: str | None = None,
             truth_path: str | None = None) -> dict:
    config = load_config(config_path)
    truth_file = Path(truth_path or f"{snapshot}.ground_truth.json")
    if not truth_file.exists():
        raise SystemExit(f"ground truth not found: {truth_file}\n"
                         f"generate the snapshot with data/generate.py first.")
    truth = json.loads(truth_file.read_text())
    injected: dict[str, list[str]] = truth["containers"]

    result = analyze(snapshot, config, keep_containers=False)
    reported = {i.container_id: i for i in result.incidents}
    suppressed = {i.container_id: i for i in result.suppressed}

    dirty = set(injected)
    caught = dirty & set(reported)
    missed = sorted(dirty - set(reported))
    caught_but_suppressed = sorted((dirty - set(reported)) & set(suppressed))

    false_positives = [cid for cid in reported if cid not in dirty]

    fam_total: Counter = Counter()
    fam_caught: Counter = Counter()
    fam_missed: dict[str, list[str]] = {f: [] for f in FAMILIES}
    for cid, fams in injected.items():
        inc = reported.get(cid) or suppressed.get(cid)
        signals = set(inc.families) if inc else set()
        for fam in fams:
            fam_total[fam] += 1
            if fam in signals:
                fam_caught[fam] += 1
            else:
                fam_missed[fam].append(cid)

    total_pairs = sum(fam_total.values())
    caught_pairs = sum(fam_caught.values())

    return {
        "snapshot": snapshot,
        "rows": result.rows,
        "runtime_seconds": round(result.runtime_seconds, 2),
        "dirty_containers": len(dirty),
        "clean_containers": result.rows - len(dirty),
        "reported": len(reported),
        "suppressed_below_severity_floor": len(suppressed),
        "caught": len(caught),
        "missed": len(missed),
        "recall_pct": round(len(caught) / len(dirty) * 100, 2) if dirty else 100.0,
        "family_recall_pct": round(caught_pairs / total_pairs * 100, 2) if total_pairs else 100.0,
        "false_positives": len(false_positives),
        "false_positive_pct": round(len(false_positives) / len(reported) * 100, 2)
        if reported else 0.0,
        "injected": len(dirty),
        "per_family": [{
            "family": f,
            "injected": fam_total.get(f, 0),
            "caught": fam_caught.get(f, 0),
            "recall_pct": round(fam_caught.get(f, 0) / fam_total[f] * 100, 2)
            if fam_total.get(f) else 100.0,
            "reported_findings_total": result.family_counts.get(f, 0),
        } for f in FAMILIES],
        "missed_container_ids": missed[:25],
        "missed_only_because_suppressed": caught_but_suppressed[:25],
        "false_positive_container_ids": false_positives[:25],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--config", default=None)
    p.add_argument("--truth", default=None)
    p.add_argument("--json", dest="json_out", default=None)
    args = p.parse_args(argv)

    m = evaluate(args.snapshot, args.config, args.truth)

    print("=" * 78)
    print(" MIDDLE WATCH — detection quality")
    print("=" * 78)
    print(f" snapshot            : {m['snapshot']}")
    print(f" containers          : {m['rows']:,}  "
          f"({m['dirty_containers']} with injected exceptions, {m['clean_containers']:,} clean)")
    print(f" runtime             : {m['runtime_seconds']}s")
    print("-" * 78)
    print(f" incidents reported  : {m['reported']}   "
          f"(+{m['suppressed_below_severity_floor']} suppressed below the severity floor)")
    print(f" DETECTION RECALL    : {m['recall_pct']}%   "
          f"({m['caught']}/{m['dirty_containers']} containers, {m['missed']} missed)")
    print(f" FAMILY RECALL       : {m['family_recall_pct']}%   "
          f"(caught for the right reason)")
    print(f" FALSE POSITIVES     : {m['false_positive_pct']}%   "
          f"({m['false_positives']}/{m['reported']} reported incidents on clean containers)")
    print("-" * 78)
    print(f" {'family':<18}{'injected':>10}{'caught':>9}{'recall':>9}{'findings raised':>18}")
    for row in m["per_family"]:
        print(f" {row['family']:<18}{row['injected']:>10}{row['caught']:>9}"
              f"{row['recall_pct']:>8.1f}%{row['reported_findings_total']:>18}")
    print("-" * 78)
    print(" 'findings raised' exceeds 'injected' where one injected exception has real")
    print(" downstream consequences — a reroute that adds six days genuinely does move")
    print(" the ETA. Those are grouped into the same incident, not counted as separate")
    print(" alerts, and they are not false positives.")
    if m["missed_container_ids"]:
        print(f" missed: {', '.join(m['missed_container_ids'])}")
    if m["false_positive_container_ids"]:
        print(f" false positives: {', '.join(m['false_positive_container_ids'])}")
    print("=" * 78)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(m, indent=2))
        print(f"wrote metrics -> {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
