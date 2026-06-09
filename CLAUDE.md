# CLAUDE.md - Bluey Battery Data App

Standing context for Claude Code sessions on this repo. Read this before any work.

## What this is

A local Home Assistant add-on running on Bluey (ODROID-N2+, HAOS, aarch64). It is
the spine of a home energy data platform. One Python service, two timers:

- Every 5 minutes: fetch AEMO P5 predispatch from NEMWeb, publish the
  5-minute-ahead VIC1 price and the run id to MQTT; run the shadow battery
  dispatch simulation; publish the simulation outputs to MQTT.
- Once a day: query InfluxDB for the previous day, roll up to 5-minute
  resolution, write Parquet, push to the Synology and the cloud with checksum
  verification, publish a health timestamp per destination.

Current state: scaffold v0.1.0 (MQTT heartbeat only). The build is incremental,
one checkpoint at a time.

## Architecture rules (do not violate)

- The publish path is MQTT to Home Assistant. The app's only outputs are MQTT
  messages and the daily Parquet files.
- The app NEVER writes to InfluxDB directly. Values published to MQTT become HA
  entities (via MQTT discovery), and HA's own InfluxDB integration logs them.
- The app MAY read InfluxDB (later increments) for previous-period actuals.
  Reads must forward-fill, because HA logs only on state change, so a sensor
  sitting at a constant value is sparse (no points during flat periods).
- Shadow-mode only: the simulation computes and logs what it would do. It NEVER
  actuates the battery or inverter.
- Secrets (NAS, cloud, InfluxDB token) come from add-on options at runtime and
  are stored by the Supervisor. NEVER commit secrets. The repo holds code and
  sensible defaults only.

## Layout

- `data-platform/` is the add-on (slug `data_platform`).
  - `config.yaml`, `build.yaml` (aarch64), `Dockerfile`, `run.sh`, `requirements.txt`.
  - `app/` is the service: `main.py` (loops), plus `p5.py`, `publisher.py`,
    `simulator.py`, `sources.py`, `archive.py`, `state.py`, `settings.py` as
    they are added.
  - `tests/` is pytest.
- `/data` is the persistent volume (state.json, rclone.conf, Parquet staging). It
  survives restarts and updates. All durable state lives here.

## Runtime facts

- MQTT: the Supervisor injects the connection (`services: mqtt:need`). `run.sh`
  exports `MQTT_HOST/PORT/USER/PASSWORD` via bashio. Broker is `core-mosquitto:1883`.
- HA API: `homeassistant_api: true`. Use `SUPERVISOR_TOKEN` to read entity states
  (for example battery SOC) through the Supervisor's HA API proxy.
- InfluxDB (later increments): `http://ec9cbdb7-influxdb2:8086`, org `home`,
  bucket `home_assistant`. Token supplied via an add-on option.

## Hardware and signal facts (GoodWe)

- Grid power sensor is `sensor.goodwe_meter_active_power_total`. NEGATIVE means
  import, POSITIVE means export (confirmed against a 14.6 kW import event).
- Battery charge rate caps around 6.5 kW, not 10 kW.
- Grid export is currently off: `number.goodwe_grid_export_limit` is 500 W,
  pending DNSP approval. Treat the export limit as a simulation parameter, not a
  constant.
- Depth of discharge on-grid is 95%; usable battery is about 40 kWh.
- HA logs only on state change, so flat sensors are sparse in InfluxDB. Any
  rollup or read must forward-fill.

## Data the platform stores (5-minute archive; for later increments)

All scalar time-series. Rollup rule: mean for instantaneous quantities (power,
SOC, temperature), last for cumulative kWh counters and categorical states. P5
and simulation values are 5-minute-native, so stored as-is.

- Measured: `grid_signed_power`, `battery_signed_power`, battery SOC,
  `goodwe_battery_mode`, `goodwe_pv_power_total`, `goodwe_house_consumption`,
  `ev_power`, `non_ev_load_power`. Energy counters: grid import, grid export
  (kept split, never netted), `goodwe_total_load`, PV generation,
  `ev_energy_shelly_total`, `non_ev_load_energy_total`.
- P5: `p5_price_forecast` (5-minute-ahead VIC1 RRP, $/MWh), `p5_run_id` (AEMO
  RUN_DATETIME).
- Simulation: `simulation_soc`, `simulation_battery_mode`, `simulation_mode`,
  `simulation_grid_signed`.

## Simulation design (for later increments)

- Single-step, stateful, decide-ahead and settle-behind. Each 5-minute tick:
  settle the period that just closed (using the decision made last tick plus the
  actuals that occurred), then decide the mode for the upcoming period. Persist
  the pending decision and the simulated SOC in `/data/state.json`. The simulated
  SOC runs as an independent counterfactual, seeded once from actual SOC.
- MVP rules: scheduled charge window, scheduled export window, SOC reserve for
  forecast use, price override (export when the next P5 price is high).
  Precedence: hard SOC limits, then reserve floor, then price override, then
  scheduled windows. Export is capped by the export-limit parameter.
- `simulation_mode` is a closed enum: `free_charge`, `grid_charge`,
  `scheduled_export`, `spike_discharge`, `self_consume`, `idle`.

## Conventions

- Australian English. No em dashes in any distributed text: docs, code comments,
  READMEs, commit messages.
- Python: Polars (not pandas), mypy strict, ruff, pytest. Put logic in pure,
  testable functions.
- Git: single linear thread on main; add, commit, push as single commits.
- Checkpoint discipline: one task brief per increment is the contract. Stop at
  the checkpoint and report. Do not run ahead into the next increment.
