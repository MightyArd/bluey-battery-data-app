# Changelog

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