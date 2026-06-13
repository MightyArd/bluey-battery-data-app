"""Bluey Data Platform - entry point.

v0.4.0: adds the once-a-day archive (rollup to Parquet, push to NAS and B2).
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt

from . import archive as archive_mod
from . import p5 as p5_mod
from . import publisher
from . import simulator
from .settings import load as load_settings

_HEARTBEAT_TOPIC = "bluey/data_platform/heartbeat"
_VERSION = "0.4.0"

_PERIOD_S = 300
_CYCLE_OFFSET_S = 120


def _next_wake(now: float) -> float:
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
    last_p5_rrp: float | None = None
    last_archive_date: date | None = None
    tz = ZoneInfo(settings.timezone)
    log.info("Last processed P5 run: %s", last_run_dt or "none")
    log.info("Daily archive scheduled for %02d:%02d %s",
             settings.archive_hour, settings.archive_minute, settings.timezone)

    while True:
        hb = json.dumps({"ts": round(time.time()), "status": "alive", "version": _VERSION})
        client.publish(_HEARTBEAT_TOPIC, hb, retain=True)

        result = p5_mod.fetch_and_parse(last_run_dt)
        if result is not None:
            publisher.publish_p5(client, result)
            p5_mod.save_last_run(settings.data_dir, result.run_datetime)
            last_run_dt = result.run_datetime
            last_p5_rrp = result.rrp
            log.info("P5 cycle complete: rrp=%.4f run=%s", result.rrp, result.run_datetime)
        else:
            log.info("P5 cycle complete: no new run")

        try:
            simulator.run_step(client, settings, last_p5_rrp)
        except Exception as exc:
            log.error("Simulation step failed: %s", exc, exc_info=True)

        now_local = datetime.now(tz)
        after_time = (now_local.hour, now_local.minute) >= (
            settings.archive_hour, settings.archive_minute
        )
        if after_time and last_archive_date != now_local.date():
            try:
                archive_mod.run_archive(client, settings)
            except Exception as exc:
                log.error("Daily archive failed: %s", exc, exc_info=True)
            last_archive_date = now_local.date()

        wake = _next_wake(time.time())
        log.info("Next wake in %.0fs", wake - time.time())
        time.sleep(max(0.0, wake - time.time()))


if __name__ == "__main__":
    main()