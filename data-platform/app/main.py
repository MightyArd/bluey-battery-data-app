"""Bluey Data Platform - entry point.

v0.5.2: add redacted B2 push diagnostic logging (no behaviour change).
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import date, datetime
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

from . import archive as archive_mod
from . import p5 as p5_mod
from . import publisher
from . import simulator
from .settings import load as load_settings

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

    from .settings import Settings

log = logging.getLogger("bluey")

_HEARTBEAT_TOPIC = "bluey/data_platform/heartbeat"
_VERSION = "0.5.2"

_PERIOD_S = 300
_CYCLE_OFFSET_S = 120


def _next_wake(now: float) -> float:
    base = math.ceil((now - _CYCLE_OFFSET_S) / _PERIOD_S) * _PERIOD_S + _CYCLE_OFFSET_S
    if base <= now:
        base += _PERIOD_S
    return base


class ArchiveTrigger:
    """Thread-safe one-shot request flag for a manual (button) archive run.

    The MQTT message callback runs on paho's network-loop thread and only calls
    request(); the main loop calls take() once per iteration. take() atomically
    reports and clears any pending request, so the archive always runs in the main
    thread, never in the callback thread, and multiple presses between iterations
    collapse to a single run.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending = False

    def request(self) -> None:
        with self._lock:
            self._pending = True

    def take(self) -> bool:
        with self._lock:
            pending = self._pending
            self._pending = False
            return pending


def _handle_button_message(message: "mqtt.MQTTMessage", trigger: ArchiveTrigger) -> None:
    """paho network-thread callback: record a force-backup press and signal the loop.

    Never runs the archive here. run_archive can take seconds to a minute, and
    blocking paho's loop thread would risk a missed keepalive and an MQTT
    disconnect that would also stall the heartbeat. We only set a thread-safe flag;
    the main loop does the work on its own thread.
    """
    payload = message.payload.decode("utf-8", "ignore").strip()
    if payload and payload != publisher.RUN_ARCHIVE_PRESS_PAYLOAD:
        log.warning("Force-backup: ignoring unexpected command payload %r", payload)
        return
    log.info("Force-backup button pressed; queued a manual archive run for the main loop")
    trigger.request()


def _service_archives(
    client: "mqtt.Client",
    settings: "Settings",
    trigger: ArchiveTrigger,
    last_archive_date: date | None,
    now_local: datetime,
    runner: Callable[..., None] = archive_mod.run_archive,
) -> date | None:
    """Run any archives due this iteration, in the main thread, and return the
    (possibly updated) last_archive_date.

    A pending manual press runs first and is purely additive: it neither reads nor
    writes last_archive_date, so it does not suppress, and is not suppressed by, the
    scheduled daily run. The scheduled run is unchanged: it fires once per local day
    at or after the configured time and records last_archive_date. Both run in this
    single-threaded loop, so a press and the timer are serialised and can never run
    concurrently, even when they coincide.
    """
    if trigger.take():
        log.info("Manual archive run starting (force-backup button)")
        try:
            runner(client, settings)
        except Exception as exc:
            log.error("Manual archive run failed: %s", exc, exc_info=True)
        log.info("Manual archive run finished (force-backup button)")

    after_time = (now_local.hour, now_local.minute) >= (
        settings.archive_hour, settings.archive_minute
    )
    if after_time and last_archive_date != now_local.date():
        log.info("Scheduled daily archive starting")
        try:
            runner(client, settings)
        except Exception as exc:
            log.error("Daily archive failed: %s", exc, exc_info=True)
        last_archive_date = now_local.date()
    return last_archive_date


def _make_client(settings: "Settings", trigger: ArchiveTrigger) -> "mqtt.Client":
    import paho.mqtt.client as mqtt

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="bluey-data-platform"
    )
    if settings.mqtt_user:
        client.username_pw_set(settings.mqtt_user, settings.mqtt_password)

    def _on_connect(
        client: "mqtt.Client",
        userdata: object,
        flags: object,
        reason_code: object,
        properties: object,
    ) -> None:
        # (Re)subscribe on every connect so a broker restart keeps the button live.
        client.subscribe(publisher.RUN_ARCHIVE_COMMAND_TOPIC)
        log.info("Subscribed to force-backup command topic %s",
                 publisher.RUN_ARCHIVE_COMMAND_TOPIC)

    def _on_button(
        client: "mqtt.Client", userdata: object, message: "mqtt.MQTTMessage"
    ) -> None:
        _handle_button_message(message, trigger)

    client.on_connect = _on_connect
    client.message_callback_add(publisher.RUN_ARCHIVE_COMMAND_TOPIC, _on_button)
    client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
    client.loop_start()
    return client


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log.info(
        "Bluey Data Platform v%s starting (MQTT %s:%s)",
        _VERSION,
        settings.mqtt_host,
        settings.mqtt_port,
    )

    trigger = ArchiveTrigger()
    client = _make_client(settings, trigger)
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
        last_archive_date = _service_archives(
            client, settings, trigger, last_archive_date, now_local
        )

        wake = _next_wake(time.time())
        log.info("Next wake in %.0fs", wake - time.time())
        time.sleep(max(0.0, wake - time.time()))


if __name__ == "__main__":
    main()