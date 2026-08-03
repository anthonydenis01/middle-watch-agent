# Snapshot schema

One **daily snapshot** = one line per container currently in the on-water pipeline.
Format: JSONL (default) or a flattened CSV export (`--csv`, nested objects become
JSON strings). All timestamps are ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`).

All data produced by `data/generate.py` is **fictional** — container numbers,
vessel names, voyage numbers, account names, service loops and transit benchmarks
are generated from word lists in the script. Port codes are public UN/LOCODEs.

---

## Record

| Field | Type | Meaning |
|---|---|---|
| `snapshot_date` | `YYYY-MM-DD` | The day this file represents |
| `snapshot_time` | timestamp | The moment the snapshot was cut — every "how long has it been sitting" clock is measured from here |
| `container_id` | string | ISO 6346 number (4-letter owner code + 6 digits + check digit) |
| `container_type` | string | `40HC`, `40GP`, `20GP`, `45HC`, `40RF` |
| `booking_id` | string | Booking reference |
| `bill_of_lading` | string | B/L reference |
| `account_id` | string | Customer account key |
| `account_name` | string | Customer account name |
| `account_tier` | enum | `strategic` \| `key` \| `standard` — drives severity weighting |
| `service_contract` | string | Contract reference the booking sits under |
| `commodity` | string | Cargo description |
| `cargo_value_usd` | int | Declared value |
| `status` | enum | `AT_ORIGIN_TERMINAL` \| `ON_WATER` \| `AT_TRANSSHIPMENT` \| `AT_DESTINATION_TERMINAL` |
| `booked` | object | **What was promised** — see below |
| `current` | object | **What is actually happening now** — see below |
| `previous_snapshot_eta` | timestamp | The ETA this container carried in yesterday's file |
| `eta_history` | array | Last 4 daily observations: `{as_of, eta}` |
| `port_events` | array | Chronological events: `{port, event, timestamp}` |
| `routing_guide` | object | Contractual lane benchmark — see below |
| `last_free_day` | timestamp | End of free time at destination (demurrage clock) |

The whole detection model is the gap between `booked` and `current`, read against
`routing_guide` and `port_events`.

### `booked` / `current`

| Field | In | Meaning |
|---|---|---|
| `origin_port` | both | UN/LOCODE |
| `destination_port` | both | UN/LOCODE — a difference between the two is a **destination change** |
| `vessel_name` | both | Fictional vessel name |
| `vessel_imo` | both | Vessel identifier |
| `voyage` | both | Voyage number, e.g. `018E` |
| `service_loop` | both | Service string, e.g. `TPX-5` |
| `etd` | both | Departure from origin |
| `eta` | both | Arrival at final destination |
| `transit_days` | `booked` only | Transit promised at booking |
| `routing` | both | Ordered legs — see below |

### Routing leg

```json
{
  "seq": 1,
  "from_port": "CNSHA",
  "to_port": "PACTB",
  "mode": "VESSEL",
  "vessel_name": "MV NORTHERN VOYAGER",
  "voyage": "018E",
  "service_loop": "TPX-5",
  "etd": "2026-07-11T04:00:00Z",
  "eta": "2026-07-29T11:00:00Z"
}
```

A booking is either **direct** (1 leg) or **transshipped** (2 legs via a hub).
Comparing the leg sequence of `booked.routing` and `current.routing` is what
produces a routing-change finding.

### Port events

`event` is one of:

| Event | Meaning | Used by |
|---|---|---|
| `GATE_IN` | Box received at the origin terminal | origin dwell |
| `LOADED` | Loaded onto a vessel | closes an origin/transshipment dwell |
| `VESSEL_DEPARTED` | Vessel sailed | actual departure, transit-time base |
| `VESSEL_ARRIVED` | Vessel berthed | — |
| `DISCHARGED` | Box discharged | starts a transshipment/destination dwell |
| `GATE_OUT` | Box picked up by the consignee | closes a destination dwell |

A dwell is an **open** interval: a `DISCHARGED` (or `GATE_IN`) with no matching
`LOADED` (or `GATE_OUT`) after it. Its length is measured to `snapshot_time`.

### `routing_guide`

```json
{
  "lane": "CNSHA-USMIA",
  "benchmark_transit_days": 34.0,
  "tolerance_days": 2.0,
  "standard_transshipment": ["PACTB"]
}
```

The contractual reference for the lane. `tolerance_days` is the lane's own
allowance; the detector adds the configured `transit_time.tolerance_days` on top
before it flags anything.

---

## Ground truth

`<snapshot>.ground_truth.json` records what the generator deliberately broke:

```json
{
  "snapshot_date": "2026-08-03",
  "seed": 7,
  "rows": 40000,
  "containers_with_injected_exceptions": 2312,
  "injected_counts": { "routing_change": 480, "...": 0 },
  "containers": { "MWSU1234565": ["vessel_swap", "eta_drift"] }
}
```

`scripts/evaluate.py` reads it and reports recall and false-positive rate. It is
**not** read by the agent — nothing in the detection path ever sees it.

### How the file stays honest

The generator injects two things, not one:

1. **Exceptions** — deliberately and comfortably past the configured thresholds.
2. **Benign near-misses** — the noise a real file is full of, deliberately kept
   *under* the thresholds: ETA jitter of ±18 h, voyage renumbering on the same
   vessel, transshipment swapped for an equivalent hub in the same group, dwell
   that is long but legal. These are **not** in the ground truth and any finding
   raised on them counts as a false positive.

Without the second category a detector could flag every row and score 100 %
recall. That is the whole point of measuring both numbers together.
