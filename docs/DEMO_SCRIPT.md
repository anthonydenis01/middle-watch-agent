# Middle Watch — 10-minute spoken demo

Before starting, run the API and web app, open the landing page at desktop width,
and keep a second 375-pixel browser view available. Use only the built-in sample and
the documented ISO test vector. Optional service keys are unnecessary. The timed
blocks include clicks and inspection pauses; rehearse to the ten-minute limit.

## 0:00–1:00 — Purpose and limits

Say: “Middle Watch is an open-source exception-monitoring app I built. It turns a
list of container numbers into a ranked queue of things worth reviewing, with the
evidence beside every finding. Once data is connected, tracking is easy to automate;
knowing what matters is the hard part.”

Point to the persistent banner. “This is a simulated feed. Journeys are generated;
no carrier is contacted. This demonstrates the workflow and detection logic, not
live shipment tracking.” Pause so the viewer can read the banner and proof card.

## 1:00–2:00 — Proof before the walkthrough

Point to the controlled synthetic benchmark: “The fixed generated dataset has
40,000 rows. The unchanged evaluation catches 2,393 of 2,393 injected exceptions,
with 100% family recall and zero false positives among the 2,393 reported incidents.
Those numbers apply to this controlled synthetic benchmark. They are not an estimate
of accuracy on real operations.”

“The benchmark deliberately includes benign near-misses. Seed and date are fixed,
and we compare the HTTP path to the original engine. The generator and detector
share assumptions, so independent validation is still a separate piece of work.”

## 2:00–3:00 — One-click workflow

Click **Load sample list**. Wait for the 25 rows. If a hosted API is waking, explain
the delay once and retry when the UI suggests it; never imply a failed request worked.

“Each valid number gets a repeatable generated journey. The existing rules run,
the findings are stored, and the table puts the strongest signals first. We can
see status, next milestone, ETA and exception families without opening every row.”

Let the viewer read several rows. Change the severity filter, then reset it.

## 3:00–4:30 — Inspect the evidence

Open a flagged row. Read its actual number and finding title from the screen.
“Here is what changed, why it matters, and the suggested next action. These
explanations work without a model key. The draft update remains subject to review.”

Explain the actual displayed fields: “This value is what the journey reports;
this is the booked or expected value; this is the threshold. The rule reference
identifies which detector family fired.”

Scroll to the timeline. “The events support the diagnosis. The tool gives a reviewer
an audit trail instead of asking them to trust a label.” Pause for a question or let
the viewer choose another finding to inspect.

## 4:30–5:30 — Useful silence

Close the detail. Select a clear row or filter for a different family.
“The goal is not to alert on every difference. A voyage number can change while the
hull stays the same. A hub can move within an equivalent group without a transit
penalty. Dwell can stay within a weekend allowance. The thresholds and existing
tests preserve those distinctions.”

Reset the filters. “Multiple signals on the same container remain visible together,
so we can reason about one operational event with several contributing findings.”

## 5:30–6:30 — Input quality and limits

Paste `CSQU3054383` and `CSQU3054384` into a new run.
“These use the documented ISO example and a one-digit mutation. One passes; the
other stays visible with a check-digit reason and never reaches the provider.”

Point to CSV upload. “The same workflow accepts one UTF-8 column named
container_number. A run is capped at 100 inputs and the file at 200 KB. Normalized
duplicates collapse into one row. Errors give a next step instead of an empty screen.”

## 6:30–7:30 — Architecture

Open the method section. “React and TypeScript render the review workflow. FastAPI
validates requests. A provider interface supplies deterministic synthetic journeys.
A thin adapter runs the original detectors; SQLAlchemy stores watchlists, events
and findings. SQLite makes this runnable with no accounts, and the hosted
configuration uses Postgres.”

“Detection is deterministic. Optional model explanations change narrative only,
never evidence or severity, and failures fall back to templates. Optional email is
an operator command, not a public send button.”

## 7:30–8:30 — Reliability and accessibility

Show the phone view and inspect a flagged row. Tab through controls, then press
Escape to close the detail.

“The simulation notice and Close control stay visible while evidence scrolls.
Keyboard access, mobile overflow and automated accessibility checks are part of the
browser suite. Run limits and bounded request bodies protect the API. Watchlists
expire after a day; reads reject expired records and a scheduled task deletes them.
A sleeping host completes physical cleanup when it wakes.”

## 8:30–9:30 — Reproducibility

Show the repository's latest Actions result, accurately naming its state.
“The checks run the original tests, API tests, migrations, the frozen benchmark,
the HTTP equivalence check, and the web build and browser workflow. The detector
logic and original eval harness have not been rewritten.”

Open the committed benchmark definitions. “The controlled synthetic benchmark has
151 repeated rows, and the report explains the counting convention. Runtime is
machine-dependent. I keep the limitations next to the evidence.”

## 9:30–10:00 — Close

Return to the sample watchlist. “The result is a working, inspectable review loop:
validate, simulate, detect, rank, explain, and inspect. The next validation step
would be independent data and reviewed operational outcomes. This version stays
explicitly synthetic. The code, rules, checks and evidence are open for review.”

End at ten minutes and invite questions about one rule or implementation decision.
