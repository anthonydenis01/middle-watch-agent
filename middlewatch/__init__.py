"""Middle Watch — on-water exception monitoring agent.

Designed for ocean freight operations: reads a daily container-status snapshot,
detects five families of operational exception, ranks them by severity and hands
an operator a short, evidence-backed queue instead of a spreadsheet.
"""

__version__ = "1.0.0"

FAMILIES = ("routing_change", "vessel_swap", "dwell", "eta_drift", "transit_time")

FAMILY_LABELS = {
    "routing_change": "Routing change",
    "vessel_swap": "Vessel swap",
    "dwell": "Dwell exception",
    "eta_drift": "ETA drift",
    "transit_time": "Transit-time discrepancy",
}
