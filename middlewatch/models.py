"""Core data structures: evidence, findings, incidents.

The rule the whole project is built around: **no finding without field-level
evidence**. A detector may not emit a Finding unless it can name the fields it
read, the values it saw, what it compared them to and the threshold it crossed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import FAMILY_LABELS


@dataclass(slots=True)
class Evidence:
    """One field-level justification for a finding."""

    field_path: str                 # e.g. "current.vessel_name"
    observed: Any                   # what the snapshot said
    expected: Any = None            # what it was compared against
    threshold: Any = None           # the configured limit that was crossed
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {"field": self.field_path, "observed": self.observed}
        if self.expected is not None:
            d["expected"] = self.expected
        if self.threshold is not None:
            d["threshold"] = self.threshold
        if self.note:
            d["note"] = self.note
        return d

    def render(self) -> str:
        parts = [f"{self.field_path}={self.observed!r}"]
        if self.expected is not None:
            parts.append(f"booked/expected={self.expected!r}")
        if self.threshold is not None:
            parts.append(f"threshold={self.threshold!r}")
        line = "  ".join(parts)
        return f"{line} — {self.note}" if self.note else line


@dataclass(slots=True)
class Finding:
    """One exception of one family, on one container."""

    container_id: str
    family: str
    headline: str                   # "Vessel swapped: MV A -> MV B, +48h to ETA"
    evidence: list[Evidence] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    magnitude: float = 0.0          # 0..1, how far past the threshold this sits

    @property
    def label(self) -> str:
        return FAMILY_LABELS[self.family]

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "label": self.label,
            "headline": self.headline,
            "magnitude": round(self.magnitude, 3),
            "metrics": self.metrics,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass(slots=True)
class Incident:
    """One container, one operational event — however many signals fired.

    A vessel swap that pushes the ETA that breaks the transit benchmark is one
    incident with three signals, not three alerts. `primary_family` is the root
    signal; `families` lists everything that fired.
    """

    container_id: str
    account_id: str
    account_name: str
    account_tier: str
    lane: str
    status: str
    primary_family: str
    findings: list[Finding]
    severity: int
    eta_booked: str
    eta_current: str
    days_to_arrival: float
    last_free_day: str
    cargo_value_usd: int
    severity_drivers: list[str] = field(default_factory=list)
    # Triage narrative — templated by default, written by the model for the
    # containers the agent escalates.
    what_changed: str = ""
    why_it_matters: str = ""
    recommended_action: str = ""
    triage_source: str = "rules"    # "rules" | "claude"
    suppressed: bool = False

    @property
    def families(self) -> list[str]:
        return [f.family for f in self.findings]

    @property
    def band(self) -> str:
        if self.severity >= 80:
            return "critical"
        if self.severity >= 60:
            return "high"
        if self.severity >= 40:
            return "medium"
        return "low"

    @property
    def primary_finding(self) -> Finding:
        for f in self.findings:
            if f.family == self.primary_family:
                return f
        return self.findings[0]

    def to_dict(self, include_evidence: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "container_id": self.container_id,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "account_tier": self.account_tier,
            "lane": self.lane,
            "status": self.status,
            "severity": self.severity,
            "band": self.band,
            "primary_family": self.primary_family,
            "families": self.families,
            "eta_booked": self.eta_booked,
            "eta_current": self.eta_current,
            "days_to_arrival": round(self.days_to_arrival, 1),
            "last_free_day": self.last_free_day,
            "cargo_value_usd": self.cargo_value_usd,
            "severity_drivers": self.severity_drivers,
            "what_changed": self.what_changed,
            "why_it_matters": self.why_it_matters,
            "recommended_action": self.recommended_action,
            "triage_source": self.triage_source,
        }
        if include_evidence:
            d["findings"] = [f.to_dict() for f in self.findings]
        else:
            d["headlines"] = [f.headline for f in self.findings]
        return d

    def compact(self) -> dict[str, Any]:
        """Small enough to put a few hundred of these in a model's context."""
        return {
            "container_id": self.container_id,
            "account": self.account_name,
            "tier": self.account_tier,
            "lane": self.lane,
            "severity": self.severity,
            "primary": self.primary_family,
            "families": self.families,
            "headlines": [f.headline for f in self.findings],
            "days_to_arrival": round(self.days_to_arrival, 1),
        }
