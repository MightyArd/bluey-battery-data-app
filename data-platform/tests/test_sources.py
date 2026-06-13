"""Unit tests for the simulation InfluxDB query builders.

The defect: the simulation reads aggregated without filtering to the numeric value
field, so mean() / aggregateWindow(fn: mean) hit a string attribute column and
errored ("mean: unsupported aggregate column type string"), leaving the simulation
on solar=0W, load=0W. Both query builders must restrict to _field == "value". These
assert on the query text, so no InfluxDB client or network is needed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.sources import _mean_query, _profile_query


def _utc(h: int, mi: int) -> datetime:
    return datetime(2026, 6, 12, h, mi, tzinfo=timezone.utc)


class TestMeanQuery:
    def test_filters_to_value_field(self):
        q = _mean_query("goodwe_pv_power_total", _utc(0, 0), _utc(0, 5))
        assert 'r["_field"] == "value"' in q

    def test_still_filters_entity_and_aggregates_mean(self):
        q = _mean_query("goodwe_pv_power_total", _utc(0, 0), _utc(0, 5))
        assert 'r["entity_id"] == "goodwe_pv_power_total"' in q
        assert "|> mean()" in q
        assert "fill(usePrevious: true)" in q

    def test_value_filter_is_anded_with_entity_filter(self):
        # A single filter() ANDs both predicates, so the string fields are excluded
        # before mean() runs.
        q = _mean_query("x", _utc(0, 0), _utc(0, 5))
        assert 'r["entity_id"] == "x" and r["_field"] == "value"' in q


class TestProfileQuery:
    def test_filters_to_value_field(self):
        q = _profile_query("goodwe_house_consumption", 7)
        assert 'r["_field"] == "value"' in q

    def test_aggregate_window_mean_over_trailing_days(self):
        q = _profile_query("goodwe_house_consumption", 7)
        assert "range(start: -7d)" in q
        assert "aggregateWindow(every: 5m, fn: mean, createEmpty: false)" in q

    def test_value_filter_is_anded_with_entity_filter(self):
        q = _profile_query("y", 7)
        assert 'r["entity_id"] == "y" and r["_field"] == "value"' in q
