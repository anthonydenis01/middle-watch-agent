# Middle Watch — on-water exception monitoring agent

**Reads a daily container-status file, finds the five things that go wrong on the water, and hands an operator a ranked queue with the evidence attached.**

40,000 containers scanned in **2.3 seconds**. 100 % of injected exceptions caught, 0 % false positives on the synthetic benchmark. Every finding cites the exact fields that triggered it.

**[▶ Live demo dashboard](https://anthonydenis01.github.io/middle-watch-agent/demo.html)** · designed for ocean freight operations · Python 3.11+ · MIT

---

## Why this exists

On an import desk, exceptions on the water are found by whoever happens to open the booking — which is usually after the customer has already called. The information is all there: the booking says one vessel, the snapshot says another; the routing guide promises 34 days, the lane is running 41. Nobody has time to read 40,000 rows looking for it.

I built and proved a structured review method for exactly this problem in ocean freight operations at scale — daily exception review across a large on-water portfolio, in minutes instead of never. But a method executed by a human is not software. **This repository is that logic rebuilt from scratch as an agent that actually runs**: clean-room, synthetic data, no employer inputs of any kind.

The design bet is a specific one: **detection must be deterministic and auditable; judgement is where a model earns its place.** Five hand-written detectors decide what counts as an exception and prove it with field-level evidence. Claude orchestrates those detectors as tools, verifies the containers it intends to escalate, and writes the triage an operator reads. Pull the model out and the report still ships — with rule-generated triage, the same evidence, and the same ranking.

---

## Quick start

```bash
git clone https://github.com/anthonydenis01/middle-watch-agent.git
cd middle-watch-agent

# 1. generate a synthetic daily snapshot (40k containers, exceptions injected)
python data/generate.py --rows 40000 --seed 7 --out data/out/snapshot.jsonl

# 2. run the morning report — no API key needed
python -m middlewatch run --snapshot data/out/snapshot.jsonl --no-llm

# 3. measure detection quality against the generator's ground truth
python scripts/evaluate.py --snapshot data/out/snapshot.jsonl
```

No dependencies for any of that — the detection engine, the CLI, the report and the dashboard builder are Python 3.11 standard library only.

To run the **agentic loop** (Claude orchestrating the detectors as tools):

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python -m middlewatch run --snapshot data/out/snapshot.jsonl --verbose
```

Without a key, `--no-llm` is used automatically and the run still completes.

Rebuild the dashboard:

```bash
python scripts/evaluate.py --snapshot data/out/snapshot.jsonl --json data/out/eval.json
python -m middlewatch run --snapshot data/out/snapshot.jsonl --no-llm --quiet \
    --json data/out/report.json --demo demo.html --eval-metrics data/out/eval.json
```

---

## What it does

```
daily snapshot (JSONL/CSV)
        │
        ├─ 5 detectors ─────────► findings + field-level evidence
        │                          (deterministic, config-driven, no model)
        ├─ grouping ────────────► one container = one incident
        ├─ severity scoring ────► ranked queue, noise floor applied
        │
        └─ agentic loop ────────► Claude drives the detectors as tools,
                                  verifies what it escalates, writes the triage
                                  │
                                  └─► console · JSON · Markdown · demo.html
```

1. **Detect** the five exception families across every container.
2. **Score and filter** — severity 0-100, with a configurable noise floor. False-positive control is a feature: every threshold lives in `config/thresholds.toml`, nothing is hardcoded.
3. **Rank** — one line per exception: container, account, what changed, why it matters, what to do.
4. **Cite** — every flagged exception references the exact fields that triggered it.
5. **Run on command** — CLI, one process, well under the ten-minute budget for a full 40k file.

---

## The 5 exception families

| Family | Fires when | Deliberately stays quiet when |
|---|---|---|
| **Routing change** | Discharge port changed, a transshipment leg added or removed, or the hub moved to a non-equivalent port | The hub was swapped for another hub in the same equivalence group at no transit cost — network management, not an exception |
| **Vessel swap** | The container is on a different hull and the swap moves the ETA past the threshold, or the service loop changed | Same vessel with a renumbered voyage; a paper swap that leaves the schedule untouched |
| **Dwell** | An open `DISCHARGED`/`GATE_IN` with no onward `LOADED`/`GATE_OUT`, past the limit for that location | Inside the limit plus grace, or inside the weekend allowance — the biggest source of Monday-morning false alarms |
| **ETA drift** | The ETA moved past the threshold against booking, **or** moved sharply since yesterday's snapshot | Sub-threshold jitter on either clock |
| **Transit time** | Projected transit exceeds routing-guide benchmark + lane tolerance + configured tolerance. Also flags lanes far *faster* than the guide — a stale benchmark prices the next contract wrong | Inside the lane's own tolerance |

**One container, one incident.** A vessel swap that pushes the ETA that breaks the transit benchmark is one operational event, not three alerts. The detectors all still run and all still attach their evidence; grouping picks the root cause (`grouping.primary_order`) and files the rest as contributing signals.

---

## Output

Console (default), plus `--json`, `--md`, and `--demo` for the dashboard.

```
!!  1. [100] MWGU4863925  Granite Peak Electronics (key)  VNSGN-BEANR  AT_DESTINATION_TERMINAL
      signals : ETA drift, Routing change, Transit-time discrepancy   (root: Routing change)
      changed : ETA moved 138h later vs. booking
      changed : Transshipment moved SGSIN → DEHAM (+5.8d transit)
      changed : Lane VNSGN-BEANR running +6.5d vs benchmark (38.5d actual vs 32.0d guide)
      why     : The cargo is no longer following the booked routing and the change adds +5.8
                days of transit, and it arrives in 3.8 days, so there is almost no room left
                to recover, with the projected arrival already past the last free day, on a
                key account — ETA drift and Transit-time discrepancy also fired on this
                container, which is consistent with one root cause rather than 3 separate
                problems.
      action  : Check the onward connection at the new hub and tell the account before they
                see it on their own tracking.
      eta     : booked 2026-08-01T06:19:10Z  ->  now 2026-08-07T00:37:10Z  (3.8d out)
      evidence:
                - booked.routing[].port_sequence='VNSGN > SGSIN > BEANR' — routing as booked
                - current.routing[].port_sequence='VNSGN > DEHAM > BEANR'  booked/expected=…
                - current.eta - current.etd='38.5 d'  booked/expected='32.7 d'  threshold='+1.0 d'
                - computed.projected_transit_days='38.5 d'  expected='32.0 d'  threshold='37.5 d'
```

Every line under `evidence:` is a field path, the observed value, what it was compared to and the threshold that was crossed. If a finding cannot produce that, it does not ship.

---

## Detection quality

Measured on every run by `scripts/evaluate.py` against the generator's ground truth, which the detection path never sees:

| Metric | Result (40,000 rows, seed 7) |
|---|---|
| Detection recall | **100 %** — 2,393 / 2,393 labelled containers |
| Family recall (caught for the *right reason*) | **100 %** |
| False-positive rate | **0 %** — 0 of 2,393 reported incidents on clean containers |
| Runtime | **2.3 s** end to end |

Definitions, because a recall number without them is marketing:

- A container is **dirty** if the generator injected at least one exception, **clean** otherwise.
- **False positive** = a reported incident on a *clean* container. Extra families firing on a *dirty* container are not counted: a reroute that adds six days genuinely does move the ETA, and reporting that is correct.
- The file is deliberately full of **benign near-misses** kept just under the thresholds — ETA jitter, voyage renumbering, equivalent-hub swaps, long-but-legal dwell. They are all clean containers, so anything raised on them lands in the false-positive count. Without them a detector could flag every row and score 100 % recall.

Re-measure at any time, or tighten a threshold and watch what happens:

```bash
python scripts/evaluate.py --snapshot data/out/snapshot.jsonl
python -m middlewatch run --snapshot data/out/snapshot.jsonl --no-llm --quiet --json out.json
```

---

## The agentic loop

`middlewatch/agent.py` is a real Claude tool-calling loop, not one large prompt. The model is never handed 40,000 rows. It gets nine tools:

| Tool | What the model uses it for |
|---|---|
| `describe_snapshot` | Shape of the file, findings per family, thresholds in effect |
| `list_detectors` | What each detector flags and what it suppresses |
| `run_detector` | Run one detector across the file; counts, magnitudes, sampled evidence |
| `rank_incidents` | The grouped, severity-ranked queue |
| `get_container` | Everything on one container — verify before escalating |
| `account_rollup` | Is this one systemic account problem or several unrelated boxes? |
| `detector_performance` | Which detector is carrying the queue, and which is producing noise |
| `simulate_threshold` | "What would the queue look like at 36 hours instead of 24?" — simulation only, config on disk is never touched |
| `emit_report` | Deliver the executive summary and the triage for escalated containers |

The model decides what to investigate, verifies its escalations against the raw container record, and writes the operator-facing wording. It cannot invent a finding: the evidence comes from the detectors either way. Containers it does not escalate still ship with rule-generated triage.

`--verbose` prints every tool call as it happens.

## MCP server

The same tools, over the Model Context Protocol, for any MCP client:

```bash
pip install mcp
MIDDLEWATCH_SNAPSHOT=data/out/snapshot.jsonl python -m middlewatch.mcp_server
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "middle-watch": {
      "command": "python",
      "args": ["-m", "middlewatch.mcp_server"],
      "cwd": "/absolute/path/to/middle-watch-agent",
      "env": {
        "MIDDLEWATCH_SNAPSHOT": "data/out/snapshot.jsonl",
        "MIDDLEWATCH_CONFIG": "config/thresholds.toml"
      }
    }
  }
}
```

One tool definition (`middlewatch/tools.py`), three consumers: the Claude API loop, the MCP server, and the CLI.

---

## Tuning

Everything that decides "exception or noise" is in [`config/thresholds.toml`](config/thresholds.toml). Nothing is hardcoded in the detectors.

```toml
[eta_drift]
min_drift_hours = 24         # vs. the ETA quoted at booking
min_daily_drift_hours = 12   # vs. yesterday's snapshot

