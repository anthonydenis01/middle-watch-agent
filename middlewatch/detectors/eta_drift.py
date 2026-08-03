"""ETA drift — the arrival date is moving.

Two clocks, because they catch different failures:

  * **baseline drift** — `current.eta` vs the ETA quoted at booking. Catches the
    slow accumulation nobody notices until the delivery appointment is wrong.
  * **daily drift** — `current.eta` vs `previous_snapshot_eta`. Catches the box
    that lost 30 hours overnight while its baseline still looks acceptable.

`eta_drift.direction` decides whether early arrivals count. They do by default:
an ETA that jumps forward breaks delivery appointments, warehouse slots and free
time just as reliably as a delay.
"""

from __future__ import annotations

from ..config import Config
from ..loader import Container
from ..models import Evidence, Finding


def detect(c: Container, config: Config) -> Finding | None:
    if c.current_eta is None or c.booked_eta is None:
        return None

    baseline_hours = (c.current_eta - c.booked_eta).total_seconds() / 3600.0
    daily_hours = ((c.current_eta - c.previous_eta).total_seconds() / 3600.0
                   if c.previous_eta else 0.0)

    min_baseline = float(config.get("eta_drift.min_drift_hours", 24))
    min_daily = float(config.get("eta_drift.min_daily_drift_hours", 12))
    critical = float(config.get("eta_drift.critical_drift_hours", 96))
    direction = str(config.get("eta_drift.direction", "both"))

    def counts(value: float) -> bool:
        if direction == "later":
            return value > 0
        if direction == "earlier":
            return value < 0
        return True

    baseline_hit = abs(baseline_hours) >= min_baseline and counts(baseline_hours)
    daily_hit = abs(daily_hours) >= min_daily and counts(daily_hours)
    if not (baseline_hit or daily_hit):
        return None

    drivers = []
    if baseline_hit:
        drivers.append("baseline")
    if daily_hit:
        drivers.append("daily")

    evidence = [
        Evidence("current.eta", c.current.get("eta"), expected=c.booked.get("eta"),
                 threshold=f"{min_baseline:.0f} h",
                 note=f"{baseline_hours:+.0f} h vs. the ETA quoted at booking"),
        Evidence("previous_snapshot_eta",
                 c.raw.get("previous_snapshot_eta"),
                 expected=c.current.get("eta"),
                 threshold=f"{min_daily:.0f} h",
                 note=f"{daily_hours:+.0f} h moved since yesterday's snapshot"),
        Evidence("eta_history", [h.get("eta") for h in (c.raw.get("eta_history") or [])],
                 note="last 4 daily observations"),
        Evidence("last_free_day", c.raw.get("last_free_day"),
                 note="free time at destination — the drift is only expensive against this"),
    ]

    word = "later" if baseline_hours > 0 else "earlier"
    headline = (f"ETA moved {abs(baseline_hours):.0f}h {word} vs. booking"
                if baseline_hit else
                f"ETA moved {abs(daily_hours):.0f}h overnight")
    if baseline_hit and daily_hit:
        headline += f" ({daily_hours:+.0f}h in the last 24h)"

    magnitude = min(1.0, max(abs(baseline_hours) / critical,
                             abs(daily_hours) / max(min_daily * 4, 1)))

    return Finding(
        container_id=c.container_id,
        family="eta_drift",
        headline=headline,
        evidence=evidence,
        metrics={
            "baseline_drift_hours": round(baseline_hours, 1),
            "daily_drift_hours": round(daily_hours, 1),
            "drivers": drivers,
            "critical_threshold_hours": critical,
            "past_last_free_day": bool(
                c.last_free_day and c.current_eta and c.current_eta > c.last_free_day),
        },
        magnitude=magnitude,
    )
