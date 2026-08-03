#!/usr/bin/env python3
"""
Middle Watch — synthetic on-water container snapshot generator.

Produces a daily container-status file of the kind an ocean-freight operations
desk works from: booking data, current vessel/voyage, routing legs, port events,
ETA history and routing-guide benchmarks — with exceptions deliberately injected
and a ground-truth file so detection quality can be measured honestly.

EVERYTHING IN HERE IS FICTIONAL. Container numbers, vessel names, voyage
numbers, account names, service loops and transit benchmarks are generated from
the word lists in this file. No carrier, customer or operational data of any
kind is used, referenced or reproduced. Port codes are public UN/LOCODEs.

Usage
-----
    python data/generate.py --rows 40000 --seed 7 --out data/out/snapshot.jsonl

    # tune how dirty the file is (rates are per family, per container)
    python data/generate.py --rows 40000 \
        --rate-routing-change 0.012 --rate-vessel-swap 0.015 \
        --rate-dwell 0.010 --rate-eta-drift 0.020 --rate-transit-time 0.010

    # clean file, no exceptions at all (noise-floor test)
    python data/generate.py --rows 5000 --clean

Outputs
-------
    <out>                 JSONL, one container record per line (see data/SCHEMA.md)
    <out>.ground_truth.json   injected exceptions per container, for scripts/evaluate.py
    <out>.csv             optional flattened CSV export (--csv)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# Reference data (fictional except public UN/LOCODE port codes)
# --------------------------------------------------------------------------- #

PORTS = {
    "CNSHA": ("Shanghai", "CN"), "CNNGB": ("Ningbo", "CN"), "CNYTN": ("Yantian", "CN"),
    "HKHKG": ("Hong Kong", "HK"), "VNSGN": ("Ho Chi Minh City", "VN"),
    "THLCH": ("Laem Chabang", "TH"), "SGSIN": ("Singapore", "SG"),
    "MYPKG": ("Port Klang", "MY"), "MYTPP": ("Tanjung Pelepas", "MY"),
    "INNSA": ("Nhava Sheva", "IN"), "AEJEA": ("Jebel Ali", "AE"),
    "NLRTM": ("Rotterdam", "NL"), "BEANR": ("Antwerp", "BE"), "DEHAM": ("Hamburg", "DE"),
    "ESALG": ("Algeciras", "ES"), "ESVLC": ("Valencia", "ES"), "MAPTM": ("Tanger Med", "MA"),
    "ITGOA": ("Genoa", "IT"), "TRMER": ("Mersin", "TR"),
    "USMIA": ("Miami", "US"), "USSAV": ("Savannah", "US"), "USNYC": ("New York", "US"),
    "USHOU": ("Houston", "US"), "USLAX": ("Los Angeles", "US"), "USORF": ("Norfolk", "US"),
    "PACTB": ("Manzanillo (PA)", "PA"), "JMKIN": ("Kingston", "JM"), "DOCAU": ("Caucedo", "DO"),
    "BRSSZ": ("Santos", "BR"), "CLVAP": ("Valparaiso", "CL"), "COCTG": ("Cartagena", "CO"),
    "ZADUR": ("Durban", "ZA"), "AUSYD": ("Sydney", "AU"), "NZAKL": ("Auckland", "NZ"),
}

HUBS = ["SGSIN", "MYPKG", "MYTPP", "AEJEA", "ESALG", "MAPTM", "NLRTM", "BEANR",
        "PACTB", "JMKIN", "DOCAU", "ESVLC", "DEHAM"]

# lane -> (benchmark transit days, routing-guide tolerance days, standard hub or None)
LANES = [
    ("CNSHA", "USMIA", 34.0, 2.0, "PACTB"),
    ("CNNGB", "USMIA", 35.0, 2.0, "PACTB"),
    ("CNYTN", "USSAV", 30.0, 2.0, "PACTB"),
    ("HKHKG", "USNYC", 32.0, 2.5, "PACTB"),
    ("VNSGN", "USMIA", 36.0, 2.5, "SGSIN"),
    ("THLCH", "USHOU", 38.0, 3.0, "SGSIN"),
    ("CNSHA", "USLAX", 18.0, 1.5, None),
    ("CNNGB", "USLAX", 19.0, 1.5, None),
    ("INNSA", "USNYC", 28.0, 2.5, "AEJEA"),
    ("INNSA", "NLRTM", 24.0, 2.0, "AEJEA"),
    ("CNSHA", "NLRTM", 31.0, 2.0, "MYTPP"),
    ("CNYTN", "DEHAM", 33.0, 2.0, "MYPKG"),
    ("VNSGN", "BEANR", 32.0, 2.5, "SGSIN"),
    ("BRSSZ", "USMIA", 14.0, 1.5, None),
    ("CLVAP", "USORF", 19.0, 2.0, "PACTB"),
    ("COCTG", "USHOU", 8.0, 1.0, None),
    ("ZADUR", "NLRTM", 25.0, 2.5, "ESALG"),
    ("AUSYD", "USLAX", 24.0, 2.0, None),
    ("NZAKL", "USSAV", 30.0, 2.5, "PACTB"),
    ("TRMER", "USNYC", 22.0, 2.0, "ESVLC"),
]

SERVICE_LOOPS = ["AEX-1", "AEX-3", "TPX-5", "TPX-7", "MED-2", "NEU-4", "NEU-9",
                 "LAM-2", "LAM-6", "IND-3", "OCE-1", "AFR-5"]

VESSEL_FIRST = ["NORTHERN", "SOUTHERN", "EASTERN", "WESTERN", "ATLANTIC", "PACIFIC",
                "CORAL", "AMBER", "IRON", "SILVER", "GRANITE", "MERIDIAN", "AURORA",
                "CASCADE", "LANTERN", "HARBOUR", "TIDEWATER", "KESTREL", "OSPREY",
                "MARINER", "BEACON", "COMPASS", "SEXTANT", "ANCHORAGE"]
VESSEL_SECOND = ["VOYAGER", "TRADER", "CARRIER", "PIONEER", "SPIRIT", "HORIZON",
                 "MERCHANT", "EXPRESS", "SENTINEL", "PROVIDER", "ENDEAVOUR",
                 "STRAIT", "PASSAGE", "CROSSING", "BRIDGE", "GATEWAY"]

ACCOUNT_FIRST = ["Northline", "Harborview", "Cedarbrook", "Vantage", "Redstone",
                 "Blue Meridian", "Kestrel", "Fairwater", "Summit Bay", "Ironwood",
                 "Clearpoint", "Westfield", "Lakeshore", "Copperfield", "Brightpath",
                 "Silverline", "Granite Peak", "Riverbend", "Foxglove", "Ambercroft",
                 "Marchfield", "Oakhaven", "Pinecrest", "Stonebridge", "Whitmore"]
ACCOUNT_SECOND = ["Industrial Supply", "Trading Co.", "Global Sourcing", "Distribution",
                  "Retail Group", "Manufacturing", "Components", "Home Goods",
                  "Consumer Brands", "Logistics Partners", "Foods International",
                  "Auto Parts", "Textiles", "Electronics", "Chemicals", "Furnishings"]

COMMODITIES = ["Furniture", "Consumer electronics", "Apparel", "Auto parts",
               "Packaged food", "Household appliances", "Building materials",
               "Industrial machinery", "Toys and games", "Footwear", "Paper products",
               "Plastic resins", "Ceramic tile", "Sporting goods", "Pet supplies"]

CONTAINER_PREFIXES = ["MWSU", "MWTU", "MWNU", "MWEU", "MWGU"]  # fictional owner codes
CONTAINER_TYPES = ["40HC", "40GP", "20GP", "45HC", "40RF"]

EQUIVALENT_HUB_GROUPS = [
    ["SGSIN", "MYPKG", "MYTPP"],
    ["NLRTM", "BEANR", "DEHAM"],
    ["ESALG", "MAPTM", "ESVLC"],
    ["PACTB", "JMKIN", "DOCAU"],
]

FAMILIES = ["routing_change", "vessel_swap", "dwell", "eta_drift", "transit_time"]

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_ISO6346_LETTERS = {c: v for c, v in zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    [10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25, 26, 27, 28, 29,
     30, 31, 32, 34, 35, 36, 37, 38])}


def iso6346_check_digit(code: str) -> int:
    """Check digit for an ISO 6346 container number (4 letters + 6 digits)."""
    total = 0
    for i, ch in enumerate(code):
        val = _ISO6346_LETTERS[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    return total % 11 % 10


def make_container_id(rng: random.Random) -> str:
    prefix = rng.choice(CONTAINER_PREFIXES)
    serial = f"{rng.randint(0, 999999):06d}"
    return f"{prefix}{serial}{iso6346_check_digit(prefix + serial)}"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours(n: float) -> timedelta:
    return timedelta(hours=n)


def days(n: float) -> timedelta:
    return timedelta(days=n)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def equivalent_hub(hub: str, rng: random.Random) -> str | None:
    for group in EQUIVALENT_HUB_GROUPS:
        if hub in group and len(group) > 1:
            return rng.choice([h for h in group if h != hub])
    return None


def non_equivalent_hub(hub: str, rng: random.Random) -> str:
    banned = {hub}
    for group in EQUIVALENT_HUB_GROUPS:
        if hub in group:
            banned |= set(group)
    return rng.choice([h for h in HUBS if h not in banned])


def vessel_name(rng: random.Random) -> str:
    return f"MV {rng.choice(VESSEL_FIRST)} {rng.choice(VESSEL_SECOND)}"


def voyage_no(rng: random.Random, direction: str = "E") -> str:
    return f"{rng.randint(1, 48):03d}{direction}"


def imo(rng: random.Random) -> str:
    return f"9{rng.randint(100000, 999999)}"


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #

def build_accounts(rng: random.Random, n: int = 180) -> list[dict]:
    seen, accounts = set(), []
    while len(accounts) < n:
        name = f"{rng.choice(ACCOUNT_FIRST)} {rng.choice(ACCOUNT_SECOND)}"
        if name in seen:
            continue
        seen.add(name)
        tier = rng.choices(["strategic", "key", "standard"], weights=[8, 22, 70])[0]
        accounts.append({
            "account_id": f"ACC-{len(accounts) + 1:04d}",
            "account_name": name,
            "account_tier": tier,
            "service_contract": f"SC-{rng.randint(2026, 2027)}-{rng.randint(100, 999)}",
        })
    return accounts


# --------------------------------------------------------------------------- #
# Record generation
# --------------------------------------------------------------------------- #

PHASES = ["origin", "leg1", "hub", "leg2", "destination"]
PHASE_WEIGHTS = [6, 32, 18, 32, 12]


def build_legs(origin: str, dest: str, hub: str | None, etd: datetime,
               eta: datetime, rng: random.Random, loop: str,
               vessel: str, voyage: str,
               feeder: tuple[str, str, str] | None = None
               ) -> tuple[list[dict], tuple[str, str, str] | None]:
    """Routing legs from origin to destination, optionally via one hub.

    `feeder` pins the second-leg vessel so that the booked and current routings
    of an unchanged container stay identical instead of drifting apart.
    """
    if hub is None:
        return [{
            "seq": 1, "from_port": origin, "to_port": dest, "mode": "VESSEL",
            "vessel_name": vessel, "voyage": voyage, "service_loop": loop,
            "etd": iso(etd), "eta": iso(eta),
        }], None
    total = (eta - etd).total_seconds()
    hub_arr = etd + timedelta(seconds=total * rng.uniform(0.42, 0.58))
    hub_dep = hub_arr + hours(rng.uniform(18, 60))
    feeder = feeder or (vessel_name(rng), voyage_no(rng, "W"), rng.choice(SERVICE_LOOPS))
    return [
        {"seq": 1, "from_port": origin, "to_port": hub, "mode": "VESSEL",
         "vessel_name": vessel, "voyage": voyage, "service_loop": loop,
         "etd": iso(etd), "eta": iso(hub_arr)},
        {"seq": 2, "from_port": hub, "to_port": dest, "mode": "VESSEL",
         "vessel_name": feeder[0], "voyage": feeder[1], "service_loop": feeder[2],
         "etd": iso(hub_dep), "eta": iso(eta)},
    ], feeder


def build_events(legs: list[dict], phase: str, snapshot: datetime,
                 rng: random.Random, dwell_override_hours: float | None
                 ) -> tuple[list[dict], float | None]:
    """Port events consistent with how far along the route the box actually is.

    Returns the events plus the length of the OPEN dwell they leave behind, if
    any. A requested dwell is clamped so the opening event can never land before
    the events that precede it — an out-of-order event stream would be closed by
    the earlier `LOADED` and the labelled exception would become undetectable.
    The caller re-checks the achieved dwell against the label.
    """
    ev: list[dict] = []
    first = legs[0]
    etd = datetime.fromisoformat(first["etd"].replace("Z", "+00:00"))

    ev.append({"port": first["from_port"], "event": "GATE_IN",
               "timestamp": iso(etd - days(rng.uniform(2, 6)))})
    if phase == "origin":
        # still on the terminal at origin, not yet loaded: the clock that matters
        # is time-since-gate-in, so anchor it to the snapshot
        dwell = dwell_override_hours if dwell_override_hours is not None \
            else rng.uniform(4, 80)
        ev[-1]["timestamp"] = iso(snapshot - hours(dwell))
        return ev, dwell

    ev.append({"port": first["from_port"], "event": "LOADED",
               "timestamp": iso(etd - hours(rng.uniform(6, 20)))})
    ev.append({"port": first["from_port"], "event": "VESSEL_DEPARTED",
               "timestamp": iso(etd)})
    if phase == "leg1" or len(legs) == 1 and phase != "destination":
        return ev, None

    if len(legs) == 2:
        hub_arr = parse_iso(legs[0]["eta"])
        hub_dep = parse_iso(legs[1]["etd"])
        if phase == "hub":
            want = dwell_override_hours if dwell_override_hours is not None \
                else rng.uniform(6, 96)
            arr = max(snapshot - hours(want), etd + hours(24))
            ev.append({"port": legs[0]["to_port"], "event": "VESSEL_ARRIVED",
                       "timestamp": iso(arr - hours(2))})
            ev.append({"port": legs[0]["to_port"], "event": "DISCHARGED",
                       "timestamp": iso(arr)})
            return ev, (snapshot - arr).total_seconds() / 3600.0
        ev.append({"port": legs[0]["to_port"], "event": "VESSEL_ARRIVED",
                   "timestamp": iso(hub_arr - hours(2))})
        ev.append({"port": legs[0]["to_port"], "event": "DISCHARGED",
                   "timestamp": iso(hub_arr)})
        ev.append({"port": legs[1]["from_port"], "event": "LOADED",
                   "timestamp": iso(hub_dep - hours(4))})
        ev.append({"port": legs[1]["from_port"], "event": "VESSEL_DEPARTED",
                   "timestamp": iso(hub_dep)})
    if phase == "leg2":
        return ev, None

    # destination: the box is on the ground, waiting to be picked up
    last = legs[-1]
    want = dwell_override_hours if dwell_override_hours is not None else rng.uniform(3, 60)
    floor = parse_iso(legs[-1]["etd"]) + hours(12) if len(legs) == 2 else etd + hours(24)
    arr = max(snapshot - hours(want), floor)
    ev.append({"port": last["to_port"], "event": "VESSEL_ARRIVED",
               "timestamp": iso(arr - hours(3))})
    ev.append({"port": last["to_port"], "event": "DISCHARGED", "timestamp": iso(arr)})
    if dwell_override_hours is None and rng.random() < 0.30:
        ev.append({"port": last["to_port"], "event": "GATE_OUT",
                   "timestamp": iso(arr + hours(rng.uniform(2, 24)))})
        return ev, None
    return ev, (snapshot - arr).total_seconds() / 3600.0


def generate_record(rng: random.Random, accounts: list[dict], snapshot: datetime,
                    rates: dict[str, float], clean: bool) -> tuple[dict, list[str]]:
    origin, dest, benchmark, lane_tol, std_hub = rng.choice(LANES)
    account = rng.choice(accounts)
    loop = rng.choice(SERVICE_LOOPS)
    booked_vessel, booked_voyage = vessel_name(rng), voyage_no(rng)
    booked_imo = imo(rng)

    phase = rng.choices(PHASES, weights=PHASE_WEIGHTS)[0]
    if std_hub is None and phase == "hub":
        phase = "leg1"

    # ---- decide what to inject (before the schedule is built, because one of the
    # transit-time cases has to be baked into the BOOKING itself) --------------- #
    injected: list[str] = []
    if not clean:
        for fam in FAMILIES:
            if rng.random() < rates[fam]:
                injected.append(fam)
        # dwell only makes sense where the box is sitting somewhere
        if "dwell" in injected and phase not in ("origin", "hub", "destination"):
            injected.remove("dwell")

    # Transit-time exceptions come in two flavours. Either the transit stretched
    # after booking (handled further down with the other injections), or the
    # booking was quoted off-guide in the first place: nothing changes afterwards,
    # same vessel, same routing, stable ETA — the lane simply does not perform the
    # way the routing guide says it does. The second case is the one only this
    # detector can catch, so it has to exist in the data.
    offguide_booking = 0.0
    if "transit_time" in injected and rng.random() < 0.45:
        offguide_booking = lane_tol + 3.0 + rng.uniform(3.0, 14.0)

    booked_transit = benchmark + rng.uniform(-1.0, 1.0) + offguide_booking
    if phase == "origin":
        etd = snapshot + days(rng.uniform(1, 6))
    elif phase == "leg1":
        etd = snapshot - days(rng.uniform(0.5, booked_transit * 0.40))
    elif phase == "hub":
        etd = snapshot - days(rng.uniform(booked_transit * 0.45, booked_transit * 0.60))
    elif phase == "leg2":
        etd = snapshot - days(rng.uniform(booked_transit * 0.62, booked_transit * 0.92))
    else:
        etd = snapshot - days(rng.uniform(booked_transit * 1.00, booked_transit * 1.08))

    booking_date = etd - days(rng.uniform(8, 30))
    booked_eta = etd + days(booked_transit)

    # ---- current state starts as a copy of the booking -------------------- #
    cur_vessel, cur_voyage, cur_imo, cur_loop = booked_vessel, booked_voyage, booked_imo, loop
    cur_hub = std_hub
    cur_dest = dest
    eta_shift_hours = rng.uniform(-18, 18)          # benign jitter, below thresholds
    daily_shift_hours = rng.uniform(-8, 8)
    added_transit_days = 0.0
    # Injected ETA movement is kept on ONE side (delay) whenever several families
    # are injected together, so two injections can never cancel each other out and
    # silently turn a labelled exception into an undetectable row.
    delay_hours = 0.0
    dwell_override = None
    routing_note = None

    # benign variation: equivalent-hub swap (must NOT be flagged)
    if std_hub and not clean and rng.random() < 0.05 and "routing_change" not in injected:
        alt = equivalent_hub(std_hub, rng)
        if alt:
            cur_hub = alt
            routing_note = "equivalent hub"

    # benign variation: same vessel, renumbered voyage (must NOT be flagged)
    if not clean and rng.random() < 0.06 and "vessel_swap" not in injected:
        cur_voyage = voyage_no(rng)

    # ---- injections -------------------------------------------------------- #
    if "routing_change" in injected:
        kind = rng.choices(["hub_change", "added_leg", "destination_change"],
                           weights=[50, 30, 20])[0]
        # "add a transshipment" only means something on a lane booked direct; on a
        # lane that already transships, the equivalent change is moving the hub.
        if std_hub is None and kind == "hub_change":
            kind = "added_leg"
        elif std_hub is not None and kind == "added_leg":
            kind = "hub_change"
        if kind == "hub_change":
            cur_hub = non_equivalent_hub(std_hub, rng)
            added_transit_days += rng.uniform(2.0, 6.0)
            routing_note = "hub change"
        elif kind == "added_leg":
            cur_hub = cur_hub or rng.choice(HUBS)
            added_transit_days += rng.uniform(2.5, 7.0)
            routing_note = "added transshipment"
        else:
            cur_dest = rng.choice([p for p in ("USMIA", "USSAV", "USNYC", "USHOU",
                                               "USLAX", "NLRTM", "BEANR")
                                   if p != dest])
            added_transit_days += rng.uniform(1.0, 5.0)
            routing_note = "destination change"

    if "vessel_swap" in injected:
        cur_vessel = vessel_name(rng)
        while cur_vessel == booked_vessel:
            cur_vessel = vessel_name(rng)
        cur_imo = imo(rng)
        cur_voyage = voyage_no(rng)
        if rng.random() < 0.45:
            cur_loop = rng.choice([s for s in SERVICE_LOOPS if s != loop])
        delay_hours += rng.uniform(40, 120)

    if "dwell" in injected:
        limits = {"origin": 96, "hub": 120, "destination": 72}
        dwell_override = limits[phase] + 12 + 24 + rng.uniform(8, 220)

    if "eta_drift" in injected:
        early_ok = injected == ["eta_drift"] and rng.random() < 0.30
        if early_ok:
            delay_hours -= rng.uniform(48, 200)      # arriving early breaks plans too
            daily_shift_hours = -rng.uniform(14, 60)
        else:
            delay_hours += rng.uniform(48, 220)
            daily_shift_hours = rng.uniform(14, 60)

    if "transit_time" in injected and not offguide_booking:
        added_transit_days += lane_tol + 3.0 + rng.uniform(3.0, 14.0)

    # A longer routing pushes the ETA out — that is a real consequence of the
    # injected change, not extra noise.
    current_eta = booked_eta + hours(eta_shift_hours + delay_hours) + days(added_transit_days)
    previous_eta = current_eta - hours(daily_shift_hours)

    # ---- assemble ---------------------------------------------------------- #
    booked_legs, feeder = build_legs(origin, dest, std_hub, etd, booked_eta, rng,
                                     loop, booked_vessel, booked_voyage)
    current_etd = etd if phase != "origin" else etd + hours(rng.uniform(0, 12))
    keep_feeder = feeder if (cur_hub == std_hub and cur_dest == dest) else None
    current_legs, _ = build_legs(origin, cur_dest, cur_hub, current_etd, current_eta,
                                 rng, cur_loop, cur_vessel, cur_voyage,
                                 feeder=keep_feeder)
    events, achieved_dwell = build_events(current_legs, phase, snapshot, rng, dwell_override)
    if "dwell" in injected:
        # The timeline could not actually hold the dwell we asked for (short lane,
        # box only just discharged). Drop the label rather than record an
        # exception the data does not contain.
        limits = {"origin": 96, "hub": 120, "destination": 72}
        if achieved_dwell is None or achieved_dwell < limits[phase] + 12 + 24 + 6:
            injected.remove("dwell")
            # rebuild with a benign dwell so the row is unambiguously clean rather
            # than parked just under the detection threshold
            events, achieved_dwell = build_events(current_legs, phase, snapshot, rng, None)

    status = {"origin": "AT_ORIGIN_TERMINAL", "leg1": "ON_WATER",
              "hub": "AT_TRANSSHIPMENT", "leg2": "ON_WATER",
              "destination": "AT_DESTINATION_TERMINAL"}[phase]

    # Day-over-day ETA history. The entry for D-1 is the previous snapshot's ETA;
    # older entries carry small independent jitter so the series looks real.
    eta_history = []
    for i in range(4, 0, -1):
        extra = 0.0 if i == 1 else rng.uniform(-4, 4) * (i - 1)
        eta_history.append({
            "as_of": iso(snapshot - days(i)),
            "eta": iso(current_eta - hours(daily_shift_hours + extra)),
        })

    last_free_day = current_eta + days(rng.uniform(3, 7))
    if rng.random() < 0.08:
        last_free_day = current_eta - days(rng.uniform(0.5, 2))

    record = {
        "snapshot_date": snapshot.strftime("%Y-%m-%d"),
        "snapshot_time": iso(snapshot),
        "container_id": make_container_id(rng),
        "container_type": rng.choice(CONTAINER_TYPES),
        "booking_id": f"BK{rng.randint(10000000, 99999999)}",
        "bill_of_lading": f"BL{rng.randint(100000000, 999999999)}",
        "account_id": account["account_id"],
        "account_name": account["account_name"],
        "account_tier": account["account_tier"],
        "service_contract": account["service_contract"],
        "commodity": rng.choice(COMMODITIES),
        "cargo_value_usd": int(rng.lognormvariate(11.2, 0.9)),
        "status": status,
        "booked": {
            "booking_date": iso(booking_date),
            "origin_port": origin,
            "destination_port": dest,
            "vessel_name": booked_vessel,
            "vessel_imo": booked_imo,
            "voyage": booked_voyage,
            "service_loop": loop,
            "etd": iso(etd),
            "eta": iso(booked_eta),
            "transit_days": round(booked_transit, 2),
            "routing": booked_legs,
        },
        "current": {
            "origin_port": origin,
            "destination_port": cur_dest,
            "vessel_name": cur_vessel,
            "vessel_imo": cur_imo,
            "voyage": cur_voyage,
            "service_loop": cur_loop,
            "etd": iso(current_etd),
            "eta": iso(current_eta),
            "routing": current_legs,
        },
        "previous_snapshot_eta": iso(previous_eta),
        "eta_history": eta_history,
        "port_events": sorted(events, key=lambda e: e["timestamp"]),
        "routing_guide": {
            "lane": f"{origin}-{dest}",
            "benchmark_transit_days": benchmark,
            "tolerance_days": lane_tol,
            "standard_transshipment": [std_hub] if std_hub else [],
        },
        "last_free_day": iso(last_free_day),
    }
    return record, injected


# --------------------------------------------------------------------------- #
# CSV flattening
# --------------------------------------------------------------------------- #

CSV_COLUMNS = [
    "snapshot_date", "container_id", "container_type", "booking_id", "account_id",
    "account_name", "account_tier", "commodity", "cargo_value_usd", "status",
    "booked_origin_port", "booked_destination_port", "booked_vessel_name",
    "booked_voyage", "booked_service_loop", "booked_etd", "booked_eta",
    "booked_transit_days", "booked_routing_json",
    "current_destination_port", "current_vessel_name", "current_voyage",
    "current_service_loop", "current_etd", "current_eta", "current_routing_json",
    "eta_history_json", "port_events_json", "routing_guide_json", "last_free_day",
]


def to_csv_row(r: dict) -> dict:
    b, c = r["booked"], r["current"]
    return {
        "snapshot_date": r["snapshot_date"], "container_id": r["container_id"],
        "container_type": r["container_type"], "booking_id": r["booking_id"],
        "account_id": r["account_id"], "account_name": r["account_name"],
        "account_tier": r["account_tier"], "commodity": r["commodity"],
        "cargo_value_usd": r["cargo_value_usd"], "status": r["status"],
        "booked_origin_port": b["origin_port"],
        "booked_destination_port": b["destination_port"],
        "booked_vessel_name": b["vessel_name"], "booked_voyage": b["voyage"],
        "booked_service_loop": b["service_loop"], "booked_etd": b["etd"],
        "booked_eta": b["eta"], "booked_transit_days": b["transit_days"],
        "booked_routing_json": json.dumps(b["routing"], separators=(",", ":")),
        "current_destination_port": c["destination_port"],
        "current_vessel_name": c["vessel_name"], "current_voyage": c["voyage"],
        "current_service_loop": c["service_loop"], "current_etd": c["etd"],
        "current_eta": c["eta"],
        "current_routing_json": json.dumps(c["routing"], separators=(",", ":")),
        "eta_history_json": json.dumps(r["eta_history"], separators=(",", ":")),
        "port_events_json": json.dumps(r["port_events"], separators=(",", ":")),
        "routing_guide_json": json.dumps(r["routing_guide"], separators=(",", ":")),
        "last_free_day": r["last_free_day"],
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate a synthetic on-water container snapshot.")
    p.add_argument("--rows", type=int, default=40000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default="data/out/snapshot.jsonl")
    p.add_argument("--snapshot-date", default=None,
                   help="YYYY-MM-DD (default: today, 06:00 UTC)")
    p.add_argument("--accounts", type=int, default=180)
    p.add_argument("--csv", action="store_true", help="also write a flattened CSV export")
    p.add_argument("--clean", action="store_true",
                   help="inject nothing — used to measure the noise floor")
    for fam, default in (("routing-change", 0.012), ("vessel-swap", 0.015),
                         ("dwell", 0.010), ("eta-drift", 0.020), ("transit-time", 0.010)):
        p.add_argument(f"--rate-{fam}", type=float, default=default,
                       help=f"per-container injection rate for {fam.replace('-', '_')}")
    args = p.parse_args(argv)

    rates = {
        "routing_change": args.rate_routing_change,
        "vessel_swap": args.rate_vessel_swap,
        "dwell": args.rate_dwell,
        "eta_drift": args.rate_eta_drift,
        "transit_time": args.rate_transit_time,
    }

    if args.snapshot_date:
        snap = datetime.strptime(args.snapshot_date, "%Y-%m-%d").replace(
            hour=6, tzinfo=timezone.utc)
    else:
        snap = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)

    rng = random.Random(args.seed)
    accounts = build_accounts(rng, args.accounts)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    truth: dict[str, list[str]] = {}
    counts = {f: 0 for f in FAMILIES}
    dirty = 0

    csv_writer = csv_fh = None
    if args.csv:
        csv_fh = open(args.out + ".csv", "w", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_fh, fieldnames=CSV_COLUMNS)
        csv_writer.writeheader()

    with open(args.out, "w", encoding="utf-8") as fh:
        for _ in range(args.rows):
            rec, injected = generate_record(rng, accounts, snap, rates, args.clean)
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            if csv_writer:
                csv_writer.writerow(to_csv_row(rec))
            if injected:
                truth[rec["container_id"]] = injected
                dirty += 1
                for f in injected:
                    counts[f] += 1
    if csv_fh:
        csv_fh.close()

    gt_path = args.out + ".ground_truth.json"
    with open(gt_path, "w", encoding="utf-8") as fh:
        json.dump({
            "snapshot_date": snap.strftime("%Y-%m-%d"),
            "seed": args.seed,
            "rows": args.rows,
            "containers_with_injected_exceptions": dirty,
            "injected_counts": counts,
            "containers": truth,
        }, fh, indent=2)

    print(f"wrote {args.rows} rows -> {args.out}")
    if args.csv:
        print(f"wrote CSV export     -> {args.out}.csv")
    print(f"wrote ground truth   -> {gt_path}")
    print(f"containers with injected exceptions: {dirty} "
          f"({dirty / max(args.rows, 1) * 100:.2f}%)")
    for f in FAMILIES:
        print(f"  {f:16s} {counts[f]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
