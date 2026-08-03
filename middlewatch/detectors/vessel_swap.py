"""Vessel swap — the container is not on the vessel it was booked on.

Compares `current.vessel_name` / `vessel_imo` / `voyage` / `service_loop` against
`booked.*` and measures the ETA impact of the swap.

Flags:
  * a different vessel that moves the ETA by at least
    `vessel_swap.min_eta_impact_hours`
  * a different vessel on a different service loop, at any ETA impact — a loop
    change is structural and usually means a different set of port calls
  * a voyage-number change on the same vessel ONLY if
    `vessel_swap.ignore_voyage_only_change` is turned off

Suppresses: same vessel with a renumbered voyage (schedule renumbering happens
constantly and means nothing to the cargo), and paper swaps that leave the ETA
where it was.
"""

from __future__ import annotations

from ..config import Config
from ..loader import Container
from ..models import Evidence, Finding


def detect(c: Container, config: Config) -> Finding | None:
    booked_vessel = c.booked.get("vessel_name")
    current_vessel = c.current.get("vessel_name")
    booked_imo = c.booked.get("vessel_imo")
    current_imo = c.current.get("vessel_imo")
    booked_voyage = c.booked.get("voyage")
    current_voyage = c.current.get("voyage")
    booked_loop = c.booked.get("service_loop")
    current_loop = c.current.get("service_loop")

    same_vessel = (booked_vessel == current_vessel) and (booked_imo == current_imo)
    voyage_changed = booked_voyage != current_voyage
    loop_changed = booked_loop != current_loop

    if same_vessel and not voyage_changed and not loop_changed:
        return None

    if same_vessel and voyage_changed and \
            config.get("vessel_swap.ignore_voyage_only_change", True) and not loop_changed:
        return None                        # noise: schedule renumbering

    eta_impact_hours = 0.0
    if c.booked_eta and c.current_eta:
        eta_impact_hours = (c.current_eta - c.booked_eta).total_seconds() / 3600.0

    min_impact = float(config.get("vessel_swap.min_eta_impact_hours", 12))
    flag_loop = bool(config.get("vessel_swap.flag_service_loop_change", True))

    if not same_vessel:
        if abs(eta_impact_hours) < min_impact and not (loop_changed and flag_loop):
            return None                    # noise: paper swap, cargo unaffected
        kind = "vessel_and_loop_change" if loop_changed else "vessel_change"
    else:
        if not (loop_changed and flag_loop):
            return None
        kind = "service_loop_change"

    evidence = [
        Evidence("current.vessel_name", current_vessel, expected=booked_vessel,
                 note="vessel carrying the container today vs. the booked vessel"),
        Evidence("current.vessel_imo", current_imo, expected=booked_imo),
        Evidence("current.voyage", current_voyage, expected=booked_voyage),
    ]
    if loop_changed:
        evidence.append(Evidence("current.service_loop", current_loop, expected=booked_loop,
                                 note="different service string — different port rotation"))
    evidence.append(Evidence(
        "current.eta", c.current.get("eta"), expected=c.booked.get("eta"),
        threshold=f"{min_impact:.0f} h",
        note=f"swap moves the ETA by {eta_impact_hours:+.0f} h"))

    if kind == "service_loop_change":
        headline = f"Service loop changed {booked_loop} → {current_loop} on the same vessel"
    else:
        headline = (f"Vessel swapped {booked_vessel} {booked_voyage} → "
                    f"{current_vessel} {current_voyage} ({eta_impact_hours:+.0f}h ETA)")
        if loop_changed:
            headline += f", loop {booked_loop} → {current_loop}"

    magnitude = min(1.0, abs(eta_impact_hours) / 120.0)
    if loop_changed:
        magnitude = max(magnitude, 0.55)

    return Finding(
        container_id=c.container_id,
        family="vessel_swap",
        headline=headline,
        evidence=evidence,
        metrics={
            "kind": kind,
            "booked_vessel": booked_vessel,
            "current_vessel": current_vessel,
            "booked_voyage": booked_voyage,
            "current_voyage": current_voyage,
            "service_loop_changed": loop_changed,
            "eta_impact_hours": round(eta_impact_hours, 1),
        },
        magnitude=magnitude,
    )
