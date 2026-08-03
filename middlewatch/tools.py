"""The tool layer.

One definition, three consumers:

  * `agent.py`      — Claude API tool-calling loop
  * `mcp_server.py` — the same tools over MCP, for any MCP client
  * `cli.py`        — the deterministic path calls the same functions directly

Every tool is a thin, side-effect-free wrapper over the detection engine, and
every tool that returns findings returns their field-level evidence with them.
The model is never asked to eyeball 40,000 rows: it asks a detector a question
and gets a summary plus a bounded sample back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import FAMILIES, FAMILY_LABELS
from .config import Config
from .detectors import DETECTOR_DOCS, run_detectors
from .engine import RunResult, analyze, detector_stats
from .loader import Container, iter_records, load_containers
from .models import Incident
from .severity import build_incident
from .triage import annotate


# --------------------------------------------------------------------------- #
# Session
# --------------------------------------------------------------------------- #

class ToolSession:
    """Holds the snapshot + config a set of tool calls operates on."""

    def __init__(self, snapshot_path: str | Path, config: Config,
                 max_sample: int = 10):
        self.path = str(snapshot_path)
        self.config = config
        self.max_sample = max_sample
        self._full: RunResult | None = None
        self._family_cache: dict[str, dict[str, Any]] = {}
        self._offsets: dict[str, int] | None = None
        self.report: dict[str, Any] | None = None      # set by emit_report
        self.call_log: list[dict[str, Any]] = []

    # -- internals ---------------------------------------------------------- #
    def full(self) -> RunResult:
        if self._full is None:
            self._full = analyze(self.path, self.config, keep_containers=False)
        return self._full

    def _offset_index(self) -> dict[str, int]:
        if self._offsets is None:
            self._offsets = {}
            if self.path.endswith(".jsonl"):
                marker = b'"container_id":"'
                with open(self.path, "rb") as fh:
                    offset = 0
                    for raw in fh:
                        i = raw.find(marker)
                        if i != -1:
                            start = i + len(marker)
                            end = raw.find(b'"', start)
                            self._offsets[raw[start:end].decode()] = offset
                        offset += len(raw)
        return self._offsets

    def container(self, container_id: str) -> Container | None:
        idx = self._offset_index()
        if container_id in idx:
            with open(self.path, "rb") as fh:
                fh.seek(idx[container_id])
                return Container(json.loads(fh.readline().decode()))
        for raw in iter_records(self.path):
            if raw.get("container_id") == container_id:
                return Container(raw)
        return None

    # -- tools -------------------------------------------------------------- #
    def describe_snapshot(self) -> dict[str, Any]:
        r = self.full()
        return {
            "snapshot_file": self.path,
            "snapshot_date": r.snapshot_date,
            "containers_scanned": r.rows,
            "status_breakdown": r.status_counts,
            "accounts_in_file": len({i.account_id for i in r.incidents + r.suppressed}),
            "findings_by_family": r.family_counts,
            "incidents_reported": len(r.incidents),
            "incidents_suppressed_below_severity_threshold": len(r.suppressed),
            "severity_bands": r.band_counts(),
            "thresholds_in_effect": r.config_summary,
            "engine_runtime_seconds": round(r.runtime_seconds, 2),
        }

    def list_detectors(self) -> dict[str, Any]:
        return {
            "detectors": [{
                "family": fam,
                "label": FAMILY_LABELS[fam],
                "enabled": self.config.enabled(fam),
                "what_it_does": " ".join((DETECTOR_DOCS.get(fam, "").strip()
                                          .split("\n\n")[0]).split()),
                "thresholds": self.config.section(fam),
            } for fam in FAMILIES],
            "grouping": self.config.section("grouping"),
        }

    def run_detector(self, family: str, limit: int | None = None,
                     account_id: str | None = None) -> dict[str, Any]:
        if family not in FAMILIES:
            return {"error": f"unknown family '{family}'. Valid: {list(FAMILIES)}"}
        if not self.config.enabled(family):
            return {"family": family, "enabled": False, "findings": 0,
                    "note": "detector disabled in config"}

        limit = limit or self.max_sample
        cache_key = f"{family}:{account_id or '*'}"
        if cache_key in self._family_cache:
            cached = self._family_cache[cache_key]
        else:
            findings_count = 0
            magnitudes: list[float] = []
            samples: list[dict[str, Any]] = []
            containers_hit = 0
            for c in load_containers(self.path):
                if account_id and c.account_id != account_id:
                    continue
                fs = run_detectors(c, self.config, [family])
                if not fs:
                    continue
                containers_hit += 1
                for f in fs:
                    findings_count += 1
                    magnitudes.append(f.magnitude)
                inc = build_incident(c, fs, self.config)
                samples.append({
                    "container_id": c.container_id,
                    "account": c.account_name,
                    "tier": c.account_tier,
                    "lane": c.lane,
                    "status": c.status,
                    "severity_if_isolated": inc.severity,
                    "headline": fs[0].headline,
                    "magnitude": round(fs[0].magnitude, 2),
                    "metrics": fs[0].metrics,
                    "evidence": [e.to_dict() for e in fs[0].evidence],
                })
            samples.sort(key=lambda s: -s["severity_if_isolated"])
            cached = {
                "family": family,
                "label": FAMILY_LABELS[family],
                "containers_flagged": containers_hit,
                "findings": findings_count,
                "mean_magnitude": round(sum(magnitudes) / len(magnitudes), 3)
                if magnitudes else 0.0,
                "thresholds_applied": self.config.section(family),
                "_samples": samples,
            }
            self._family_cache[cache_key] = cached

        out = {k: v for k, v in cached.items() if not k.startswith("_")}
        out["sample_returned"] = min(limit, len(cached["_samples"]))
        out["top_findings"] = cached["_samples"][:limit]
        return out

    def rank_incidents(self, limit: int = 25, min_severity: int | None = None,
                       family: str | None = None,
                       account_id: str | None = None) -> dict[str, Any]:
        r = self.full()
        rows = r.incidents
        if family:
            rows = [i for i in rows if family in i.families]
        if account_id:
            rows = [i for i in rows if i.account_id == account_id]
        if min_severity is not None:
            rows = [i for i in rows if i.severity >= min_severity]
        return {
            "matched": len(rows),
            "returned": min(limit, len(rows)),
            "incidents": [i.compact() for i in rows[:limit]],
        }

    def get_container(self, container_id: str) -> dict[str, Any]:
        c = self.container(container_id)
        if c is None:
            return {"error": f"container {container_id} not found in {self.path}"}
        findings = run_detectors(c, self.config)
        payload: dict[str, Any] = {
            "container_id": c.container_id,
            "account": {"id": c.account_id, "name": c.account_name, "tier": c.account_tier},
            "status": c.status,
            "lane": c.lane,
            "booked": c.booked,
            "current": c.current,
            "previous_snapshot_eta": c.raw.get("previous_snapshot_eta"),
            "eta_history": c.raw.get("eta_history"),
            "port_events": c.raw.get("port_events"),
            "routing_guide": c.guide,
            "last_free_day": c.raw.get("last_free_day"),
            "cargo_value_usd": c.cargo_value_usd,
            "findings": [f.to_dict() for f in findings],
        }
        if findings:
            inc = annotate(build_incident(c, findings, self.config))
            payload["incident"] = inc.to_dict(include_evidence=False)
        return payload

    def account_rollup(self, limit: int = 15) -> dict[str, Any]:
        r = self.full()
        return {"accounts_affected": len(r.account_rollup()),
                "accounts": r.account_rollup(limit=limit)}

    def detector_performance(self) -> dict[str, Any]:
        return {"per_family": detector_stats(self.full()),
                "note": "'as_contributing_signal' counts findings that were grouped under "
                        "another family's incident on the same container."}

    def simulate_threshold(self, path: str, value: float) -> dict[str, Any]:
        """What would the queue look like if this threshold moved? (does not persist)"""
        family = path.split(".")[0]
        if family not in FAMILIES:
            return {"error": f"'{path}' does not address a detector family {list(FAMILIES)}"}
        before = self.run_detector(family, limit=0)
        trial = self.config.with_override(path, value)
        hits = 0
        for c in load_containers(self.path):
            if run_detectors(c, trial, [family]):
                hits += 1
        return {
            "threshold": path,
            "current_value": self.config.get(path),
            "simulated_value": value,
            "containers_flagged_now": before.get("containers_flagged", 0),
            "containers_flagged_if_changed": hits,
            "delta": hits - before.get("containers_flagged", 0),
            "note": "simulation only — config on disk is unchanged",
        }

    def emit_report(self, executive_summary: str,
                    triaged: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        self.report = {
            "executive_summary": executive_summary,
            "triaged": triaged or [],
        }
        return {"accepted": True,
                "executive_summary_chars": len(executive_summary),
                "containers_triaged": len(triaged or [])}

    # -- dispatch ----------------------------------------------------------- #
    def dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        fn = getattr(self, name, None)
        if fn is None or name not in {t["name"] for t in TOOL_SPECS}:
            return {"error": f"unknown tool '{name}'"}
        try:
            result = fn(**(arguments or {}))
        except TypeError as exc:
            result = {"error": f"bad arguments for {name}: {exc}"}
        self.call_log.append({"tool": name, "arguments": arguments})
        return result

    def apply_report(self, incidents: list[Incident]) -> str:
        """Merge the model's triage back onto the ranked incidents."""
        if not self.report:
            return ""
        by_id = {i.container_id: i for i in incidents}
        for item in self.report.get("triaged", []):
            inc = by_id.get(item.get("container_id", ""))
            if inc is None:
                continue
            if item.get("what_changed"):
                inc.what_changed = item["what_changed"]
            if item.get("why_it_matters"):
                inc.why_it_matters = item["why_it_matters"]
            if item.get("recommended_action"):
                inc.recommended_action = item["recommended_action"]
            inc.triage_source = "claude"
        return self.report.get("executive_summary", "")


