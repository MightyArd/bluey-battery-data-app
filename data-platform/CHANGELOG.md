# Changelog

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