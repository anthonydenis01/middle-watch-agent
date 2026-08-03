"""Snapshot loading.

Reads the daily container-status file (JSONL or the flattened CSV export) and
wraps each row in a `Container` that pre-parses the timestamps the detectors
need. Streaming by design: a 40k-row file is read line by line, never held in
memory as raw text.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_NESTED_CSV_COLUMNS = {
    "booked_routing_json": ("booked", "routing"),
    "current_routing_json": ("current", "routing"),
    "eta_history_json": (None, "eta_history"),
    "port_events_json": (None, "port_events"),
    "routing_guide_json": (None, "routing_guide"),
}


def parse_ts(value: str | None) -> datetime | None:
    """Fast ISO-8601-Z parser. ~10x faster than strptime at 40k rows x 15 fields."""
    if not value:
        return None
    try:
        return datetime(int(value[0:4]), int(value[5:7]), int(value[8:10]),
                        int(value[11:13]), int(value[14:16]), int(value[17:19]),
                        tzinfo=timezone.utc)
    except (ValueError, IndexError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


class Container:
    """One snapshot row, with the timestamps the detectors need already parsed."""

    __slots__ = ("raw", "snapshot_time", "booked", "current", "guide",
                 "events", "booked_eta", "current_eta", "booked_etd",
                 "current_etd", "previous_eta", "last_free_day")

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.booked = raw.get("booked", {})
        self.current = raw.get("current", {})
        self.guide = raw.get("routing_guide", {})
        self.snapshot_time = parse_ts(raw.get("snapshot_time"))
        self.booked_eta = parse_ts(self.booked.get("eta"))
        self.current_eta = parse_ts(self.current.get("eta"))
        self.booked_etd = parse_ts(self.booked.get("etd"))
        self.current_etd = parse_ts(self.current.get("etd"))
        self.previous_eta = parse_ts(raw.get("previous_snapshot_eta")) or \
            self._eta_from_history()
        self.last_free_day = parse_ts(raw.get("last_free_day"))
        self.events = [
            (parse_ts(e.get("timestamp")), e.get("port"), e.get("event"))
            for e in raw.get("port_events", [])
        ]
        self.events.sort(key=lambda e: (e[0] or self.snapshot_time))

    # -- convenience -------------------------------------------------------- #
    def _eta_from_history(self) -> datetime | None:
        hist = self.raw.get("eta_history") or []
        return parse_ts(hist[-1].get("eta")) if hist else None

    @property
    def container_id(self) -> str:
        return self.raw.get("container_id", "")

    @property
    def account_id(self) -> str:
        return self.raw.get("account_id", "")

    @property
    def account_name(self) -> str:
        return self.raw.get("account_name", "")

    @property
    def account_tier(self) -> str:
        return self.raw.get("account_tier", "standard")

    @property
    def status(self) -> str:
        return self.raw.get("status", "")

    @property
    def lane(self) -> str:
        return self.guide.get("lane") or (
            f"{self.booked.get('origin_port', '?')}-{self.booked.get('destination_port', '?')}")

    @property
    def cargo_value_usd(self) -> int:
        return int(self.raw.get("cargo_value_usd") or 0)

    def last_event(self, kinds: tuple[str, ...] | None = None):
        for ts, port, kind in reversed(self.events):
            if kinds is None or kind in kinds:
                return ts, port, kind
        return None, None, None

    def actual_departure(self) -> datetime | None:
        for ts, _port, kind in self.events:
            if kind == "VESSEL_DEPARTED":
                return ts
        return None

    def hours_since(self, ts: datetime | None) -> float | None:
        if ts is None or self.snapshot_time is None:
            return None
        return (self.snapshot_time - ts).total_seconds() / 3600.0


# --------------------------------------------------------------------------- #
# Readers
# --------------------------------------------------------------------------- #

def _row_from_csv(row: dict[str, str]) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "snapshot_date": row.get("snapshot_date"),
        "snapshot_time": row.get("snapshot_time") or f"{row.get('snapshot_date')}T06:00:00Z",
        "container_id": row.get("container_id"),
        "container_type": row.get("container_type"),
        "booking_id": row.get("booking_id"),
        "account_id": row.get("account_id"),
        "account_name": row.get("account_name"),
        "account_tier": row.get("account_tier"),
        "commodity": row.get("commodity"),
        "cargo_value_usd": int(row.get("cargo_value_usd") or 0),
        "status": row.get("status"),
        "last_free_day": row.get("last_free_day"),
        "booked": {
            "origin_port": row.get("booked_origin_port"),
            "destination_port": row.get("booked_destination_port"),
            "vessel_name": row.get("booked_vessel_name"),
            "voyage": row.get("booked_voyage"),
            "service_loop": row.get("booked_service_loop"),
            "etd": row.get("booked_etd"),
            "eta": row.get("booked_eta"),
            "transit_days": float(row.get("booked_transit_days") or 0),
        },
        "current": {
            "origin_port": row.get("booked_origin_port"),
            "destination_port": row.get("current_destination_port"),
            "vessel_name": row.get("current_vessel_name"),
            "voyage": row.get("current_voyage"),
            "service_loop": row.get("current_service_loop"),
            "etd": row.get("current_etd"),
            "eta": row.get("current_eta"),
        },
    }
    for col, (parent, key) in _NESTED_CSV_COLUMNS.items():
        value = json.loads(row[col]) if row.get(col) else ([] if key != "routing_guide" else {})
        if parent:
            rec[parent][key] = value
        else:
            rec[key] = value
    hist = rec.get("eta_history") or []
    rec["previous_snapshot_eta"] = hist[-1]["eta"] if hist else None
    return rec


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield raw records from a .jsonl / .json / .csv snapshot."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"snapshot not found: {p}")
    suffix = p.suffix.lower()

    if suffix == ".csv":
        with open(p, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                yield _row_from_csv(row)
        return

    if suffix == ".json":
        with open(p, encoding="utf-8") as fh:
            payload = json.load(fh)
        rows = payload if isinstance(payload, list) else payload.get("containers", [])
        yield from rows
        return

    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_containers(path: str | Path) -> Iterator[Container]:
    for raw in iter_records(path):
        yield Container(raw)
