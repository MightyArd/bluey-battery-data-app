# Checkpoint: P5 fetch-and-publish (v0.2.0)

Read `CLAUDE.md` first. This file is the contract for this increment. Stop and
report at the end. Do not start the simulation or archive increments.

## Objective

Turn the scaffold into a working P5 ingestion loop: every 5 minutes, fetch the
AEMO P5 predispatch, extract two values, and publish them to MQTT so Home
Assistant auto-creates the entities.

## In scope

- `app/p5.py`: fetch and parse.
- `app/publisher.py`: MQTT discovery and state publish.
- `app/main.py`: replace the 60-second heartbeat with a 5-minute loop.
- `app/settings.py`: load add-on options.
- `tests/test_p5_parser.py`: a deterministic parser test against a saved fixture.
- Bump version to 0.2.0; update `DOCS.md` and `CHANGELOG.md`.

## Out of scope

The simulation and the daily archive. Do not build them. Do not read or write
InfluxDB in this increment.

## Requirements

P5 fetch (`p5.py`):

- Source is AEMO NEMWeb Current reports. VERIFY the exact folder under
  `https://nemweb.com.au/Reports/Current/` (expected pattern is a P5-minute
  reports folder) and the current file naming before coding. Do not hardcode a
  path from memory; AEMO has changed conventions before. Download a real sample
  to confirm the structure.
- The file is a zipped, nested AEMO CSV: rows tagged `C` (comment), `I` (header)
  and `D` (data), with multiple tables. Parse the REGIONSOLUTION table: find its
  `I` header row, then read its `D` rows.
- For `REGIONID == "VIC1"`, take the first forward interval, where
  `INTERVAL_DATETIME` equals `RUN_DATETIME` plus 5 minutes. Its `RRP` is the
  5-minute-ahead price. `RUN_DATETIME` is the packet id.
- The parser must be a pure function: text or bytes in, `(rrp: float,
  run_datetime: str)` out. Unit-test it against a saved fixture. Commit a trimmed
  real sample under `tests/fixtures/`.
- Robustness: retries with a timeout; handle the case where the latest run has
  not published yet; handle malformed or partial files without crashing the loop.
- Dedupe: skip if `RUN_DATETIME` equals the last processed run. Persist the last
  run id in `/data`.

Publish (`publisher.py`):

- Use MQTT discovery so HA auto-creates the entities. Primary entity:
  `sensor.p5_price_forecast`, numeric, unit `$/MWh`. It is a price, so do not set
  an energy device_class; use `state_class: measurement`. Give it a stable
  `unique_id` and group it under a device block so the entities cluster in HA.
- Carry the run id either as an attribute on that sensor or as a companion
  `sensor.p5_run_id`. Your call, but document which you chose.
- Publish the discovery config retained; publish state each cycle.

Loop (`main.py`):

- A 5-minute cycle aligned just after AEMO publishes: trigger when the minute is
  a multiple of 5, plus a small offset (for example 60 seconds) to let the file
  land. Keep a lightweight status log line each cycle. On a fetch failure, log
  and continue. Never let the loop crash.

## Constraints

- No secrets committed. No InfluxDB. Shadow-only, no actuation. Australian
  English, no em dashes in any text. Follow `CLAUDE.md`.

## Acceptance criteria

- pytest green, including the parser test against the fixture.
- Run locally: the loop fetches a live P5 file and logs the extracted `(rrp,
  run_datetime)`; dedupe demonstrably skips an unchanged run.
- After deploy on Bluey: `sensor.p5_price_forecast` appears via discovery and
  updates roughly every 5 minutes; the run id is present.

## Stop and report (do not continue past this)

Report:

1. Summary of what was built.
2. Files added or changed.
3. Decisions and assumptions made (for example the confirmed NEMWeb folder, and
   the run-id-as-attribute versus companion-sensor choice). Log them.
4. How it was verified (tests plus live fetch output).
5. Open questions.
6. Risks and limitations.
7. Recommended next step.

Note for the user, not a change in this repo: once this is running, add
`sensor.p5_*` to the InfluxDB include globs in the `home-assistant-config` repo
so the values are logged. Do not edit that repo from here.
