"""Detector registry.

Each detector is a pure function `detect(container, config) -> Finding | None`.
No I/O, no shared state, no hidden thresholds — everything it decides with comes
from the container and the config. That is what makes them safe to expose as
tools to a model (and as MCP tools to any other client).
"""

from __future__ import annotations

from typing import Callable

from ..config import Config
from ..loader import Container
from ..models import Finding
from . import dwell, eta_drift, routing_change, transit_time, vessel_swap

DetectorFn = Callable[[Container, Config], "Finding | None"]

DETECTORS: dict[str, DetectorFn] = {
    "routing_change": routing_change.detect,
    "vessel_swap": vessel_swap.detect,
    "dwell": dwell.detect,
    "eta_drift": eta_drift.detect,
    "transit_time": transit_time.detect,
}

DETECTOR_DOCS: dict[str, str] = {
    "routing_change": routing_change.__doc__ or "",
    "vessel_swap": vessel_swap.__doc__ or "",
    "dwell": dwell.__doc__ or "",
    "eta_drift": eta_drift.__doc__ or "",
    "transit_time": transit_time.__doc__ or "",
}


def run_detectors(container: Container, config: Config,
                  families: list[str] | None = None) -> list[Finding]:
    out: list[Finding] = []
    for name in (families or list(DETECTORS)):
        fn = DETECTORS.get(name)
        if fn is None or not config.enabled(name):
            continue
        finding = fn(container, config)
        if finding is not None:
            out.append(finding)
    return out


__all__ = ["DETECTORS", "DETECTOR_DOCS", "run_detectors", "DetectorFn"]
