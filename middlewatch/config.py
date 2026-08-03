"""Threshold configuration loading.

Every number that decides "exception or noise" lives in config/thresholds.toml.
Nothing in the detectors hardcodes a threshold — that is what makes false-positive
control a tuning exercise instead of a code change.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "thresholds.toml"


class Config:
    """Dotted-path read/write access over the parsed TOML tree."""

    def __init__(self, data: dict[str, Any], source: str = "<memory>"):
        self._data = data
        self.source = source

    # -- access ------------------------------------------------------------ #
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, path: str) -> Any:
        value = self.get(path, _MISSING)
        if value is _MISSING:
            raise KeyError(f"missing config key: {path} (in {self.source})")
        return value

    def section(self, name: str) -> dict[str, Any]:
        return self.get(name, {}) or {}

    def enabled(self, family: str) -> bool:
        return bool(self.get(f"{family}.enabled", True))

    # -- mutation (used by the agent's threshold-simulation tool) ----------- #
    def with_override(self, path: str, value: Any) -> "Config":
        data = copy.deepcopy(self._data)
        node = data
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        return Config(data, source=f"{self.source} +override({path}={value})")

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._data)

    def summary(self) -> dict[str, Any]:
        """The thresholds an operator would want printed at the top of a report."""
        return {
            "min_severity_to_report": self.get("general.min_severity_to_report"),
            "routing_change": {
                "min_added_transit_days": self.get("routing_change.min_added_transit_days"),
                "ignore_equivalent_transshipment":
                    self.get("routing_change.ignore_equivalent_transshipment"),
            },
            "vessel_swap": {
                "min_eta_impact_hours": self.get("vessel_swap.min_eta_impact_hours"),
                "ignore_voyage_only_change": self.get("vessel_swap.ignore_voyage_only_change"),
            },
            "dwell": {
                "transshipment_max_hours": self.get("dwell.transshipment_max_hours"),
                "destination_max_hours": self.get("dwell.destination_max_hours"),
                "origin_max_hours": self.get("dwell.origin_max_hours"),
                "grace_hours": self.get("dwell.grace_hours"),
            },
            "eta_drift": {
                "min_drift_hours": self.get("eta_drift.min_drift_hours"),
                "min_daily_drift_hours": self.get("eta_drift.min_daily_drift_hours"),
            },
            "transit_time": {
                "tolerance_days": self.get("transit_time.tolerance_days"),
            },
        }


_MISSING = object()


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with open(p, "rb") as fh:
        return Config(tomllib.load(fh), source=str(p))
