# Bluey Battery Data App

A local Home Assistant add-on running on Bluey (ODROID-N2+, HAOS). It is the
spine of the home energy data platform: it ingests AEMO price forecasts, runs a
shadow battery-dispatch simulation, and archives 5-minute data off the box.

## What it does

Two timers in one Python service:

- **Every 5 minutes** it fetches AEMO's P5 predispatch from NEMWeb, extracts the
  5-minute-ahead VIC1 price and the run id, and publishes them to MQTT. It then
  runs the stateful dispatch simulation (settle the period that just closed using
  last tick's decision plus actuals; decide the upcoming period) and publishes the
  simulation outputs to MQTT.
- **Once a day** it queries InfluxDB for the previous day, rolls it up to
  5-minute resolution, writes Parquet, pushes it to the Synology and the cloud
  with checksum verification, and publishes a health timestamp per destination.

Everything it publishes becomes a Home Assistant entity over MQTT, which flows
into InfluxDB through the existing logging globs. The app never writes to the
database directly; its only outputs are MQTT messages and the daily Parquet files.

## Why it exists

HAOS is a locked appliance with nowhere to run scheduled custom code, and HA
automations cannot reliably do scheduled external fetching with unzip-and-parse
of AEMO's nested CSV, a simulation that carries state across ticks, or a daily
backup with integrity checks and per-destination health. Those need a real
Python runtime with libraries, persistent state, and proper lifecycle
management. This add-on is that runtime.

## Build status

Incremental build. Current state: **scaffold** (v0.1.0) - connects to MQTT and
publishes a heartbeat. P5 fetch, simulation, and archive are added in later
increments.

## Layout

- `data-platform/` - the add-on (slug `data_platform`)
  - `config.yaml` - add-on manifest (options, schema, MQTT/HA API access)
  - `build.yaml` - base image (aarch64)
  - `Dockerfile`, `run.sh`, `requirements.txt`
  - `app/` - the Python service
    - `main.py` - scheduler and loops (heartbeat only, for now)

## Configuration and secrets

All credentials (NAS, cloud, InfluxDB) are entered in the add-on options at
runtime and stored by the Supervisor. They are never committed to this repo.
