"""The agentic loop, exercised against a stub Claude client.

No API key, no network — the point is to prove the loop itself is correct: that
it dispatches tool_use blocks to the tool layer, feeds tool_result blocks back in
the right shape, stops when emit_report lands, merges the model's triage onto the
right incidents, and degrades cleanly when the model never calls emit_report.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from middlewatch import agent as agent_mod          # noqa: E402
from middlewatch.config import load_config          # noqa: E402
from middlewatch.tools import ToolSession           # noqa: E402
from middlewatch.triage import annotate_all         # noqa: E402

spec = importlib.util.spec_from_file_location("generate", ROOT / "data" / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


# --------------------------------------------------------------------------- #
# Stub client
# --------------------------------------------------------------------------- #

class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self):
        return dict(self.__dict__)


class Usage:
    input_tokens = 1000
    output_tokens = 200


class Response:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = Usage()


class StubMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


class StubClient:
    def __init__(self, script):
        self.messages = StubMessages(script)


def tool_use(name, **inp):
    return Block(type="tool_use", id=f"tu_{name}", name=name, input=inp)


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("agent") / "snapshot.jsonl"
    generate.main(["--rows", "500", "--seed", "5", "--out", str(out),
                   "--snapshot-date", "2026-08-03"])
    return str(out)


def test_loop_orchestrates_tools_and_applies_the_models_triage(snapshot, monkeypatch):
    session = ToolSession(snapshot, load_config())
    target = session.full().incidents[0].container_id

    script = [
        Response([tool_use("describe_snapshot"), tool_use("list_detectors")]),
        Response([tool_use("run_detector", family="vessel_swap", limit=3)]),
        Response([tool_use("get_container", container_id=target)]),
        Response([tool_use("emit_report",
                           executive_summary="Twelve containers need a human today.",
                           triaged=[{"container_id": target,
                                     "what_changed": "Vessel swapped after booking.",
                                     "why_it_matters": "Arrival slips past the free-time window.",
                                     "recommended_action": "Call the account and rebook the "
                                                           "delivery appointment."}])],
                 stop_reason="tool_use"),
    ]
    monkeypatch.setattr(agent_mod, "_client", lambda: StubClient(script))

    outcome = agent_mod.run_agent(session, model="stub-model", max_turns=10)

    assert outcome.ok and outcome.turns == 4
    assert outcome.escalated == 1
    assert outcome.input_tokens == 4000 and outcome.output_tokens == 800
    assert [c["tool"] for c in outcome.tool_calls] == [
        "describe_snapshot", "list_detectors", "run_detector", "get_container", "emit_report"]

    incidents = session.full().incidents
    annotate_all(incidents)
    assert session.apply_report(incidents) == "Twelve containers need a human today."
    escalated = next(i for i in incidents if i.container_id == target)
    assert escalated.triage_source == "claude"
    assert escalated.recommended_action.startswith("Call the account")
    # everything the model did not touch still ships with rule-generated triage
    assert all(i.why_it_matters for i in incidents)


def test_tool_results_are_fed_back_in_the_shape_the_api_expects(snapshot, monkeypatch):
    session = ToolSession(snapshot, load_config())
    script = [Response([tool_use("describe_snapshot")]),
              Response([tool_use("emit_report", executive_summary="done")])]
    stub = StubClient(script)
    monkeypatch.setattr(agent_mod, "_client", lambda: stub)
    agent_mod.run_agent(session, max_turns=5)

    second_call_messages = stub.messages.calls[1]["messages"]
    assert second_call_messages[1]["role"] == "assistant"
    result_turn = second_call_messages[2]
    assert result_turn["role"] == "user"
    block = result_turn["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tu_describe_snapshot"
    assert "containers_scanned" in block["content"]


def test_a_model_that_never_reports_degrades_to_rule_triage(snapshot, monkeypatch):
    session = ToolSession(snapshot, load_config())
    script = [Response([Block(type="text", text="I am done thinking.")], stop_reason="end_turn")]
    monkeypatch.setattr(agent_mod, "_client", lambda: StubClient(script))

    outcome = agent_mod.run_agent(session, max_turns=3)
    assert not outcome.ok and "emit_report" in outcome.error
    incidents = session.full().incidents
    annotate_all(incidents)
    assert all(i.recommended_action for i in incidents)


def test_missing_api_key_is_a_clear_message_not_a_traceback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(agent_mod.AgentUnavailable) as exc:
        agent_mod._client()
    assert "--no-llm" in str(exc.value)