# --------------------------------------------------------------------------- #
# Tool schemas (Claude API `tools` format; reused by the MCP server)
# --------------------------------------------------------------------------- #

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "describe_snapshot",
        "description": "Overview of today's container-status snapshot: row count, status "
                       "breakdown, how many findings each detector produced, severity bands "
                       "and the thresholds currently in effect. Call this first.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_detectors",
        "description": "The five exception detectors, what each one flags, what it "
                       "deliberately suppresses as noise, and the thresholds it is running "
                       "with right now.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_detector",
        "description": "Run ONE exception detector across every container in the snapshot. "
                       "Returns how many containers it flagged, the mean magnitude past the "
                       "threshold, and the highest-severity sample findings with their "
                       "field-level evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "family": {"type": "string", "enum": list(FAMILIES),
                           "description": "Which detector to run."},
                "limit": {"type": "integer",
                          "description": "How many sample findings to return (default 10)."},
                "account_id": {"type": "string",
                               "description": "Optional: restrict to one account."},
            },
            "required": ["family"],
        },
    },
    {
        "name": "rank_incidents",
        "description": "The ranked exception queue. One incident per container — correlated "
                       "signals are grouped, so a vessel swap that moved the ETA is one "
                       "incident, not two. Sorted by severity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Default 25."},
                "min_severity": {"type": "integer", "description": "0-100 filter."},
                "family": {"type": "string", "enum": list(FAMILIES)},
                "account_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_container",
        "description": "Everything the snapshot holds on one container — booking, current "
                       "state, full routing, port events, ETA history, routing guide — plus "
                       "every finding against it with field-level evidence. Use this to "
                       "verify before you escalate.",
        "input_schema": {
            "type": "object",
            "properties": {"container_id": {"type": "string"}},
            "required": ["container_id"],
        },
    },
    {
        "name": "account_rollup",
        "description": "Incidents grouped by customer account, worst account first. Use it to "
                       "spot an account with a systemic problem rather than one bad box.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Default 15."}},
        },
    },
    {
        "name": "detector_performance",
        "description": "Per-detector contribution to the queue: findings raised, how often "
                       "the family was the root cause vs. a downstream signal, and mean "
                       "severity. Use it to judge whether a detector is producing noise.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_threshold",
        "description": "Ask what the queue would look like at a different threshold, e.g. "
                       "'eta_drift.min_drift_hours' = 36. Returns the before/after container "
                       "count. Simulation only — the config on disk is never modified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "Dotted config path, e.g. 'dwell.transshipment_max_hours'."},
                "value": {"type": "number"},
            },
            "required": ["path", "value"],
        },
    },
    {
        "name": "emit_report",
        "description": "Deliver the finished daily report. Call this exactly once, at the end. "
                       "Provide a short executive summary and, for the containers you "
                       "escalated, a plain-language 'what changed', 'why it matters' and a "
                       "concrete 'recommended action' an operator can execute today.",
        "input_schema": {
            "type": "object",
            "properties": {
                "executive_summary": {
                    "type": "string",
                    "description": "3-6 sentences: the shape of today's queue, the pattern "
                                   "worth knowing, and what to do first.",
                },
                "triaged": {
                    "type": "array",
                    "description": "One entry per escalated container.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "container_id": {"type": "string"},
                            "what_changed": {"type": "string"},
                            "why_it_matters": {"type": "string"},
                            "recommended_action": {"type": "string"},
                        },
                        "required": ["container_id", "why_it_matters", "recommended_action"],
                    },
                },
            },
            "required": ["executive_summary"],
        },
    },
]

TOOL_NAMES = [t["name"] for t in TOOL_SPECS]
