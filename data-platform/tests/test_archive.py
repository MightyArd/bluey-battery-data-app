"""Unit tests for the daily archive rollup, forward-fill, and naming logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.archive import (
    build_specs,
    daily_filename,
    day_bounds,
    partition_path,
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

    def test_filename_and_partition(self):
        d = date(2026, 6, 9)
        assert daily_filename(d) == "energy_5min_2026-06-09.parquet"
        assert partition_path(d) == "2026/06"
