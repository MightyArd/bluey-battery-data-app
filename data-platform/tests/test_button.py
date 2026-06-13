"""Unit tests for the force-backup button: press routing, bookkeeping, concurrency.

These exercise app.main's pure pieces (the trigger flag, the message handler, and
the per-iteration archive servicing) with a stub runner, so no MQTT broker, no
paho, and no real archive run are needed. The contract under test:

- a press only sets a thread-safe flag (it never runs the archive on the callback
  thread); the run happens later in the main loop;
- a manual press does not touch last_archive_date, so it neither suppresses nor is
  suppressed by the scheduled daily run;
- a press coinciding with the scheduled run is serialised by the single-threaded
  loop and never runs concurrently.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import app.main as main
import app.publisher as publisher


class FakeMessage:
    """Stand-in for paho's MQTTMessage: only .payload (bytes) is read."""

    def __init__(self, payload: bytes, topic: str = publisher.RUN_ARCHIVE_COMMAND_TOPIC):
        self.payload = payload
        self.topic = topic


class FakeClient:
    """Records publish() calls so discovery configs can be inspected."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload=None, retain=False):
        self.published.append((topic, payload, retain))


def _settings(archive_hour: int = 0, archive_minute: int = 30) -> SimpleNamespace:
    return SimpleNamespace(archive_hour=archive_hour, archive_minute=archive_minute)


# --------------------------------------------------------------------------- #
# ArchiveTrigger: thread-safe one-shot flag.
# --------------------------------------------------------------------------- #


class TestArchiveTrigger:
    def test_empty_when_unset(self):
        assert main.ArchiveTrigger().take() is False

    def test_request_then_take_is_true_once(self):
        t = main.ArchiveTrigger()
        t.request()
        assert t.take() is True
        assert t.take() is False  # one-shot: consumed

    def test_multiple_requests_collapse_to_one(self):
        t = main.ArchiveTrigger()
        t.request()
        t.request()
        assert t.take() is True
        assert t.take() is False


# --------------------------------------------------------------------------- #
# Button callback: sets the flag, never runs the archive on the callback thread.
# --------------------------------------------------------------------------- #


class TestButtonCallback:
    def test_press_only_sets_flag_does_not_run_archive(self, monkeypatch):
        # If routing leaked into the callback thread, this stub would be called.
        called: list[int] = []
        monkeypatch.setattr(
            main.archive_mod, "run_archive", lambda *a, **k: called.append(1)
        )
        trigger = main.ArchiveTrigger()

        main._handle_button_message(FakeMessage(b"PRESS"), trigger)

        assert called == []            # archive NOT run from the callback
        assert trigger.take() is True  # request queued for the main loop instead

    def test_empty_payload_is_treated_as_a_press(self):
        trigger = main.ArchiveTrigger()
        main._handle_button_message(FakeMessage(b""), trigger)
        assert trigger.take() is True

    def test_unexpected_payload_is_ignored(self):
        trigger = main.ArchiveTrigger()
        main._handle_button_message(FakeMessage(b"definitely-not-a-press"), trigger)
        assert trigger.take() is False


# --------------------------------------------------------------------------- #
# Main-loop servicing: routing, bookkeeping isolation, serialisation.
# --------------------------------------------------------------------------- #


class TestServiceArchives:
    def test_pending_press_routes_to_run_archive(self):
        calls: list[tuple] = []
        trigger = main.ArchiveTrigger()
        trigger.request()
        # 00:00 is before the 00:30 schedule, so only the manual run can fire.
        now = datetime(2026, 6, 13, 0, 0)

        out = main._service_archives(
            "client", _settings(), trigger, None, now,
            runner=lambda c, s: calls.append((c, s)),
        )

        assert len(calls) == 1       # the press ran the archive
        assert out is None           # manual run did not set last_archive_date

    def test_manual_press_does_not_alter_last_archive_date(self):
        trigger = main.ArchiveTrigger()
        trigger.request()
        now = datetime(2026, 6, 13, 0, 10)  # before 00:30; scheduled not yet due
        prior = date(2026, 6, 12)
        calls: list[int] = []

        out = main._service_archives(
            "c", _settings(), trigger, prior, now,
            runner=lambda c, s: calls.append(1),
        )

        assert calls == [1]   # manual run happened
        assert out == prior   # bookkeeping untouched: not advanced to "today"

    def test_manual_press_does_not_suppress_later_scheduled_run(self):
        settings = _settings()
        prior = date(2026, 6, 12)
        calls: list[str] = []
        trigger = main.ArchiveTrigger()

        # Iteration 1: a press before the scheduled time.
        trigger.request()
        d = main._service_archives(
            "c", settings, trigger, prior, datetime(2026, 6, 13, 0, 10),
            runner=lambda c, s: calls.append("manual"),
        )
        assert calls == ["manual"]
        assert d == prior  # still not advanced

        # Iteration 2: the scheduled time is reached, no press pending.
        d = main._service_archives(
            "c", settings, trigger, d, datetime(2026, 6, 13, 0, 30),
            runner=lambda c, s: calls.append("scheduled"),
        )
        assert calls == ["manual", "scheduled"]  # scheduled still fired
        assert d == date(2026, 6, 13)

    def test_scheduled_run_fires_once_per_day(self):
        settings = _settings()
        calls: list[int] = []
        trigger = main.ArchiveTrigger()

        def runner(c, s):
            calls.append(1)

        now = datetime(2026, 6, 13, 0, 30)

        d = main._service_archives("c", settings, trigger, None, now, runner=runner)
        assert calls == [1]
        assert d == date(2026, 6, 13)

        # Same day, later iteration: must not run again.
        d = main._service_archives(
            "c", settings, trigger, d, datetime(2026, 6, 13, 1, 0), runner=runner
        )
        assert calls == [1]
        assert d == date(2026, 6, 13)

    def test_press_coinciding_with_scheduled_runs_serially_not_concurrently(self):
        # A re-entrancy detector: if the two runs ever overlapped, the second entry
        # would see in_progress True and fail. Single-threaded servicing keeps them
        # strictly sequential.
        state = {"in_progress": False, "count": 0}

        def runner(client, settings):
            assert state["in_progress"] is False, "archive ran concurrently"
            state["in_progress"] = True
            state["count"] += 1
            state["in_progress"] = False

        trigger = main.ArchiveTrigger()
        trigger.request()
        now = datetime(2026, 6, 13, 0, 30)  # scheduled due AND a press pending

        out = main._service_archives("c", _settings(), trigger, None, now, runner=runner)

        assert state["count"] == 2       # manual + scheduled, both ran
        assert out == date(2026, 6, 13)  # scheduled recorded; manual did not interfere

    def test_runner_exception_does_not_propagate(self):
        trigger = main.ArchiveTrigger()
        trigger.request()

        def boom(c, s):
            raise RuntimeError("nas offline")

        # Must not raise: a failed manual run never crashes the main loop.
        out = main._service_archives(
            "c", _settings(), trigger, None, datetime(2026, 6, 13, 0, 0), runner=boom
        )
        assert out is None


# --------------------------------------------------------------------------- #
# Discovery: the button advertises correctly under the existing device.
# --------------------------------------------------------------------------- #


class TestButtonDiscovery:
    def test_button_discovery_config(self):
        client = FakeClient()
        publisher._publish_button_discovery(client)

        assert len(client.published) == 1
        topic, payload, retain = client.published[0]
        assert topic == publisher._DISCOVERY_BUTTON
        assert retain is True

        cfg = json.loads(payload)
        # object_id under the device name -> button.bluey_data_platform_run_archive
        assert cfg["object_id"] == "run_archive"
        assert cfg["name"] == "Force backup"
        assert cfg["command_topic"] == publisher.RUN_ARCHIVE_COMMAND_TOPIC
        assert cfg["payload_press"] == publisher.RUN_ARCHIVE_PRESS_PAYLOAD
        assert cfg["device"]["identifiers"] == ["bluey_data_platform"]

    def test_publish_discovery_includes_the_button(self):
        client = FakeClient()
        publisher.publish_discovery(client)
        topics = {t for t, _, _ in client.published}
        assert publisher._DISCOVERY_BUTTON in topics
