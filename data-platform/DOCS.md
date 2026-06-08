# Bluey Data Platform

## Installation

1. Add this repository to the Home Assistant add-on store
   (Settings > Add-ons > Add-on Store > top-right menu > Repositories), using
   `https://github.com/MightyArd/bluey-battery-data-app`.
2. Install the **Bluey Data Platform** add-on from the new entry.
3. Ensure the Mosquitto broker add-on is running (this add-on requires MQTT).
4. Start the add-on and check the log.

## Current behaviour (v0.1.0)

Scaffold only. On start it connects to MQTT and publishes a retained heartbeat to
`bluey/data_platform/heartbeat` every 60 seconds. Use MQTT Explorer to confirm.

## Options

- `log_level` - one of trace, debug, info, notice, warning, error, fatal.
