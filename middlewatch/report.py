"""Report rendering: console, JSON, Markdown.

One line per exception with container, account, what changed, why it matters and
the recommended action — plus the evidence behind it, because a report an
operator cannot check is a report an operator will stop believing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import FAMILY_LABELS, __version__
from .engine import RunResult, detector_stats
from .models import Incident

BAND_MARK = {"critical": "!!", "high": "! ", "medium": "· ", "low": "  "}


# --------------------------------------------------------------------------- #
# Console
# --------------------------------------------------------------------------- #

def render_console(result: RunResult, executive_summary: str = "",
                   limit: int = 25, show_evidence: bool = True) -> str:
    out: list[str] = []
    w = 92
    out.append("=" * w)
    out.append(f" MIDDLE WATCH — on-water exception report   {result.snapshot_date}")
    out.append("=" * w)
    bands = result.band_counts()
    out.append(f" {result.rows:,} containers scanned in {result.runtime_seconds:.1f}s  |  "
               f"{len(result.incidents)} exceptions  |  "
               f"{bands['critical']} critical / {bands['high']} high / "
               f"{bands['medium']} medium / {bands['low']} low")
    out.append(f" {len(result.suppressed)} findings suppressed below severity "
               f"{result.config_summary.get('min_severity_to_report')}  |  "
               f"{len({i.account_id for i in result.incidents})} accounts affected")
    fam = "  ".join(f"{FAMILY_LABELS[k].split()[0]}:{v}"
                    for k, v in result.family_counts.items())
    out.append(f" signals — {fam}")
    out.append("=" * w)

    if executive_summary:
        out.append("")
        for line in _wrap(executive_summary, w - 2):
            out.append(f" {line}")
        out.append("")

    shown = result.incidents[:limit] if limit else result.incidents
    for n, inc in enumerate(shown, 1):
        out.append("-" * w)
        out.append(f"{BAND_MARK[inc.band]}{n:>3}. [{inc.severity:>3}] {inc.container_id}  "
                   f"{inc.account_name} ({inc.account_tier})  {inc.lane}  {inc.status}")
        out.append(f"      signals : {', '.join(FAMILY_LABELS[f] for f in inc.families)}"
                   f"   (root: {FAMILY_LABELS[inc.primary_family]})")
        for f in inc.findings:
            out.append(f"      changed : {f.headline}")
        for i, line in enumerate(_wrap(inc.why_it_matters, w - 16)):
            out.append(f"      why     : {line}" if i == 0 else f"                {line}")
        for i, line in enumerate(_wrap(inc.recommended_action, w - 16)):
            out.append(f"      action  : {line}" if i == 0 else f"                {line}")
        out.append(f"      eta     : booked {inc.eta_booked}  ->  now {inc.eta_current}  "
                   f"({inc.days_to_arrival:.1f}d out)  LFD {inc.last_free_day}")
        if show_evidence:
            out.append("      evidence:")
            for f in inc.findings:
                for e in f.evidence:
                    out.append(f"                - {e.render()}")
        if inc.triage_source == "claude":
            out.append("      (triage written by the agent after verifying the container)")

    if limit and len(result.incidents) > limit:
        out.append("-" * w)
        out.append(f" ... {len(result.incidents) - limit} more exceptions in the full report "
                   f"(--limit 0 to print all, --json for the file)")
    out.append("=" * w)
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = (text or "").split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #

def to_payload(result: RunResult, executive_summary: str = "",
               agent_meta: dict[str, Any] | None = None,
               include_evidence: bool = True,
               max_incidents: int = 0) -> dict[str, Any]:
    incidents = result.incidents[:max_incidents] if max_incidents else result.incidents
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": f"middle-watch-agent {__version__}",
        "summary": result.summary(),
        "executive_summary": executive_summary,
        "agent": agent_meta or {"mode": "rules", "note": "deterministic triage, no model call"},
        "detector_performance": detector_stats(result),
        "account_rollup": result.account_rollup(limit=40),
        "incidents": [i.to_dict(include_evidence=include_evidence) for i in incidents],
    }


def to_json(result: RunResult, executive_summary: str = "",
            agent_meta: dict[str, Any] | None = None, indent: int = 2) -> str:
    return json.dumps(to_payload(result, executive_summary, agent_meta),
                      indent=indent, default=str)


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

def to_markdown(result: RunResult, executive_summary: str = "",
                limit: int = 50) -> str:
    bands = result.band_counts()
    md: list[str] = [
        f"# Middle Watch — on-water exception report",
        "",
        f"**Snapshot:** {result.snapshot_date}  |  **Containers scanned:** {result.rows:,}  "
        f"|  **Runtime:** {result.runtime_seconds:.1f}s",
        "",
        f"**{len(result.incidents)} exceptions** — {bands['critical']} critical, "
        f"{bands['high']} high, {bands['medium']} medium, {bands['low']} low. "
        f"{len(result.suppressed)} findings suppressed below the severity floor.",
        "",
    ]
    if executive_summary:
        md += ["## Summary", "", executive_summary, ""]

    md += ["## Exception queue", "",
           "| # | Sev | Container | Account | Lane | Signals | What changed | Action |",
           "|---|-----|-----------|---------|------|---------|--------------|--------|"]
    for n, i in enumerate(result.incidents[:limit], 1):
        signals = ", ".join(FAMILY_LABELS[f] for f in i.families)
        changed = _md_escape(" | ".join(f.headline for f in i.findings))
        md.append(f"| {n} | {i.severity} | `{i.container_id}` | {i.account_name} "
                  f"({i.account_tier}) | {i.lane} | {signals} | {changed} | "
                  f"{_md_escape(i.recommended_action)} |")

    md += ["", "## By account", "",
           "| Account | Tier | Incidents | Critical | Worst severity |",
           "|---------|------|-----------|----------|----------------|"]
    for a in result.account_rollup(limit=15):
        md.append(f"| {a['account_name']} | {a['account_tier']} | {a['incidents']} | "
                  f"{a['critical']} | {a['max_severity']} |")

    md += ["", "## Evidence", ""]
    for i in result.incidents[:limit]:
        md.append(f"### {i.container_id} — severity {i.severity} ({i.band})")
        md.append("")
        md.append(f"- **Account:** {i.account_name} ({i.account_tier}) — lane {i.lane}")
        md.append(f"- **Why it matters:** {i.why_it_matters}")
        md.append(f"- **Recommended action:** {i.recommended_action}")
        for f in i.findings:
            md.append(f"- **{FAMILY_LABELS[f.family]}:** {f.headline}")
            for e in f.evidence:
                md.append(f"  - `{e.field_path}` = `{e.observed}`"
                          + (f" (booked/expected `{e.expected}`)" if e.expected is not None else "")
                          + (f" — threshold `{e.threshold}`" if e.threshold is not None else "")
                          + (f" — {e.note}" if e.note else ""))
        md.append("")
    return "\n".join(md)


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")
