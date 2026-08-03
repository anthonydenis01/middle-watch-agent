"""The detection run: snapshot in, ranked incidents out.

This layer is deliberately deterministic and LLM-free. It streams the snapshot
once, runs every enabled detector on every row, groups the findings per container
into incidents, scores them and ranks them. Reproducible, auditable, fast enough
that 40,000 containers finish in seconds rather than minutes.

The model sits ON TOP of this (see agent.py) — it orchestrates these detectors as
tools, drills into what it wants to see and writes the triage narrative for the
containers it escalates. It never replaces the evidence.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import FAMILIES
from .config import Config
from .detectors import run_detectors
from .loader import Container, load_containers
from .models import Incident
from .severity import build_incident


@dataclass
class RunResult:
    snapshot_path: str
    snapshot_date: str
    rows: int
    incidents: list[Incident]                     # reported, ranked
    suppressed: list[Incident]                    # below min_severity_to_report
    family_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    runtime_seconds: float = 0.0
    config_summary: dict[str, Any] = field(default_factory=dict)
    containers_by_id: dict[str, Container] = field(default_factory=dict, repr=False)

    # -- rollups ------------------------------------------------------------ #
    def account_rollup(self, limit: int = 0) -> list[dict[str, Any]]:
        buckets: dict[str, dict[str, Any]] = {}
        for inc in self.incidents:
            b = buckets.setdefault(inc.account_id, {
                "account_id": inc.account_id,
                "account_name": inc.account_name,
                "account_tier": inc.account_tier,
                "incidents": 0,
                "critical": 0,
                "high": 0,
                "max_severity": 0,
                "families": Counter(),
                "containers": [],
            })
            b["incidents"] += 1
            b["max_severity"] = max(b["max_severity"], inc.severity)
            if inc.band == "critical":
                b["critical"] += 1
            elif inc.band == "high":
                b["high"] += 1
            b["families"][inc.primary_family] += 1
            if len(b["containers"]) < 25:
                b["containers"].append(inc.container_id)
        rows = sorted(buckets.values(),
                      key=lambda b: (-b["critical"], -b["incidents"], -b["max_severity"]))
        for r in rows:
            r["families"] = dict(r["families"])
        return rows[:limit] if limit else rows

    def band_counts(self) -> dict[str, int]:
        c = Counter(i.band for i in self.incidents)
        return {b: c.get(b, 0) for b in ("critical", "high", "medium", "low")}

    def top(self, limit: int = 25, family: str | None = None,
            account_id: str | None = None) -> list[Incident]:
        out = self.incidents
        if family:
            out = [i for i in out if family in i.families]
        if account_id:
            out = [i for i in out if i.account_id == account_id]
        return out[:limit] if limit else out

    def summary(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot_path,
            "snapshot_date": self.snapshot_date,
            "containers_scanned": self.rows,
            "incidents_reported": len(self.incidents),
            "incidents_suppressed_below_threshold": len(self.suppressed),
            "by_band": self.band_counts(),
            "by_family": self.family_counts,
            "accounts_affected": len({i.account_id for i in self.incidents}),
            "runtime_seconds": round(self.runtime_seconds, 2),
            "config": self.config_summary,
        }


def analyze(snapshot_path: str | Path, config: Config,
            families: list[str] | None = None,
            keep_containers: bool = True,
            containers: Iterable[Container] | None = None) -> RunResult:
    """Run every enabled detector over the snapshot and rank what comes out."""
    started = time.perf_counter()
    incidents: list[Incident] = []
    suppressed: list[Incident] = []
    family_counts: Counter = Counter()
    status_counts: Counter = Counter()
    by_id: dict[str, Container] = {}
    rows = 0
    snapshot_date = ""

    source = containers if containers is not None else load_containers(snapshot_path)
    for c in source:
        rows += 1
        if not snapshot_date:
            snapshot_date = c.raw.get("snapshot_date", "")
        status_counts[c.status] += 1
        findings = run_detectors(c, config, families)
        if not findings:
            continue
        for f in findings:
            family_counts[f.family] += 1
        inc = build_incident(c, findings, config)
        if keep_containers:
            by_id[c.container_id] = c
        (suppressed if inc.suppressed else incidents).append(inc)

    incidents.sort(key=lambda i: (-i.severity, i.days_to_arrival))
    cap = int(config.get("general.max_incidents_reported", 0) or 0)
    if cap:
        overflow = incidents[cap:]
        incidents = incidents[:cap]
        suppressed.extend(overflow)

    return RunResult(
        snapshot_path=str(snapshot_path),
        snapshot_date=snapshot_date,
        rows=rows,
        incidents=incidents,
        suppressed=suppressed,
        family_counts={f: family_counts.get(f, 0) for f in FAMILIES},
        status_counts=dict(status_counts),
        runtime_seconds=time.perf_counter() - started,
        config_summary=config.summary(),
        containers_by_id=by_id,
    )


def detector_stats(result: RunResult) -> list[dict[str, Any]]:
    """Per-family view: how much of the queue each detector is responsible for."""
    primary = Counter(i.primary_family for i in result.incidents)
    contributing = Counter()
    for i in result.incidents:
        for fam in i.families:
            if fam != i.primary_family:
                contributing[fam] += 1
    sev = defaultdict(list)
    for i in result.incidents:
        sev[i.primary_family].append(i.severity)
    return [{
        "family": fam,
        "findings": result.family_counts.get(fam, 0),
        "as_primary": primary.get(fam, 0),
        "as_contributing_signal": contributing.get(fam, 0),
        "mean_severity_when_primary": round(sum(sev[fam]) / len(sev[fam]), 1) if sev[fam] else 0,
    } for fam in FAMILIES]
