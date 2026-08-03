"""Detector unit tests.

Two things are being protected here:
  1. every detector fires on the exception it owns, and
  2. every detector STAYS QUIET on the near-miss that looks like it.

The second half is the one that matters. A detector that only has positive tests
will happily drift into flagging everything.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from middlewatch.config import load_config          # noqa: E402
from middlewatch.detectors import run_detectors      # noqa: E402
from middlewatch.loader import Container             # noqa: E402
from middlewatch.severity import build_incident      # noqa: E402

SNAP = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def config():
    return load_config()


def make_container(**over) -> Container:
    """A clean, healthy container. Tests break exactly one thing at a time."""
    etd = SNAP - timedelta(days=12)
    eta = etd + timedelta(days=34)
    leg = {"seq": 1, "from_port": "CNSHA", "to_port": "PACTB", "mode": "VESSEL",
           "vessel_name": "MV NORTHERN VOYAGER", "voyage": "018E", "service_loop": "TPX-5",
           "etd": iso(etd), "eta": iso(etd + timedelta(days=17))}
    leg2 = {"seq": 2, "from_port": "PACTB", "to_port": "USMIA", "mode": "VESSEL",
            "vessel_name": "MV CORAL TRADER", "voyage": "004W", "service_loop": "LAM-2",
            "etd": iso(etd + timedelta(days=18)), "eta": iso(eta)}
    rec = {
        "snapshot_date": "2026-08-03", "snapshot_time": iso(SNAP),
        "container_id": "MWSU1234565", "account_id": "ACC-0001",
        "account_name": "Northline Industrial Supply", "account_tier": "standard",
        "status": "ON_WATER", "cargo_value_usd": 80000,
        "booked": {"origin_port": "CNSHA", "destination_port": "USMIA",
                   "vessel_name": "MV NORTHERN VOYAGER", "vessel_imo": "9123456",
                   "voyage": "018E", "service_loop": "TPX-5",
                   "etd": iso(etd), "eta": iso(eta), "transit_days": 34.0,
                   "routing": [leg, leg2]},
        "current": {"origin_port": "CNSHA", "destination_port": "USMIA",
                    "vessel_name": "MV NORTHERN VOYAGER", "vessel_imo": "9123456",
                    "voyage": "018E", "service_loop": "TPX-5",
                    "etd": iso(etd), "eta": iso(eta),
                    "routing": [dict(leg), dict(leg2)]},
        "previous_snapshot_eta": iso(eta),
        "eta_history": [{"as_of": iso(SNAP - timedelta(days=1)), "eta": iso(eta)}],
        "port_events": [
            {"port": "CNSHA", "event": "GATE_IN", "timestamp": iso(etd - timedelta(days=3))},
            {"port": "CNSHA", "event": "LOADED", "timestamp": iso(etd - timedelta(hours=10))},
            {"port": "CNSHA", "event": "VESSEL_DEPARTED", "timestamp": iso(etd)},
        ],
        "routing_guide": {"lane": "CNSHA-USMIA", "benchmark_transit_days": 34.0,
                          "tolerance_days": 2.0, "standard_transshipment": ["PACTB"]},
        "last_free_day": iso(eta + timedelta(days=5)),
    }
    for key, value in over.items():
        if "." in key:
            parent, child = key.split(".", 1)
            rec[parent][child] = value
        else:
            rec[key] = value
    return Container(rec)


def families(c: Container, config) -> set[str]:
    return {f.family for f in run_detectors(c, config)}


# --------------------------------------------------------------------------- #
# The clean baseline must be silent
# --------------------------------------------------------------------------- #

def test_healthy_container_raises_nothing(config):
    assert families(make_container(), config) == set()


# --------------------------------------------------------------------------- #
# Routing change
# --------------------------------------------------------------------------- #

def test_destination_change_is_flagged(config):
    c = make_container()
    c.current["destination_port"] = "USSAV"
    c.current["routing"][1]["to_port"] = "USSAV"
    assert "routing_change" in families(c, config)


def test_equivalent_hub_swap_at_no_cost_is_ignored(config):
    """PACTB -> JMKIN inside the same hub group, same transit: this is noise."""
    c = make_container()
    c.current["routing"][0]["to_port"] = "JMKIN"
    c.current["routing"][1]["from_port"] = "JMKIN"
    assert "routing_change" not in families(c, config)


def test_non_equivalent_hub_change_is_flagged(config):
    c = make_container()
    c.current["routing"][0]["to_port"] = "NLRTM"
    c.current["routing"][1]["from_port"] = "NLRTM"
    assert "routing_change" in families(c, config)


# --------------------------------------------------------------------------- #
# Vessel swap
# --------------------------------------------------------------------------- #

def test_vessel_swap_with_eta_impact_is_flagged(config):
    c = make_container()
    c.current["vessel_name"] = "MV IRON SENTINEL"
    c.current["vessel_imo"] = "9999999"
    c.current["eta"] = iso(c.booked_eta + timedelta(hours=48))
    c = Container(c.raw)
    assert "vessel_swap" in families(c, config)


def test_voyage_renumbering_on_the_same_vessel_is_ignored(config):
    c = make_container()
    c.current["voyage"] = "019E"
    assert "vessel_swap" not in families(c, config)


def test_paper_swap_with_no_eta_impact_is_ignored(config):
    c = make_container()
    c.current["vessel_name"] = "MV IRON SENTINEL"
    c.current["vessel_imo"] = "9999999"          # different hull, same schedule, same loop
    assert "vessel_swap" not in families(c, config)


# --------------------------------------------------------------------------- #
# Dwell
# --------------------------------------------------------------------------- #

def _discharged_at_hub(hours_ago: float):
    c = make_container(status="AT_TRANSSHIPMENT")
    events = c.raw["port_events"] + [
        {"port": "PACTB", "event": "VESSEL_ARRIVED",
         "timestamp": iso(SNAP - timedelta(hours=hours_ago + 2))},
        {"port": "PACTB", "event": "DISCHARGED",
         "timestamp": iso(SNAP - timedelta(hours=hours_ago))},
    ]
    return Container({**c.raw, "port_events": events})


def test_long_transshipment_dwell_is_flagged(config):
    assert "dwell" in families(_discharged_at_hub(260), config)


def test_dwell_inside_the_limit_plus_grace_is_ignored(config):
    assert "dwell" not in families(_discharged_at_hub(90), config)


def test_dwell_closed_by_a_load_event_is_ignored(config):
    c = _discharged_at_hub(260)
    events = c.raw["port_events"] + [
        {"port": "PACTB", "event": "LOADED", "timestamp": iso(SNAP - timedelta(hours=6))}]
    assert "dwell" not in families(Container({**c.raw, "port_events": events}), config)


# --------------------------------------------------------------------------- #
# ETA drift
# --------------------------------------------------------------------------- #

def test_baseline_eta_drift_is_flagged(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=72))
    assert "eta_drift" in families(Container(c.raw), config)


def test_eta_jitter_below_the_threshold_is_ignored(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=17))
    c.raw["previous_snapshot_eta"] = iso(c.booked_eta + timedelta(hours=14))
    assert "eta_drift" not in families(Container(c.raw), config)


def test_overnight_drift_is_flagged_even_when_the_baseline_looks_fine(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=18))
    c.raw["previous_snapshot_eta"] = iso(c.booked_eta - timedelta(hours=6))
    assert "eta_drift" in families(Container(c.raw), config)


# --------------------------------------------------------------------------- #
# Transit time
# --------------------------------------------------------------------------- #

def test_transit_beyond_guide_plus_tolerance_is_flagged(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.current_eta + timedelta(days=9))
    assert "transit_time" in families(Container(c.raw), config)


def test_transit_inside_the_lane_tolerance_is_ignored(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.current_eta + timedelta(days=2))
    assert "transit_time" not in families(Container(c.raw), config)


# --------------------------------------------------------------------------- #
# Grouping, severity, evidence
# --------------------------------------------------------------------------- #

def test_correlated_signals_group_into_one_incident_with_the_root_cause_first(config):
    c = make_container()
    c.raw["current"]["routing"][0]["to_port"] = "NLRTM"
    c.raw["current"]["routing"][1]["from_port"] = "NLRTM"
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(days=6))
    c = Container(c.raw)
    findings = run_detectors(c, config)
    incident = build_incident(c, findings, config)
    assert len(incident.findings) > 1
    assert incident.primary_family == "routing_change"      # root cause, not the symptom


def test_every_finding_carries_field_level_evidence(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=96))
    for finding in run_detectors(Container(c.raw), config):
        assert finding.evidence, f"{finding.family} produced no evidence"
        for e in finding.evidence:
            assert e.field_path and e.observed is not None


def test_strategic_account_scores_higher_than_standard(config):
    def sev(tier):
        c = make_container(account_tier=tier)
        c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=96))
        c = Container(c.raw)
        return build_incident(c, run_detectors(c, config), config).severity
    assert sev("strategic") > sev("standard")


def test_thresholds_are_configurable_without_touching_code(config):
    c = make_container()
    c.raw["current"]["eta"] = iso(c.booked_eta + timedelta(hours=30))
    c = Container(c.raw)
    assert "eta_drift" in families(c, config)
    stricter = config.with_override("eta_drift.min_drift_hours", 48) \
                     .with_override("eta_drift.min_daily_drift_hours", 48)
    assert "eta_drift" not in families(c, stricter)
