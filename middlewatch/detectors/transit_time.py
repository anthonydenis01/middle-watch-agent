"""Transit time — the lane is not performing the way the routing guide says.

Projected transit = actual departure from origin (or `current.etd` if the box
has not sailed yet) to `current.eta`. It is compared to the routing guide:

    allowed = benchmark_transit_days + lane tolerance_days + transit_time.tolerance_days

This is the only detector that looks at the commercial promise rather than the
operational plan. It catches the case every other detector misses: nothing
"changed" — same vessel, same routing, ETA stable — the lane is simply running
five days slower than the contract says it does.

With `flag_faster_than_guide` it also flags lanes running far FASTER than the
guide. That is usually a stale benchmark, and a stale benchmark prices the next
contract wrong.
"""

from __future__ import annotations

from ..config import Config
from ..loader import Container
from ..models import Evidence, Finding


def detect(c: Container, config: Config) -> Finding | None:
    if c.current_eta is None:
        return None

    departure = c.actual_departure() or c.current_etd
    if departure is None:
        return None

    benchmark = c.guide.get("benchmark_transit_days")
    if benchmark is None:
        return None
    benchmark = float(benchmark)
    lane_tolerance = float(c.guide.get("tolerance_days") or 0.0)
    tolerance = float(config.get("transit_time.tolerance_days", 3.0))
    critical = float(config.get("transit_time.critical_excess_days", 7.0))

    projected = (c.current_eta - departure).total_seconds() / 86400.0
    allowed = benchmark + lane_tolerance + tolerance
    excess = projected - allowed

    direction = None
    if excess > 0:
        direction = "slower"
    elif config.get("transit_time.flag_faster_than_guide", True):
        fast_margin = float(config.get("transit_time.faster_than_guide_days", 4.0))
        floor = benchmark - lane_tolerance - fast_margin
        if projected < floor:
            direction = "faster"
            excess = floor - projected

    if direction is None:
        return None

    departed = c.actual_departure() is not None
    evidence = [
        Evidence("port_events[VESSEL_DEPARTED].timestamp" if departed else "current.etd",
                 departure.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 note="actual departure from origin" if departed
                      else "planned departure — container has not sailed yet"),
        Evidence("current.eta", c.current.get("eta"),
                 note="projected arrival at final destination"),
        Evidence("computed.projected_transit_days", f"{projected:.1f} d",
                 expected=f"{benchmark:.1f} d",
                 threshold=f"{allowed:.1f} d",
                 note=f"routing-guide benchmark {benchmark:.1f}d "
                      f"+ lane tolerance {lane_tolerance:.1f}d "
                      f"+ configured tolerance {tolerance:.1f}d"),
        Evidence("routing_guide.lane", c.guide.get("lane"),
                 note="contractual lane the benchmark comes from"),
    ]

    deviation = projected - benchmark
    if direction == "slower":
        headline = (f"Lane {c.guide.get('lane')} running {deviation:+.1f}d vs benchmark "
                    f"({projected:.1f}d actual vs {benchmark:.1f}d guide, "
                    f"{excess:.1f}d past tolerance)")
    else:
        headline = (f"Lane {c.guide.get('lane')} beating the benchmark by "
                    f"{abs(deviation):.1f}d ({projected:.1f}d vs {benchmark:.1f}d guide) "
                    f"— the routing guide looks stale")

    return Finding(
        container_id=c.container_id,
        family="transit_time",
        headline=headline,
        evidence=evidence,
        metrics={
            "direction": direction,
            "lane": c.guide.get("lane"),
            "projected_transit_days": round(projected, 2),
            "benchmark_transit_days": benchmark,
            "lane_tolerance_days": lane_tolerance,
            "allowed_transit_days": round(allowed, 2),
            "excess_days": round(excess, 2),
            "deviation_vs_benchmark_days": round(deviation, 2),
            "departed": departed,
        },
        magnitude=min(1.0, excess / max(critical, 0.1)),
    )
