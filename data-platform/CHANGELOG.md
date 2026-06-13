# Changelog

## 0.5.3
- Fix the B2 (cloud) upload, which failed every run with 403 AccessDenied ("not
  entitled") at "failed to prepare upload" despite correct, uncorrupted
  credentials (confirmed by the v0.5.2 diagnostics). The cause was rclone's S3
  backend running a bucket existence/creation check before the upload; a B2
  application key restricted to a single bucket has no bucket-create or
  list-all-buckets entitlement, so that check returned 403. The SMB (NAS) backend
  has no bucket concept, which is why only the cloud leg failed.
- write_rclone_config now writes no_check_bucket = true in the [b2] S3 section
  (rclone's documented remedy for keys without bucket-creation permission). The
  [nas] section is unchanged. No other behaviour changes.
- The v0.5.2 diagnostic logging is kept for this run, so the config dump will show
  no_check_bucket = true under [b2] and confirm the upload now succeeds; a later
  patch can trim the diagnostics once B2 is green.
- Unit test: the generated [b2] section contains no_check_bucket = true and the
  [nas] section does not.
- Bumped version to 0.5.3; updated config.yaml, DOCS.md, and the device model.

## 0.5.2
- Diagnostic-logging release: no behaviour change to upload, verification, path
  building, the key, or anything else. Logging only.
- When a B2 destination is configured, each archive run now INFO-logs, before the
  upload, exactly what the add-on sends to B2, to localise the AccessDenied (403,
  "not entitled") failures: the b2_key_id, b2_bucket, b2_endpoint and the
  destination object path; a non-revealing fingerprint of the secret key (length,
  first four and last two characters, and a leading/trailing whitespace flag); the
  exact rclone copyto invocation; and the /data/rclone.conf path, whether it
  existed before this run, and its contents.
- No secret is ever logged in plaintext. The b2_key and the NAS password are
  masked to **** in the config dump and the command, and the b2_key otherwise
  appears only as the fingerprint. A new redaction helper enforces this.
- Confirmed the rclone config file is rewritten from the current options on every
  run, so a stale config baked from an earlier key cannot be reused; the log states
  this explicitly per run.
- Unit tests: the fingerprint can never contain the full secret (including a short
  secret, where head and tail are also masked) and flags whitespace; the config
  redactor masks secret_access_key and pass while keeping access_key_id, endpoint
  and user; the secret-masking helper masks occurrences and is a no-op on empty
  (5 cases).
- Bumped version to 0.5.2; updated config.yaml, DOCS.md, and the device model.

## 0.5.1
- Fix NAS backup verification, which failed a correct upload with "is a file not a
  directory". rclone check operates on directories, not file paths; it is now
  pointed at the local staging directory and the remote directory with the file
  name included (--include) and --download, so the single uploaded file is hash
  compared on SMB (no server-side hash) and B2 alike. A present, matching file no
  longer reports as a verification failure, and the per-destination health
  timestamps still update only on a genuinely verified push.
- Fix the remote path so an empty nas_path no longer produces a double slash
  (energy-archive//2026/06). Segments are joined dropping empties, yielding
  energy-archive/2026/06. The same correction applies to both the NAS and B2 legs;
  the one-destination-fails-without-stopping-the-other behaviour is preserved.
- Fix the simulation InfluxDB reads, which errored with "mean: unsupported
  aggregate column type string" and left the simulation running on solar=0W,
  load=0W and a broken reserve profile. Both simulation reads in sources.py (the
  previous-period actuals mean and the trailing 7-day load/solar profile) now
  filter _field == "value" before mean(), so only the numeric state column is
  aggregated, not the string attribute fields HA also logs. The daily archive
  reads already filtered _field == "value" and are unchanged.
- No behaviour change to the daily timer, the force-backup button, the simulation
  logic, or the archive variable selection and rollup rules.
- Unit tests: simulation query builders include the _field filter; the remote-path
  builder drops empty segments (no double slash); the verification invocation uses
  the directory-plus-include form, not a bare file path (12 cases).
- Bumped version to 0.5.1; updated config.yaml, DOCS.md, and the device model.

## 0.5.0
- Force-backup button: a momentary MQTT button entity
  (button.bluey_data_platform_run_archive, friendly name "Force backup") under the
  existing Bluey Data Platform device. Pressing it runs the same daily archive the
  timer runs (rollup of the previous full local day, push to NAS and B2, checksum
  verification, backup-health timestamp updates).
- The press is routed safely: the MQTT callback only sets a thread-safe flag; the
  archive runs in the main loop, never on paho's network thread, so a multi-second
  run cannot stall the heartbeat or trip an MQTT disconnect. The single-threaded
  loop serialises manual and scheduled runs, so a press and the daily timer can
  never run concurrently.
- A manual press is purely additive: it does not touch the daily-run bookkeeping
  (last_archive_date), so it neither suppresses nor is suppressed by the scheduled
  run. A press while the NAS is off completes the B2 leg and skips the NAS leg
  cleanly, exactly like any run.
- The command subscription is re-established on every MQTT (re)connect, so a broker
  restart keeps the button live.
- Unit tests: trigger one-shot semantics, callback-sets-flag-not-run, bookkeeping
  isolation, scheduled-once-per-day, press-and-schedule serialisation, and button
  discovery config (14 cases).
- Bumped version to 0.5.0; updated config.yaml, DOCS.md, and the device model.
- Refactored the paho import in publisher.py and main.py behind TYPE_CHECKING (the
  pattern archive.py already uses) so the routing logic is unit-testable without
  the paho dependency; runtime behaviour is unchanged.

## 0.4.2
- Corrected the battery SOC entity name, which was assumed and did not exist:
  - Simulation soc_entity option default is now
    sensor.goodwe_battery_state_of_charge.
  - The archive battery_soc column reads goodwe_battery_state_of_charge (mean).
- Corrected the app-entity InfluxDB names: Home Assistant logs this add-on's own
  entities under bluey_data_platform_* (device name plus entity name), so the
  archive now reads bluey_data_platform_p5_price_forecast and
  bluey_data_platform_simulation_* rather than the unprefixed names.
- P5 run id: the archive reads the AEMO RUN_DATETIME from the run_id_str field on
  bluey_data_platform_p5_price_forecast (the price remains the value field).
- Persisted simulation state is now schema-versioned and bumped to 2, so the next
  run discards the old state (which had been seeded from the non-existent SOC
  entity) and re-seeds the counterfactual SOC from the corrected actual SOC.

## 0.4.1
- Corrected the archived energy-counter selections (no behaviour change otherwise):
  - Battery RTE inputs now use the cumulative lifetime counters
    goodwe_total_battery_charge and goodwe_total_battery_discharge (last), replacing
    the kWh-measurement auto-discovery, which could not match these names. RTE is
    therefore computable from deltas over any multi-day window. These are DC-terminal
    counters, so the derived RTE is the battery DC round-trip and excludes inverter
    conversion; AC-to-AC RTE is not available from these sensors.
  - Grid energy now uses the grid-meter counters goodwe_meter_total_energy_import and
    goodwe_meter_total_energy_export (matching goodwe_meter_active_power_total), not
    the inverter-side goodwe_total_energy_* nor the second meter goodwe_meter_2_*.
  - PV generation now uses goodwe_total_pv_generation.
  - goodwe_total_load, ev_energy_shelly_total and non_ev_load_energy_total unchanged.
- Removed the now-unused kWh-measurement RTE discovery from sources.py.

## 0.4.0
- Daily archive: once a day (default 00:30 local) query InfluxDB for the previous
  full local day, roll up to 5-minute resolution, write Parquet, and push the file
  to the Synology NAS and Backblaze B2, each verified by checksum.
- Rollup rules: mean for instantaneous quantities (power, SOC), last for
  cumulative kWh counters and categorical states; P5 and simulation values taken
  as-is. Every 5-minute bucket is forward-filled so flat sensors (grid power in
  particular) leave no gaps.
- Grid power is now archived as separate grid_import_power and grid_export_power
  columns, derived from the signed grid meter, so a window spanning both
  directions keeps a sensible mean in each.
- Round-trip efficiency counters are auto-detected in the kWh measurement and
  included when present; their absence is logged, never synthesised.
- Dual rclone push from Bluey: NAS over SMB and B2 over the S3 backend, with the
  cloud leg skipped gracefully when B2 options are unset. A failure of one
  destination still completes the other; the loop never crashes.
- Two backup-health timestamp sensors (backup_nas_last_success,
  backup_cloud_last_success) published only after a verified push.
- rclone config is generated at runtime from add-on options into /data/rclone.conf
  with SMB passwords obscured; no secrets are committed.
- New module: app/archive.py (pure rollup, Parquet write, dual push, health).
  sources.py gains raw-series reads with a forward-fill seed and RTE counter
  discovery. New add-on options for archive time and the two destinations.
- Unit tests: bucketing, mean-vs-last, forward-fill across flat and gappy series,
  grid split, RTE include/omit, and filename/partition logic (13 cases).
- Bumped version to 0.4.0; updated config.yaml, run.sh, DOCS.md, and CLAUDE.md.

## 0.3.0
- Battery dispatch simulation: shadow-mode settle + decide loop running every
  5-minute cycle after the P5 fetch.
- Four new MQTT discovery entities: sensor.bluey_data_platform_simulation_soc,
  simulation_planned_mode, simulation_settled_mode, simulation_grid_signed.
- New modules: app/simulator.py (decide + settle logic), app/sources.py (HA API
  + InfluxDB reads), app/state.py (durable state in /data/sim_state.json).
- Simulation parameters configurable as add-on options with sensible defaults:
  charge/export windows, reserve target, price override threshold, SOC limits,
  battery capacity, export cap, entity names, InfluxDB token, timezone.
- InfluxDB reads for period actuals (settle) and 7-day load/solar profile
  (reserve floor + decide). Falls back gracefully when token is not configured.
- Cold start seeds simulated SOC from actual battery SOC via HA Supervisor API.
- Reserve floor is dynamic: SOC needed to cover expected load to next 11:00.
- Unit tests: TestDecide (10 cases), TestSettle (8 cases), TestReserveFloor
  (3 cases).
- Bumped version to 0.3.0; updated config.yaml options/schema, run.sh, and
  requirements.txt (added tzdata for Alpine timezone support).

## 0.2.0
- P5 fetch-and-publish loop: every 5 minutes, fetch the AEMO P5MIN predispatch
  from NEMWeb, extract the VIC1 5-minute-ahead RRP, and publish to MQTT.
- MQTT discovery: sensor.p5_price_forecast appears automatically in Home
  Assistant (state_class measurement, unit $/MWh). The run_id is carried as a
  JSON attribute on the sensor.
- Dedupe: skips publish if RUN_DATETIME matches the last processed run; last
  run is persisted to /data/last_run_id.json across restarts.
- Loop aligned to 5-minute AEMO dispatch boundaries plus 60-second offset.
- New modules: app/p5.py, app/publisher.py, app/settings.py.
- Parser unit tests with a trimmed real-data fixture (tests/fixtures/).

## 0.1.0
- Initial scaffold. Connects to MQTT and publishes a heartbeat every 60
  seconds. No data features yet.