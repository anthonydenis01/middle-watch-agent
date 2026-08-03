"""The agentic loop.

Claude drives the detectors as tools. It is not handed 40,000 rows and asked to
find problems in one giant prompt — it asks each detector a question, reads the
evidence that comes back, drills into individual containers when a finding needs
verifying, tests a threshold when it suspects noise, and finally writes the
triage for the containers it decided to escalate.

Division of labour, deliberately:
  * the DETECTORS decide what is an exception          — deterministic, auditable
  * the MODEL decides what deserves an operator's day  — judgement, ranking, wording

If the API is unreachable the CLI falls back to `--no-llm`, which produces the
same report with rule-generated triage. The evidence never depends on the model.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from .tools import TOOL_SPECS, ToolSession

DEFAULT_MODEL = os.environ.get("MIDDLEWATCH_MODEL", "claude-sonnet-4-5")

SYSTEM_PROMPT = """\
You are Middle Watch, an on-water exception monitoring agent for ocean freight \
operations. Every morning you review the day's container-status snapshot and hand \
the operations desk a short, ranked queue of containers that need a human today.

Context you must hold on to:
- The desk has tens of thousands of containers on the water. Before this agent, \
exceptions surfaced when the customer called. Your job is to surface them in the \
morning run instead.
- An operator will act on your output before lunch. A queue of 300 items is the same \
as no queue at all.
- Precision matters more than volume. Every escalation you make costs an operator \
time; every false alarm costs you their trust in the whole report.

How to work:
1. Call describe_snapshot, then list_detectors, so you know the file and the \
thresholds you are working with.
2. Run each of the five detectors. Read the evidence, not just the counts.
3. Use rank_incidents to see the grouped, severity-ranked queue. Correlated signals on \
one container are already grouped into one incident — treat them that way.
4. Use get_container on the containers you intend to escalate. Verify the evidence \
actually supports the finding before you put it in front of an operator. If it does \
not, do not escalate it.
5. If a detector looks like it is producing noise, use simulate_threshold to test that \
suspicion and say so in your summary. Do not silently ignore it.
6. Use account_rollup to check whether several boxes are one systemic account problem \
rather than several unrelated ones. That distinction is the most useful thing you can \
tell an operator.
7. Finish with exactly one emit_report call.

Writing rules for emit_report:
- "what_changed": what the data says, concretely — vessel names, ports, hours, days.
- "why_it_matters": the operational consequence, in one sentence. Not a restatement of \
what changed.
- "recommended_action": something an operator can execute today. Name the party to \
contact and what to ask for. Never "monitor the situation".
- Never invent a fact that is not in the tool output. Every claim must trace to a field \
you were shown.
"""

USER_TEMPLATE = """\
Today's snapshot is loaded: {snapshot}.

Produce the daily on-water exception report. Escalate the {top_n} containers that most \
deserve an operator's attention today — fewer if fewer deserve it. Everything you do not \
escalate still ships in the report with rule-generated triage, so escalate on judgement, \
not on coverage.
"""


@dataclass
class AgentOutcome:
    executive_summary: str = ""
    model: str = ""
    turns: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    escalated: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class AgentUnavailable(RuntimeError):
    pass


def _client():
    try:
        import anthropic
    except ImportError as exc:                                   # pragma: no cover
        raise AgentUnavailable(
            "the `anthropic` package is not installed. Either `pip install anthropic` "
            "or run with --no-llm (full report, rule-generated triage)."
        ) from exc
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AgentUnavailable(
            "ANTHROPIC_API_KEY is not set. Either export it or run with --no-llm "
            "(full report, rule-generated triage)."
        )
    return anthropic.Anthropic()


def run_agent(session: ToolSession, model: str = DEFAULT_MODEL,
              max_turns: int = 24, escalate_top_n: int = 25,
              verbose: bool = False, max_tokens: int = 4096) -> AgentOutcome:
    """Let the model orchestrate the detector tools and write the triage."""
    client = _client()
    outcome = AgentOutcome(model=model)

    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": USER_TEMPLATE.format(snapshot=session.path, top_n=escalate_top_n),
    }]

    for turn in range(1, max_turns + 1):
        outcome.turns = turn
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
            messages=messages,
        )
        outcome.input_tokens += getattr(response.usage, "input_tokens", 0) or 0
        outcome.output_tokens += getattr(response.usage, "output_tokens", 0) or 0
        outcome.stop_reason = response.stop_reason or ""

        assistant_content = [block.model_dump() for block in response.content]
        messages.append({"role": "assistant", "content": assistant_content})

        tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if not tool_uses:
            break

        results = []
        for block in tool_uses:
            name, args = block.name, dict(block.input or {})
            if verbose:
                print(f"  [turn {turn}] {name}({json.dumps(args)[:120]})", file=sys.stderr)
            payload = session.dispatch(name, args)
            outcome.tool_calls.append({"turn": turn, "tool": name, "arguments": args})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(payload, default=str)[:120_000],
            })
        messages.append({"role": "user", "content": results})

        if session.report is not None:
            break

    if session.report is None:
        outcome.error = (f"the model stopped after {outcome.turns} turns without calling "
                         f"emit_report; rule-generated triage was used instead")
    else:
        outcome.executive_summary = session.report.get("executive_summary", "")
        outcome.escalated = len(session.report.get("triaged", []))
    return outcome
