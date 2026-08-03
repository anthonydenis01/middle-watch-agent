"""End-to-end tests: generator -> detection -> tools -> report.

The important one is `test_recall_and_false_positives_on_a_generated_file`. It
regenerates a labelled snapshot and re-measures detection quality on every run,
so a threshold change that quietly breaks recall (or opens the noise floor) fails
CI instead of shipping.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from middlewatch.config import load_config          # noqa: E402
from middlewatch.demo import build_demo             # noqa: E402
from middlewatch.engine import analyze              # noqa: E402
from middlewatch.report import to_markdown, to_payload  # noqa: E402
from middlewatch.tools import TOOL_SPECS, ToolSession  # noqa: E402
from middlewatch.triage import annotate_all         # noqa: E402

spec = importlib.util.spec_from_file_location("generate", ROOT / "data" / "generate.py")
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)

sys.path.insert(0, str(ROOT / "scripts"))
from evaluate import evaluate                        # noqa: E402


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("data") / "snapshot.jsonl"
    generate.main(["--rows", "1500", "--seed", "42", "--out", str(out),
                   "--snapshot-date", "2026-08-03"])
    return str(out)


def test_generator_writes_rows_and_ground_truth(snapshot):
    rows = [json.loads(line) for line in open(snapshot)]
    assert len(rows) == 1500
    truth = json.loads(Path(snapshot + ".ground_truth.json").read_text())
    assert truth["rows"] == 1500
    assert truth["containers"], "no exceptions were injected"


def test_recall_and_false_positives_on_a_generated_file(snapshot):
    m = evaluate(snapshot)
    assert m["recall_pct"] == 100.0, f"missed containers: {m['missed_container_ids']}"
    assert m["family_recall_pct"] == 100.0
    assert m["false_positive_pct"] == 0.0, \
        f"false positives: {m['false_positive_container_ids']}"


def test_a_clean_file_produces_no_incidents(tmp_path):
    out = tmp_path / "clean.jsonl"
    generate.main(["--rows", "800", "--seed", "3", "--clean", "--out", str(out),
                   "--snapshot-date", "2026-08-03"])
    result = analyze(str(out), load_config())
    assert result.incidents == [] and result.suppressed == [], \
        "the noise floor is leaking: a file with nothing injected raised findings"


def test_csv_input_produces_the_same_incidents(tmp_path):
    out = tmp_path / "snap.jsonl"
    generate.main(["--rows", "600", "--seed", "11", "--csv", "--out", str(out),
                   "--snapshot-date", "2026-08-03"])
    config = load_config()
    from_jsonl = analyze(str(out), config)
    from_csv = analyze(str(out) + ".csv", config)
    assert {i.container_id for i in from_jsonl.incidents} == \
           {i.container_id for i in from_csv.incidents}


def test_every_tool_answers(snapshot):
    """The tool layer the agent and the MCP server both sit on."""
    session = ToolSession(snapshot, load_config())
    assert "containers_scanned" in session.dispatch("describe_snapshot", {})
    assert len(session.dispatch("list_detectors", {})["detectors"]) == 5

    detected = session.dispatch("run_detector", {"family": "vessel_swap", "limit": 3})
    assert detected["findings"] >= 1
    assert detected["top_findings"][0]["evidence"]

    ranked = session.dispatch("rank_incidents", {"limit": 5})
    assert ranked["incidents"]
    cid = ranked["incidents"][0]["container_id"]

    detail = session.dispatch("get_container", {"container_id": cid})
    assert detail["findings"] and detail["port_events"]

    assert session.dispatch("account_rollup", {"limit": 3})["accounts"]
    assert len(session.dispatch("detector_performance", {})["per_family"]) == 5

    sim = session.dispatch("simulate_threshold",
                           {"path": "eta_drift.min_drift_hours", "value": 240})
    assert sim["containers_flagged_if_changed"] <= sim["containers_flagged_now"]

    assert session.dispatch("emit_report", {
        "executive_summary": "test", "triaged": [
            {"container_id": cid, "why_it_matters": "because",
             "recommended_action": "call the account"}]})["accepted"]

    incidents = session.full().incidents
    annotate_all(incidents)
    assert session.apply_report(incidents) == "test"
    assert next(i for i in incidents if i.container_id == cid).triage_source == "claude"


def test_unknown_tool_and_bad_arguments_do_not_raise(snapshot):
    session = ToolSession(snapshot, load_config())
    assert "error" in session.dispatch("no_such_tool", {})
    assert "error" in session.dispatch("run_detector", {"family": "not_a_family"})
    assert "error" in session.dispatch("get_container", {"container_id": "NOPE0000000"})


def test_tool_specs_are_well_formed():
    for spec_ in TOOL_SPECS:
        assert spec_["name"] and spec_["description"]
        assert spec_["input_schema"]["type"] == "object"
        assert hasattr(ToolSession, spec_["name"]), f"{spec_['name']} has no implementation"


def test_report_outputs_render(snapshot, tmp_path):
    config = load_config()
    result = analyze(snapshot, config)
    annotate_all(result.incidents)
    payload = to_payload(result, "summary", None, max_incidents=20)
    assert payload["incidents"] and payload["summary"]["containers_scanned"] == 1500
    assert "Middle Watch" in to_markdown(result, "summary", limit=5)

    out = build_demo(payload, tmp_path / "demo.html",
                     evaluation={"recall_pct": 100.0, "false_positive_pct": 0.0})
    html = out.read_text()
    assert "__PAYLOAD__" not in html and "report-data" in html
    assert result.incidents[0].container_id in html


def test_cli_runs_end_to_end(snapshot, tmp_path):
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, "-m", "middlewatch", "run", "--snapshot", snapshot,
         "--no-llm", "--quiet", "--json", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(out.read_text())
    assert payload["incidents"][0]["recommended_action"]
    assert payload["agent"]["mode"] == "rules"
