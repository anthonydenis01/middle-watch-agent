"""Dwell — the box has stopped moving somewhere it should not have.

A dwell is an OPEN interval in the event stream: a `DISCHARGED` with no later
`LOADED`, a `GATE_IN` with no later `LOADED`, or a `DISCHARGED` at destination
with no later `GATE_OUT`. Its length is measured from that event to
`snapshot_time`.

Limits come from `[dwell]` and depend on where the box is sitting (origin,
transshipment hub, destination). On top of the limit the detector adds
`grace_hours`, plus `non_working_day_allowance_hours` when the dwell window
covers a weekend — the single biggest source of Monday-morning false positives.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..config import Config
from ..loader import Container
from ..models import Evidence, Finding

_OPENERS = {"DISCHARGED", "GATE_IN"}
_CLOSERS = {"LOADED", "GATE_OUT", "VESSEL_DEPARTED"}


def _open_dwell(c: Container) -> tuple[datetime | None, str | None, str | None]:
    """Last opening event with no closing event after it."""
    opener_ts = opener_port = opener_kind = None
    for ts, port, kind in c.events:
        if kind in _OPENERS:
            opener_ts, opener_port, opener_kind = ts, port, kind
        elif kind in _CLOSERS and opener_ts is not None:
            opener_ts = opener_port = opener_kind = None
    return opener_ts, opener_port, opener_kind


def _covers_weekend(start: datetime, end: datetime) -> bool:
    day = start
    while day < end:
        if day.weekday() >= 5:
            return True
        day += timedelta(days=1)
    return end.weekday() >= 5


def _location_kind(c: Container, port: str | None) -> str:
    origin = c.booked.get("origin_port")
    dest = c.current.get("destination_port") or c.booked.get("destination_port")
    if port == origin:
        return "origin"
    if port == dest:
        return "destination"
    return "transshipment"


def detect(c: Container, config: Config) -> Finding | None:
    ts, port, kind = _open_dwell(c)
    if ts is None or c.snapshot_time is None:
        return None

    dwell_hours = (c.snapshot_time - ts).total_seconds() / 3600.0
    if dwell_hours <= 0:
        return None

    location = _location_kind(c, port)
    limit = float(config.get(f"dwell.{location}_max_hours", 96))
    grace = float(config.get("dwell.grace_hours", 0))
    allowance = float(config.get("dwell.non_working_day_allowance_hours", 0)) \
        if _covers_weekend(ts, c.snapshot_time) else 0.0
    effective_limit = limit + grace + allowance

    if dwell_hours <= effective_limit:
        return None

    over = dwell_hours - effective_limit
    evidence = [
        Evidence(f"port_events[last {kind}].timestamp",
                 ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 note=f"{kind} at {port}, never closed by a LOADED/GATE_OUT event"),
        Evidence("snapshot_time", c.snapshot_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 note="clock the dwell is measured to"),
        Evidence("computed.dwell_hours", f"{dwell_hours:.0f} h",
                 threshold=f"{effective_limit:.0f} h",
                 note=f"{location} limit {limit:.0f}h + grace {grace:.0f}h"
                      + (f" + weekend allowance {allowance:.0f}h" if allowance else "")),
        Evidence("status", c.status, note="carrier status on this snapshot"),
    ]

    headline = (f"Sitting {dwell_hours:.0f}h at {port} ({location}) — "
                f"{over:.0f}h over the {effective_limit:.0f}h limit")

    return Finding(
        container_id=c.container_id,
        family="dwell",
        headline=headline,
        evidence=evidence,
        metrics={
            "location": location,
            "port": port,
            "opening_event": kind,
            "dwell_hours": round(dwell_hours, 1),
            "effective_limit_hours": round(effective_limit, 1),
            "hours_over_limit": round(over, 1),
            "weekend_allowance_applied": bool(allowance),
        },
        magnitude=min(1.0, over / 168.0),
    )
