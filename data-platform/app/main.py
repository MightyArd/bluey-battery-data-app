"""Bluey Data Platform - entry point.

v0.2.0: 5-minute P5 fetch-and-publish loop aligned to AEMO dispatch intervals.
"""
from __future__ import annotations

import json
import logging
import math
import time

import paho.mqtt.client as mqtt

from . import p5 as p5_mod
from . import publisher
from .settings import load as load_settings

_HEARTBEAT_TOPIC = "bluey/data_platform/heartbeat"
_VERSION = "0.2.0"

# Loop fires at the first minute-multiple-of-5 boundary after CYCLE_OFFSET_S
# seconds into each 5-minute window. 60 s gives AEMO time to publish the file.
_PERIOD_S = 300
_CYCLE_OFFSET_S = 60


def _next_wake(now: float) -> float:
    """Return the next aligned wake time: next 5-minute boundary + offset."""
    base = math.ceil((now - _CYCLE_OFFSET_S) / _PERIOD_S) * _PERIOD_S + _CYCLE_OFFSET_S
    if base <= now:
        base += _PERIOD_S
    return base


def _make_client(settings) -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="bluey-data-platform"
    )
    if settings.mqtt_user:
        client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()
    return client


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("bluey")
    log.info(
        "Bluey Data Platform v%s starting (MQTT %s:%s)",
        _VERSION,
        settings.mqtt_host,
        settings.mqtt_port,
    )

    client = _make_client(settings)
    publisher.publish_discovery(client)

    last_run_dt = p5_mod.load_last_run(settings.data_dir)
    log.info("Last processed P5 run: %s", last_run_dt or "none")

    while True:
        hb = json.dumps({"ts": round(time.time()), "status": "alive", "version": _VERSION})
        client.publish(_HEARTBEAT_TOPIC, hb, retain=True)

        result = p5_mod.fetch_and_parse(last_run_dt)
        if result is not None:
            publisher.publish_p5(client, result)
            p5_mod.save_last_run(settings.data_dir, result.run_datetime)
            last_run_dt = result.run_datetime
            log.info("Cycle complete: rrp=%.4f run=%s", result.rrp, result.run_datetime)
        else:
            log.info("Cycle complete: no new P5 run")

        wake = _next_wake(time.time())
        log.info("Next wake in %.0fs", wake - time.time())
        time.sleep(max(0.0, wake - time.time()))


if __name__ == "__main__":
    main()