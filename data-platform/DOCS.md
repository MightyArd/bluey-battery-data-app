# Bluey Data Platform

## Installation

1. Add this repository to the Home Assistant add-on store
   (Settings > Add-ons > Add-on Store > top-right menu > Repositories), using
   `https://github.com/MightyArd/bluey-battery-data-app`.
2. Install the **Bluey Data Platform** add-on from the new entry.
3. Ensure the Mosquitto broker add-on is running (this add-on requires MQTT).
4. Start the add-on and check the log.

## Current behaviour (v0.2.0)

Every 5 minutes (aligned to AEMO dispatch boundaries, +60 seconds offset):

1. Fetches the latest P5MIN predispatch ZIP from NEMWeb
   (`https://nemweb.com.au/Reports/Current/P5_Reports/`).
2. Parses the REGIONSOLUTION table; extracts the VIC1 RRP for the interval
   equal to RUN_DATETIME + 5 minutes (the 5-minute-ahead price).
3. Publishes `sensor.p5_price_forecast` via MQTT discovery. The sensor has:
   - `state_class: measurement`, unit `$/MWh`.
   - A `run_id` attribute (the AEMO RUN_DATETIME string) so you can confirm
     which dispatch run is displayed.
4. Skips publish if the run has already been processed (deduped on RUN_DATETIME).

The last processed run id is stored at `/data/last_run_id.json` and survives
restarts.

Note: once this is running, add `sensor.p5_*` to the InfluxDB include globs in
your Home Assistant configuration so the values are logged.

## Options

- `log_level` - one of trace, debug, info, notice, warning, error, fatal.