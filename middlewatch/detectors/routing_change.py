"""Routing change — the box is no longer going the way it was booked.

Compares the port sequence of `current.routing` against `booked.routing`.

Flags:
  * final discharge port changed                      (always, if enabled)
  * a transshipment leg added or removed              (always, if enabled)
  * transshipment hub swapped for a non-equivalent hub
  * transshipment hub swapped for an EQUIVALENT hub only when it costs more than
    `routing_change.min_added_transit_days`

Suppresses: hub swaps inside the same equivalence group that cost nothing. Moving
a box from one hub to its neighbour in the same group is network management, not
an exception, and flagging it is the fastest way to make an operator stop reading
the report.
"""

from __future__ import annotations

from ..config import Config
from ..loader import Container
from ..models import Evidence, Finding


def _port_sequence(routing: list[dict]) -> list[str]:
    if not routing:
        return []
    seq = [leg.get("from_port") for leg in routing]
    seq.append(routing[-1].get("to_port"))
    return [p for p in seq if p]


def _hubs(routing: list[dict]) -> list[str]:
    seq = _port_sequence(routing)
    return seq[1:-1]


def _equivalence_groups(config: Config) -> list[set[str]]:
    groups = config.section("routing_change.equivalent_hubs") or \
        config.get("routing_change.equivalent_hubs", {}) or {}
    return [set(v) for v in groups.values() if isinstance(v, list)]


def _same_group(a: str, b: str, groups: list[set[str]]) -> bool:
    return any(a in g and b in g for g in groups)


def _transit_days(etd, eta) -> float | None:
    if etd is None or eta is None:
        return None
    return (eta - etd).total_seconds() / 86400.0


def detect(c: Container, config: Config) -> Finding | None:
    booked_routing = c.booked.get("routing") or []
    current_routing = c.current.get("routing") or []
    booked_seq = _port_sequence(booked_routing)
    current_seq = _port_sequence(current_routing)
    if not booked_seq or not current_seq or booked_seq == current_seq:
        return None

    booked_dest = c.booked.get("destination_port")
    current_dest = c.current.get("destination_port")
    booked_hubs, current_hubs = _hubs(booked_routing), _hubs(current_routing)

    booked_transit = _transit_days(c.booked_etd, c.booked_eta)
    current_transit = _transit_days(c.current_etd, c.current_eta)
    added_days = (current_transit - booked_transit) \
        if (booked_transit is not None and current_transit is not None) else 0.0

    min_added = float(config.get("routing_change.min_added_transit_days", 1.0))
    groups = _equivalence_groups(config)

    kind = None
    if config.get("routing_change.flag_destination_change", True) and booked_dest != current_dest:
        kind = "destination_change"
    elif config.get("routing_change.flag_added_transshipment", True) and \
            len(current_routing) != len(booked_routing):
        kind = "added_transshipment" if len(current_routing) > len(booked_routing) \
            else "removed_transshipment"
    elif booked_hubs != current_hubs:
        equivalent = (
            len(booked_hubs) == len(current_hubs)
            and all(_same_group(a, b, groups) for a, b in zip(booked_hubs, current_hubs))
        )
        if equivalent and config.get("routing_change.ignore_equivalent_transshipment", True) \
                and added_days < min_added:
            return None                     # noise: interchangeable hub, no cost
        kind = "equivalent_hub_change" if equivalent else "hub_change"

    if kind is None:
        return None

    evidence = [
        Evidence("booked.routing[].port_sequence", " > ".join(booked_seq),
                 note="routing as booked"),
        Evidence("current.routing[].port_sequence", " > ".join(current_seq),
                 expected=" > ".join(booked_seq),
                 note="routing on today's snapshot"),
    ]
    if kind == "destination_change":
        evidence.append(Evidence("current.destination_port", current_dest,
                                 expected=booked_dest,
                                 note="final discharge port no longer matches the booking"))
    if booked_hubs != current_hubs:
        evidence.append(Evidence("current.routing[].transshipment", current_hubs or ["direct"],
                                 expected=booked_hubs or ["direct"],
                                 note="transshipment plan changed"))
    if booked_transit is not None and current_transit is not None:
        evidence.append(Evidence(
            "current.eta - current.etd", f"{current_transit:.1f} d",
            expected=f"{booked_transit:.1f} d",
            threshold=f"+{min_added:.1f} d",
            note=f"current transit is {added_days:+.1f} days against the booked plan"))

    headlines = {
        "destination_change": f"Discharge port changed {booked_dest} → {current_dest}",
        "added_transshipment": f"Extra transshipment added via {', '.join(current_hubs) or '?'}",
        "removed_transshipment": "Transshipment leg removed vs. booking",
        "hub_change": f"Transshipment moved {', '.join(booked_hubs) or 'direct'} → "
                      f"{', '.join(current_hubs) or 'direct'}",
        "equivalent_hub_change": f"Hub swapped {', '.join(booked_hubs) or 'direct'} → "
                                 f"{', '.join(current_hubs) or 'direct'} at a transit cost",
    }
    headline = headlines[kind]
    if added_days:
        headline += f" ({added_days:+.1f}d transit)"

    magnitude = min(1.0, max(added_days, 0.0) / 7.0)
    if kind == "destination_change":
        magnitude = max(magnitude, 0.85)
    elif kind == "added_transshipment":
        magnitude = max(magnitude, 0.5)

    return Finding(
        container_id=c.container_id,
        family="routing_change",
        headline=headline,
        evidence=evidence,
        metrics={
            "kind": kind,
            "booked_route": booked_seq,
            "current_route": current_seq,
            "added_transit_days": round(added_days, 2),
        },
        magnitude=magnitude,
    )
