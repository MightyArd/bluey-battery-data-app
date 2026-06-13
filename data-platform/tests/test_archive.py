"""Unit tests for the daily archive rollup, forward-fill, and naming logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import archive
from app.archive import (
    build_specs,
    daily_filename,
    day_bounds,
    partition_path,
    push_verified,
    rollup_series,
    split_grid_power,
    time_buckets,
)

TZ = "Australia/Melbourne"


def _utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class TestBuckets:
    def test_normal_day_has_288_buckets(self):
        start, stop = day_bounds(date(2026, 6, 9), TZ)
        buckets = time_buckets(start, stop)
        assert len(buckets) == 288
        assert buckets[0] == start
        assert buckets[-1] == stop - timedelta(minutes=5)

    def test_day_bounds_span_one_local_day(self):
        start, stop = day_bounds(date(2026, 6, 9), TZ)
        # 10 hours offset in winter (AEST, UTC+10): local midnight = 14:00 UTC prior day
        assert (stop - start) == timedelta(days=1)
        assert start.tzinfo == timezone.utc


class TestRollupMeanVsLast:
    def test_mean_averages_points_in_bucket(self):
        buckets = [_utc(2026, 6, 9, 0, 0)]
        records = [
            (_utc(2026, 6, 9, 0, 1), 10.0),
            (_utc(2026, 6, 9, 0, 2), 20.0),
            (_utc(2026, 6, 9, 0, 3), 30.0),
        ]
        out = rollup_series(records, buckets, "mean")
        assert out == [pytest.approx(20.0)]

    def test_last_takes_final_point_in_bucket(self):
        buckets = [_utc(2026, 6, 9, 0, 0)]
        records = [
            (_utc(2026, 6, 9, 0, 1), 100.0),
            (_utc(2026, 6, 9, 0, 4), 175.0),
        ]
        out = rollup_series(records, buckets, "last")
        assert out == [175.0]

    def test_last_preserves_categorical_strings(self):
        buckets = [_utc(2026, 6, 9, 0, 0), _utc(2026, 6, 9, 0, 5)]
        records = [(_utc(2026, 6, 9, 0, 2), "eco_charge")]
        out = rollup_series(records, buckets, "last")
        # carried forward into the second, empty bucket
        assert out == ["eco_charge", "eco_charge"]


class TestForwardFill:
    def test_flat_sensor_fills_every_bucket_from_seed(self):
        # One seed point before the day, then nothing: every bucket carries it.
        buckets = time_buckets(*day_bounds(date(2026, 6, 9), TZ))
        records = [(buckets[0] - timedelta(hours=3), 0.0)]
        out = rollup_series(records, buckets, "mean")
        assert len(out) == len(buckets)
        assert all(v == 0.0 for v in out)
        assert None not in out

    def test_gap_between_changes_is_filled_not_left_empty(self):
        buckets = [_utc(2026, 6, 9, 0, m) for m in range(0, 25, 5)]  # 5 buckets
        records = [
            (_utc(2026, 6, 9, 0, 1), 7.0),   # bucket 0
            (_utc(2026, 6, 9, 0, 22), 9.0),  # bucket 4
        ]
        out = rollup_series(records, buckets, "last")
        # buckets 1,2,3 had no points but must carry 7.0; bucket 4 takes 9.0
        assert out == [7.0, 7.0, 7.0, 7.0, 9.0]

    def test_no_data_before_first_value_stays_none(self):
        buckets = [_utc(2026, 6, 9, 0, 0), _utc(2026, 6, 9, 0, 5)]
        records = [(_utc(2026, 6, 9, 0, 6), 4.0)]  # only in second bucket
        out = rollup_series(records, buckets, "mean")
        assert out == [None, 4.0]


class TestGridSplit:
    def test_split_separates_import_and_export(self):
        # negative = import, positive = export
        records = [
            (_utc(2026, 6, 9, 0, 1), -3000.0),  # importing 3 kW
            (_utc(2026, 6, 9, 0, 2), 500.0),    # exporting 500 W
        ]
        imp, exp = split_grid_power(records)
        assert [v for _, v in imp] == [3000.0, 0.0]
        assert [v for _, v in exp] == [0.0, 500.0]

    def test_window_with_both_directions_keeps_both_means(self):
        buckets = [_utc(2026, 6, 9, 0, 0)]
        records = [
            (_utc(2026, 6, 9, 0, 1), -1000.0),
            (_utc(2026, 6, 9, 0, 2), 1000.0),
        ]
        imp, exp = split_grid_power(records)
        assert rollup_series(imp, buckets, "mean") == [pytest.approx(500.0)]
        assert rollup_series(exp, buckets, "mean") == [pytest.approx(500.0)]


class TestSpecsAndNaming:
    def _spec(self, column: str):
        return next(s for s in build_specs() if s.column == column)

    def test_battery_rte_uses_lifetime_counters_as_last(self):
        charge = self._spec("goodwe_total_battery_charge")
        discharge = self._spec("goodwe_total_battery_discharge")
        assert charge.entity_id == "goodwe_total_battery_charge"
        assert discharge.entity_id == "goodwe_total_battery_discharge"
        assert charge.agg == "last" and discharge.agg == "last"

    def test_grid_energy_uses_grid_meter_counters(self):
        assert self._spec("grid_import_energy").entity_id == "goodwe_meter_total_energy_import"
        assert self._spec("grid_export_energy").entity_id == "goodwe_meter_total_energy_export"
        assert self._spec("grid_import_energy").agg == "last"
        assert self._spec("grid_export_energy").agg == "last"

    def test_pv_generation_uses_total_counter(self):
        spec = self._spec("goodwe_total_pv_generation")
        assert spec.entity_id == "goodwe_total_pv_generation"
        assert spec.agg == "last"

    def test_remaining_energy_counters_exact(self):
        cols = {s.column for s in build_specs()}
        for name in ("goodwe_total_load", "ev_energy_shelly_total", "non_ev_load_energy_total"):
            assert name in cols
        # inverter-side and second-meter counters must not be archived
        entities = {s.entity_id for s in build_specs()}
        assert "goodwe_total_energy_import" not in entities
        assert "goodwe_total_energy_export" not in entities
        assert not any(e.startswith("goodwe_meter_2_") for e in entities)

    def test_battery_soc_uses_state_of_charge_entity(self):
        spec = self._spec("battery_soc")
        assert spec.entity_id == "goodwe_battery_state_of_charge"
        assert spec.agg == "mean"

    def test_app_entities_use_device_prefixed_names(self):
        app_cols = (
            "p5_price_forecast", "p5_run_id", "simulation_soc",
            "simulation_planned_mode", "simulation_settled_mode", "simulation_grid_signed",
        )
        for col in app_cols:
            assert self._spec(col).entity_id.startswith("bluey_data_platform_")

    def test_p5_run_id_reads_run_id_str_field(self):
        price = self._spec("p5_price_forecast")
        run_id = self._spec("p5_run_id")
        assert price.entity_id == "bluey_data_platform_p5_price_forecast"
        assert price.field == "value"  # price is the state
        assert run_id.entity_id == "bluey_data_platform_p5_price_forecast"
        assert run_id.field == "run_id_str"  # AEMO RUN_DATETIME string

    def test_filename_and_partition(self):
        d = date(2026, 6, 9)
        assert daily_filename(d) == "energy_5min_2026-06-09.parquet"
        assert partition_path(d) == "2026/06"


class TestRemoteJoin:
    def test_empty_nas_path_produces_no_double_slash(self):
        # The live defect: nas_path empty gave nas:energy-archive//2026/06.
        assert (
            archive._remote_join("nas:energy-archive", "", "2026/06")
            == "nas:energy-archive/2026/06"
        )

    def test_set_nas_path_joins_with_single_slashes(self):
        assert (
            archive._remote_join("nas:share", "energy-archive", "2026/06")
            == "nas:share/energy-archive/2026/06"
        )

    def test_stray_slashes_on_segments_are_stripped(self):
        assert (
            archive._remote_join("b2:bucket", "/energy-archive/", "2026/06")
            == "b2:bucket/energy-archive/2026/06"
        )


class _RcloneRecorder:
    """Stand-in for archive._rclone: records each arg list and returns scripted results."""

    def __init__(self, results: list[bool]):
        self.calls: list[list[str]] = []
        self._results = iter(results)

    def __call__(self, args, config_path):
        self.calls.append(args)
        return next(self._results)


class TestPushVerified:
    def _local(self, tmp_path):
        f = tmp_path / "energy_5min_2026-06-12.parquet"
        f.write_text("parquet-bytes")
        return f

    def test_verify_targets_directory_plus_include_not_bare_file(self, monkeypatch, tmp_path):
        rec = _RcloneRecorder([True, True])  # copy ok, verify ok
        monkeypatch.setattr(archive, "_rclone", rec)
        local = self._local(tmp_path)
        remote = "nas:energy-archive/2026/06"

        assert push_verified(local, remote, tmp_path / "rclone.conf") is True
        assert len(rec.calls) == 2

        copy_args = rec.calls[0]
        assert copy_args[0] == "copyto"
        assert copy_args[-1] == f"{remote}/{local.name}"

        verify_args = rec.calls[1]
        assert verify_args[0] == "check"
        assert "--download" in verify_args        # SMB has no server-side hash
        assert "--one-way" in verify_args          # ignore other files at the remote
        assert "--include" in verify_args
        assert local.name in verify_args           # restricted to the single file
        assert str(local.parent) in verify_args    # local dir, not the file path
        assert remote in verify_args               # remote dir, not the file path
        # the bare remote file path must NOT be a check argument (the old bug)
        assert f"{remote}/{local.name}" not in verify_args

    def test_failed_upload_does_not_attempt_verification(self, monkeypatch, tmp_path):
        rec = _RcloneRecorder([False])  # copy fails
        monkeypatch.setattr(archive, "_rclone", rec)
        local = self._local(tmp_path)

        assert push_verified(local, "nas:share/2026/06", tmp_path / "c.conf") is False
        assert len(rec.calls) == 1  # no verify after a failed copy

    def test_verification_failure_returns_false(self, monkeypatch, tmp_path):
        rec = _RcloneRecorder([True, False])  # copy ok, verify fails
        monkeypatch.setattr(archive, "_rclone", rec)
        local = self._local(tmp_path)

        assert push_verified(local, "nas:share/2026/06", tmp_path / "c.conf") is False
        assert len(rec.calls) == 2


class TestB2DiagnosticRedaction:
    # A realistic B2 application key: 31 chars, like the live "...004" key.
    SECRET = "K004abcdefghijklmnopqrstuvwxy8o"

    def test_fingerprint_never_contains_full_secret(self):
        fp = archive._fingerprint(self.SECRET)
        assert self.SECRET not in fp
        assert f"len={len(self.SECRET)}" in fp
        assert "head=K004" in fp
        assert "tail=8o" in fp
        assert "ws=no" in fp

    def test_fingerprint_flags_leading_or_trailing_whitespace(self):
        assert "ws=yes" in archive._fingerprint("  paddedsecretvalue  ")
        assert "ws=no" in archive._fingerprint("cleansecretvalue")

    def test_fingerprint_masks_short_secret_entirely(self):
        # head+tail of a short secret could reconstruct it, so both are masked.
        secret = "abc123"
        fp = archive._fingerprint(secret)
        assert secret not in fp
        assert "len=6" in fp
        assert "head=****" in fp

    def test_redact_rclone_config_masks_secrets_keeps_metadata(self):
        cfg = (
            "[b2]\ntype = s3\nprovider = Other\n"
            "access_key_id = K004publicidvalue\n"
            f"secret_access_key = {self.SECRET}\n"
            "endpoint = s3.us-west-004.backblazeb2.com\n\n"
            "[nas]\ntype = smb\nuser = backup\npass = OBSCUREDNASPASS\n"
        )
        red = archive._redact_rclone_config(cfg)
        # both secrets gone, masked
        assert self.SECRET not in red
        assert "OBSCUREDNASPASS" not in red
        assert "secret_access_key = ****" in red
        assert "pass = ****" in red
        # non-secret metadata preserved in full
        assert "access_key_id = K004publicidvalue" in red
        assert "endpoint = s3.us-west-004.backblazeb2.com" in red
        assert "user = backup" in red

    def test_redact_secret_masks_occurrences_and_noop_on_empty(self):
        assert archive._redact_secret(f"copyto x {self.SECRET}", self.SECRET) == "copyto x ****"
        assert archive._redact_secret("nothing to mask", "") == "nothing to mask"


class TestRcloneConfig:
    def _settings(self):
        # Only the fields write_rclone_config reads; both destinations configured.
        return SimpleNamespace(
            nas_host="192.168.50.214",
            nas_share="energy-archive",
            nas_user="backup",
            nas_password="naspw",
            b2_bucket="bluey-energy-archive",
            b2_key_id="K004keyid",
            b2_key="K004secretvalue",
            b2_endpoint="s3.us-west-004.backblazeb2.com",
        )

    def test_b2_section_has_no_check_bucket_and_nas_does_not(self, monkeypatch, tmp_path):
        # Avoid the real rclone obscure subprocess; the obscured value is irrelevant here.
        monkeypatch.setattr(archive, "_obscure", lambda config_path, secret: "OBSCURED")
        cfg_path = tmp_path / "rclone.conf"

        nas_ok, b2_ok = archive.write_rclone_config(self._settings(), cfg_path)
        assert nas_ok and b2_ok

        text = cfg_path.read_text()
        # [nas] is written before [b2], so everything before the [b2] header is the
        # NAS section and everything from it onward is the B2 section.
        b2_idx = text.index("[b2]")
        nas_section, b2_section = text[:b2_idx], text[b2_idx:]

        assert "no_check_bucket = true" in b2_section  # the fix
        assert "no_check_bucket" not in nas_section     # SMB has no bucket concept
        # the existing B2 fields are still present and unaffected
        assert "type = s3" in b2_section
        assert "access_key_id = K004keyid" in b2_section
