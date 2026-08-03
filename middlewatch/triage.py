"""Deterministic triage narrative.

Every incident gets three sentences an operator can act on — what changed, why it
matters, what to do — generated from the finding metrics with no model in the
loop. This is what `--no-llm` produces for the whole queue, and what the tail of
the queue gets when the model is only asked to write up the escalated top slice.

Keeping this path complete is a design choice: the agent must degrade to a
working tool when the API is unreachable, not to an empty report.
"""

from __future__ import annotations

from .models import Finding, Incident

_ACTION = {
    "routing_change": {
        "destination_change": "Confirm the new discharge port with the account before the "
                              "vessel arrives — inland delivery, customs entry and the "
                              "delivery order are all filed against the old port.",
        "added_transshipment": "Validate the connection at the new hub and re-issue the "
                               "arrival notice with the revised ETA.",
        "removed_transshipment": "Confirm the direct routing is intentional and update the "
                                 "customer's ETA — an earlier arrival needs a delivery slot.",
        "hub_change": "Check the onward connection at the new hub and tell the account "
                      "before they see it on their own tracking.",
        "equivalent_hub_change": "Re-check the connection window at the substitute hub; the "
                                 "swap is routine but this one costs transit days.",
    },
    "vessel_swap": {
        "vessel_and_loop_change": "Different service string means a different port rotation — "
                                  "re-verify the full routing, not just the ETA.",
        "vessel_change": "Update the ETA on the booking and notify the account; check whether "
                         "the delivery appointment still holds.",
        "service_loop_change": "Confirm the new loop calls the same discharge port on the "
                               "same rotation.",
    },
    "dwell": {
        "transshipment": "Chase the connection at the hub — the box has missed at least one "
                         "sailing window and nothing in the file says why.",
        "destination": "Push the consignee to pick up: free time is burning and demurrage "
                       "starts on the last free day.",
        "origin": "Check the box has an actual load confirmation; a container gated in and "
                  "not loaded is usually a documentation or VGM hold.",
    },
    "eta_drift": {
        "default": "Re-quote the ETA to the account and re-check the delivery appointment "
                   "and free-time window against the new date.",
        "past_lfd": "Re-quote the ETA and pre-negotiate free time now — the projected arrival "
                    "is already past the last free day.",
    },
    "transit_time": {
        "slower": "Flag the lane, not just the box: the routing guide promises a transit this "
                  "service is not delivering, and every booking on it is quoted wrong.",
        "faster": "Verify the routing-guide benchmark for this lane — it looks stale, and a "
                  "stale benchmark prices the next contract wrong.",
    },
}


def _why(inc: Incident, primary: Finding) -> str:
    bits: list[str] = []
    fam = inc.primary_family
    m = primary.metrics

    if fam == "routing_change":
        added = m.get("added_transit_days", 0)
        bits.append(f"the cargo is no longer following the booked routing"
                    + (f" and the change adds {added:+.1f} days of transit" if added else ""))
    elif fam == "vessel_swap":
        bits.append(f"the swap moves the arrival by {m.get('eta_impact_hours', 0):+.0f} hours")
    elif fam == "dwell":
        bits.append(f"the box has been static for {m.get('dwell_hours', 0):.0f} hours at "
                    f"{m.get('port')} with no onward movement recorded")
    elif fam == "eta_drift":
        bits.append(f"the arrival date has moved {m.get('baseline_drift_hours', 0):+.0f} hours "
                    f"since booking ({m.get('daily_drift_hours', 0):+.0f}h of it overnight)")
    elif fam == "transit_time":
        dev = m.get("deviation_vs_benchmark_days", 0.0)
        bits.append(f"this lane is running {abs(dev):.1f} days "
                    f"{'slower' if dev > 0 else 'faster'} than the routing-guide benchmark "
                    f"of {m.get('benchmark_transit_days')} days, which is "
                    f"{m.get('excess_days', 0):.1f} days outside the agreed tolerance")

    if inc.days_to_arrival <= 5:
        bits.append(f"and it arrives in {max(inc.days_to_arrival, 0):.1f} days, so there is "
                    f"almost no room left to recover")
    if "projected arrival past last free day" in inc.severity_drivers:
        bits.append("with the projected arrival already past the last free day")
    if inc.account_tier in ("strategic", "key"):
        bits.append(f"on a {inc.account_tier} account")

    if len(inc.findings) > 1:
        others = " and ".join(f.label for f in inc.findings if f.family != fam)
        bits.append(f"— {others} also fired on this container, which is consistent with one "
                    f"root cause rather than {len(inc.findings)} separate problems")

    sentence = ", ".join(bits).replace(", —", " —")
    return sentence[:1].upper() + sentence[1:] + "."


def _action(inc: Incident, primary: Finding) -> str:
    fam = inc.primary_family
    m = primary.metrics
    table = _ACTION[fam]
    if fam == "routing_change":
        return table.get(m.get("kind", ""), table["hub_change"])
    if fam == "vessel_swap":
        return table.get(m.get("kind", ""), table["vessel_change"])
    if fam == "dwell":
        return table.get(m.get("location", ""), table["transshipment"])
    if fam == "eta_drift":
        return table["past_lfd"] if m.get("past_last_free_day") else table["default"]
    if fam == "transit_time":
        return table.get(m.get("direction", "slower"), table["slower"])
    return "Review the container."


def annotate(inc: Incident) -> Incident:
    """Fill what_changed / why_it_matters / recommended_action from the evidence."""
    primary = inc.primary_finding
    inc.what_changed = " | ".join(f.headline for f in inc.findings)
    inc.why_it_matters = _why(inc, primary)
    inc.recommended_action = _action(inc, primary)
    inc.triage_source = "rules"
    return inc


def annotate_all(incidents: list[Incident]) -> list[Incident]:
    return [annotate(i) for i in incidents]