[dwell]
transshipment_max_hours = 120
grace_hours = 12
non_working_day_allowance_hours = 24   # kills the Monday-morning false alarms

[general]
min_severity_to_report = 40  # below this: counted, kept in the JSON, out of the queue
```

Ask what a change would do before you make it:

```bash
python -m middlewatch run --snapshot data/out/snapshot.jsonl --no-llm --quiet
# or let the agent test it: it has simulate_threshold and is told to use it
```

---

## Tech

| | |
|---|---|
| Core engine, CLI, report, dashboard | Python 3.11+, **standard library only** (`tomllib`, `dataclasses`, `csv`, `json`) |
| Agentic loop | `anthropic` — real tool-calling, 9 tools, `--no-llm` fallback |
| MCP server | `mcp` — stdio, same tool definitions |
| Dashboard | One self-contained HTML file. No build step, no CDN, no network at runtime |
| Tests | `pytest` — 32 tests, including recall/false-positive regression on a regenerated file and the full agentic loop against a stub client |

```
middle-watch-agent/
├── config/thresholds.toml       every threshold, one file
├── data/generate.py             synthetic generator (seedable, injection flags)
├── data/SCHEMA.md               documented schema + ground-truth definitions
├── middlewatch/
│   ├── detectors/               the five detectors, one file each, pure functions
│   ├── engine.py                snapshot in, ranked incidents out
│   ├── severity.py              scoring + grouping
│   ├── triage.py                deterministic narrative (the --no-llm path)
│   ├── tools.py                 tool layer: agent + MCP + CLI
│   ├── agent.py                 the Claude tool-calling loop
│   ├── mcp_server.py            stdio MCP server
│   ├── report.py                console / JSON / Markdown
│   └── demo.py + demo_template.html
├── scripts/evaluate.py          recall / false-positive measurement
├── tests/                       32 tests
└── demo.html                    the built dashboard (GitHub Pages)
```

```bash
pip install -e ".[dev]" && pytest -q
```

---

## Data schema

Full documentation in [`data/SCHEMA.md`](data/SCHEMA.md). One record per container per day:

```json
{
  "snapshot_time": "2026-08-03T06:00:00Z",
  "container_id": "MWSU1234565",
  "account_id": "ACC-0001", "account_name": "…", "account_tier": "strategic",
  "status": "AT_TRANSSHIPMENT",
  "booked":  { "destination_port": "USMIA", "vessel_name": "…", "voyage": "018E",
               "etd": "…", "eta": "…", "transit_days": 34.0, "routing": [ … ] },
  "current": { "destination_port": "USMIA", "vessel_name": "…", "voyage": "018E",
               "etd": "…", "eta": "…", "routing": [ … ] },
  "previous_snapshot_eta": "…",
  "eta_history": [ { "as_of": "…", "eta": "…" } ],
  "port_events": [ { "port": "PACTB", "event": "DISCHARGED", "timestamp": "…" } ],
  "routing_guide": { "lane": "CNSHA-USMIA", "benchmark_transit_days": 34.0,
                     "tolerance_days": 2.0, "standard_transshipment": ["PACTB"] },
  "last_free_day": "…"
}
```

The whole detection model is the gap between `booked` and `current`, read against `routing_guide` and `port_events`. CSV input is supported (`--csv` on the generator); nested objects become JSON strings in their columns.

To point this at real operational data, write an adapter that emits this schema. Nothing downstream changes.

---

## About the data

Every row in this repository comes from `data/generate.py`. Container numbers, vessel names, voyage numbers, account names, service loops and transit benchmarks are generated from word lists in that script; port codes are public UN/LOCODEs. **No carrier, customer or operational data of any kind is used, referenced or reproduced anywhere in this repository.** The business logic — "check whether the vessel changed since booking" — belongs to no one; the implementation here is written from scratch.

---

## License

MIT — see [LICENSE](LICENSE).
