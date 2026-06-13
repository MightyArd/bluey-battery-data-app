# Checkpoint: Force-backup button (v0.5.0)

Read `CLAUDE.md` first. This file is the contract for this increment. Stop and
report at the end.

## Objective

Add an on-demand "force backup" control: a momentary MQTT button entity that
triggers the same daily archive run (rollup, push to NAS and B2, verification,
health timestamps) the timer already performs. The button is stateless, so it
resets itself; no config flag, no self-restart, no self-modifying options.

## In scope

- `app/publisher.py`: add MQTT discovery for a button entity under the existing
  `bluey_data_platform` device.
- `app/main.py`: subscribe to the button's command topic and route a press to
  the existing `run_archive`, executed from the main loop (see concurrency below).
- `tests/`: unit tests for the press-to-run routing and the bookkeeping rules.
- Bump the minor version to 0.5.0; update `DOCS.md` and `CHANGELOG.md`.

## Out of scope

- Any change to the daily timer's behaviour or its bookkeeping logic.
- Any new archive logic. Reuse `run_archive(client, settings)` as-is.
- The "press automatically when the NAS comes online" automation. That belongs in
  Home Assistant as an automation in the config repo, not in this add-on.
- The `nas_share` / `nas_path` options. Those are user config, not code.

## The button

- Publish via MQTT discovery as a `button` component under the existing device,
  so it appears as `button.bluey_data_platform_run_archive` (friendly name along
  the lines of "Force backup"). Retained discovery config, same mechanism and
  device block as the existing entities.
- Subscribe to its command topic. On receiving the press payload, trigger one
  archive run.

## Concurrency (important)

- Do NOT call `run_archive` inside the MQTT message callback. `run_archive` can
  take seconds to a minute (query, rollup, two pushes), and the callback runs on
  paho's network-loop thread; blocking it risks delayed keepalives and an MQTT
  disconnect, and would stall the heartbeat.
- Instead, the callback sets a thread-safe request flag (for example a
  `threading.Event` or a flag under a lock). The main loop checks the flag each
  iteration, clears it, and runs `run_archive` in the main thread, the same place
  and same code path the daily timer uses.
- This serialises manual and scheduled runs naturally (the single-threaded main
  loop runs one per iteration), so a press and the 03:00 timer cannot overlap or
  double-run.
- A manual press is purely additive: it must NOT update the daily-run bookkeeping
  (`last_archive_date`), so it neither suppresses nor is suppressed by the
  scheduled run.

## Behaviour on press

- Runs exactly what the timer runs: rollup of the previous full local day, push
  to both configured destinations, checksum verification, and the
  `backup_nas_last_success` / `backup_cloud_last_success` timestamp updates.
- A press while the NAS is off (or `nas_share` unset) behaves like any run: it
  completes the B2 leg and cleanly skips or fails the NAS leg, without crashing.
  No special-casing.
- Log clearly when a press is received and when the manual run starts and
  finishes, distinct from the scheduled run's log lines.

## Constraints

Reuse the existing `run_archive`; do not duplicate archive logic. The button is
stateless and momentary. Archive execution stays in the main loop, never in the
MQTT callback thread. No secrets. Australian English, no em dashes. Follow
`CLAUDE.md`.

## Acceptance criteria

- pytest green. Cover at least: a press payload routes to `run_archive` via the
  main-loop flag, not directly from the callback thread; a press does not alter
  `last_archive_date`; a press coinciding with the scheduled run does not produce
  two concurrent runs.
- On Bluey: the button appears in HA grouped under the Bluey Data Platform device.
  Pressing it runs the archive (visible in the log), pushes to the configured
  destinations, and updates the backup health timestamps.
- A press while the NAS is off completes the B2 leg and skips the NAS leg cleanly.
- The 5-minute P5 loop and the heartbeat keep ticking during and after a
  button-triggered archive run; no MQTT disconnect from a blocked network thread.

## Stop and report

1. Summary of what was built.
2. Files added or changed.
3. Decisions and assumptions made (the button object_id and friendly name, the
   command topic, the signalling mechanism chosen). Log them.
4. How it was verified (tests plus, if possible, a live press).
5. Open questions.
6. Risks and limitations.
7. Recommended next step.
