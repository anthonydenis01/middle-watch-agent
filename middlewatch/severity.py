"""Severity scoring and incident assembly.

Ranking is the product. An operator with 40,000 containers does not need to know
that 900 of them have something slightly odd about them; they need to know which
twelve to touch before lunch.

    score = (family base
             + magnitude bonus          how far past the threshold it sits
             + correlated-signal bonus  more than one detector fired
             + account-tier bonus)
            x urgency multipliers       time left, free time, cargo value

All weights live in `[severity]` in the config.
"""

from __future__ import annotations

from .config import Config
from .loader import Container
from .models import Finding, Incident

MAGNITUDE_BONUS_MAX = 15.0


def pick_primary(findings: list[Finding], config: Config) -> str:
    """Root-cause ordering: the routing change explains the ETA drift, not the reverse."""
    order = config.get("grouping.primary_order", []) or []
    ranked = sorted(
        findings,
        key=lambda f: (order.index(f.family) if f.family in order else 99, -f.magnitude),
    )
    return ranked[0].family


def score(c: Container, findings: list[Finding], primary_family: str,
          config: Config) -> tuple[int, list[str]]:
    drivers: list[str] = []
    base = float(config.get(f"severity.{primary_family}", 50))

    primary = next((f for f in findings if f.family == primary_family), findings[0])
    bonus_max = float(config.get("severity.magnitude_bonus_max", MAGNITUDE_BONUS_MAX))
    magnitude_bonus = bonus_max * max(0.0, min(1.0, primary.magnitude))
    if magnitude_bonus >= 5:
        drivers.append(f"{primary_family} well past threshold")

    correlated = float(config.get("severity.correlated_signal_bonus", 6)) * (len(findings) - 1)
    if len(findings) > 1:
        drivers.append(f"{len(findings)} correlated signals")

    tier = c.account_tier or "standard"
    tier_bonus = float(config.get(f"severity.account_tier_bonus.{tier}", 0))
    if tier_bonus:
        drivers.append(f"{tier} account")

    total = base + magnitude_bonus + correlated + tier_bonus

    mult = config.section("severity.multipliers")
    days_to_arrival = 999.0
    if c.current_eta and c.snapshot_time:
        days_to_arrival = (c.current_eta - c.snapshot_time).total_seconds() / 86400.0
    if days_to_arrival <= float(mult.get("urgent_days_to_arrival", 5)):
        total *= float(mult.get("days_to_arrival_urgent", 1.0))
        drivers.append(f"arriving in {max(days_to_arrival, 0):.1f} days")

    if c.last_free_day and c.current_eta and c.current_eta > c.last_free_day:
        total *= float(mult.get("last_free_day_risk", 1.0))
        drivers.append("projected arrival past last free day")

    if c.cargo_value_usd >= float(mult.get("high_value_threshold_usd", 10**12)):
        total *= float(mult.get("high_value_cargo", 1.0))
        drivers.append(f"cargo value ${c.cargo_value_usd:,}")

    return int(round(max(0.0, min(100.0, total)))), drivers


def build_incident(c: Container, findings: list[Finding], config: Config) -> Incident:
    primary_family = pick_primary(findings, config)
    if not config.get("grouping.enabled", True):
        primary_family = findings[0].family
    sev, drivers = score(c, findings, primary_family, config)

    days_to_arrival = 999.0
    if c.current_eta and c.snapshot_time:
        days_to_arrival = (c.current_eta - c.snapshot_time).total_seconds() / 86400.0

    return Incident(
        container_id=c.container_id,
        account_id=c.account_id,
        account_name=c.account_name,
        account_tier=c.account_tier,
        lane=c.lane,
        status=c.status,
        primary_family=primary_family,
        findings=sorted(findings, key=lambda f: -f.magnitude),
        severity=sev,
        eta_booked=c.booked.get("eta", ""),
        eta_current=c.current.get("eta", ""),
        days_to_arrival=days_to_arrival,
        last_free_day=c.raw.get("last_free_day", ""),
        cargo_value_usd=c.cargo_value_usd,
        severity_drivers=drivers,
        suppressed=sev < float(config.get("general.min_severity_to_report", 0)),
    )
