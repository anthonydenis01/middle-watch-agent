"""Command line entry point.

    python -m middlewatch run --snapshot data/out/snapshot.jsonl
    python -m middlewatch run --snapshot data/out/snapshot.jsonl --no-llm
    python -m middlewatch run --snapshot ... --json out/report.json --demo demo.html
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import FAMILIES, __version__
from .config import load_config
from .engine import analyze
from .report import render_console, to_json, to_markdown, to_payload
from .tools import ToolSession
from .triage import annotate_all


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="middlewatch",
        description="Middle Watch — on-water exception monitoring agent for ocean freight "
                    "operations.")
    p.add_argument("--version", action="version", version=f"middle-watch-agent {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the morning exception report")
    run.add_argument("--snapshot", required=True, help="daily container-status file (.jsonl/.csv/.json)")
    run.add_argument("--config", default=None, help="thresholds file (default config/thresholds.toml)")
    run.add_argument("--families", nargs="*", choices=list(FAMILIES), default=None,
                     help="restrict to specific detectors")
    run.add_argument("--no-llm", action="store_true",
                     help="skip the agentic loop; deterministic detection + rule-generated "
                          "triage (no API key needed)")
    run.add_argument("--model", default=None, help="Claude model for the agentic loop")
    run.add_argument("--top", type=int, default=25,
                     help="how many containers the agent is asked to escalate (default 25)")
    run.add_argument("--limit", type=int, default=25,
                     help="incidents printed to the console; 0 = all (default 25)")
    run.add_argument("--max-turns", type=int, default=24)
    run.add_argument("--json", dest="json_out", default=None, help="write the full report as JSON")
    run.add_argument("--md", dest="md_out", default=None, help="write the report as Markdown")
    run.add_argument("--demo", dest="demo_out", default=None,
                     help="write a self-contained demo.html dashboard")
    run.add_argument("--demo-incidents", type=int, default=150,
                     help="how many incidents to embed in the dashboard (default 150)")
    run.add_argument("--eval-metrics", default=None,
                     help="metrics JSON from scripts/evaluate.py, shown in the dashboard")
    run.add_argument("--no-evidence", action="store_true", help="hide evidence lines in the console")
    run.add_argument("--quiet", action="store_true", help="suppress the console report")
    run.add_argument("--verbose", action="store_true", help="log every tool call the agent makes")

    detectors = sub.add_parser("detectors", help="list the detectors and their thresholds")
    detectors.add_argument("--config", default=None)

    inspect = sub.add_parser("container", help="everything known about one container")
    inspect.add_argument("container_id")
    inspect.add_argument("--snapshot", required=True)
    inspect.add_argument("--config", default=None)
    return p


def cmd_run(args) -> int:
    config = load_config(args.config)
    snapshot = Path(args.snapshot)

    executive_summary = ""
    agent_meta = {"mode": "rules", "note": "deterministic triage, no model call"}

    if args.no_llm:
        result = analyze(snapshot, config, families=args.families, keep_containers=False)
        annotate_all(result.incidents)
    else:
        from .agent import DEFAULT_MODEL, AgentUnavailable, run_agent
        session = ToolSession(snapshot, config)
        try:
            outcome = run_agent(session, model=args.model or DEFAULT_MODEL,
                                max_turns=args.max_turns, escalate_top_n=args.top,
                                verbose=args.verbose)
            result = session.full()
            annotate_all(result.incidents)
            executive_summary = session.apply_report(result.incidents)
            agent_meta = {
                "mode": "claude-tool-calling",
                "model": outcome.model,
                "turns": outcome.turns,
                "tool_calls": len(outcome.tool_calls),
                "tools_used": sorted({c["tool"] for c in outcome.tool_calls}),
                "escalated_containers": outcome.escalated,
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "stop_reason": outcome.stop_reason,
                "error": outcome.error,
            }
            if outcome.error:
                print(f"warning: {outcome.error}", file=sys.stderr)
        except AgentUnavailable as exc:
            print(f"agentic loop unavailable: {exc}\n"
                  f"falling back to deterministic triage.", file=sys.stderr)
            result = session.full()
            annotate_all(result.incidents)
            agent_meta = {"mode": "rules", "note": f"fell back: {exc}"}

    if not args.quiet:
        print(render_console(result, executive_summary, limit=args.limit,
                             show_evidence=not args.no_evidence))

    if args.json_out:
        _write(args.json_out, to_json(result, executive_summary, agent_meta))
        print(f"wrote JSON report     -> {args.json_out}", file=sys.stderr)
    if args.md_out:
        _write(args.md_out, to_markdown(result, executive_summary))
        print(f"wrote Markdown report -> {args.md_out}", file=sys.stderr)
    if args.demo_out:
        from .demo import build_demo
        payload = to_payload(result, executive_summary, agent_meta,
                             include_evidence=True, max_incidents=args.demo_incidents)
        metrics = None
        if args.eval_metrics:
            m = json.loads(Path(args.eval_metrics).read_text())
            metrics = {
                "recall_pct": m.get("recall_pct"),
                "family_recall_pct": m.get("family_recall_pct"),
                "caught": m.get("caught"),
                "injected": m.get("injected"),
                "false_positives": m.get("false_positives"),
                "false_positive_pct": m.get("false_positive_pct"),
                "reported": m.get("reported"),
            }
        build_demo(payload, args.demo_out, evaluation=metrics)
        print(f"wrote demo dashboard  -> {args.demo_out}", file=sys.stderr)

    return 0


def cmd_detectors(args) -> int:
    config = load_config(args.config)
    session = ToolSession("", config)
    print(json.dumps(session.list_detectors(), indent=2))
    return 0


def cmd_container(args) -> int:
    config = load_config(args.config)
    session = ToolSession(args.snapshot, config)
    print(json.dumps(session.get_container(args.container_id), indent=2, default=str))
    return 0


def _write(path: str, text: str) -> None:
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        os.makedirs(p.parent, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return {"run": cmd_run, "detectors": cmd_detectors, "container": cmd_container}[
        args.command](args)


if __name__ == "__main__":
    sys.exit(main())
