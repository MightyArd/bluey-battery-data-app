"""Unit tests for the battery dispatch simulation."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.simulator import SimParams, SettleResult, compute_reserve_floor, decide, settle

# Baseline params matching checkpoint defaults.
P = SimParams(
    charge_window_start_h=11, charge_window_start_m=0,
    charge_window_end_h=14, charge_window_end_m=0,
    export_window_start_h=18, export_window_start_m=0,
    export_window_end_h=21, export_window_end_m=0,
    reserve_target_soc=15.0,
    price_override_threshold=500.0,
    export_limit_w=500.0,
    usable_capacity_kwh=40.0,
    max_charge_kw=6.5,
    soc_hard_min=5.0,
    soc_hard_max=100.0,
    tz_name="Australia/Melbourne",
)


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 9, hour, minute)


class TestDecide:
    def test_price_override_discharges_above_hard_floor(self):
        mode = decide(
            soc=50.0, next_price=600.0, expected_solar_w=0.0, expected_load_w=1000.0,
            t=_t(15), params=P, reserve_floor_soc=40.0,
        )
        assert mode == "discharge"

    def test_price_override_blocked_at_hard_min(self):
        # SOC exactly at hard_min: price override must not trigger
        mode = decide(
            soc=5.0, next_price=600.0, expected_solar_w=0.0, expected_load_w=1000.0,
            t=_t(15), params=P, reserve_floor_soc=0.0,
        )
        assert mode != "discharge"

    def test_charge_window_charges_below_hard_max(self):
        mode = decide(
            soc=50.0, next_price=20.0, expected_solar_w=0.0, expected_load_w=1000.0,
            t=_t(12), params=P, reserve_floor_soc=30.0,
        )
        assert mode == "charge"

    def test_charge_window_idle_at_hard_max(self):
        mode = decide(
            soc=100.0, next_price=20.0, expected_solar_w=5000.0, expected_load_w=1000.0,
            t=_t(12), params=P, reserve_floor_soc=30.0,
        )
        assert mode == "idle"

    def test_export_window_discharges_above_floor(self):
        mode = decide(
            soc=60.0, next_price=20.0, expected_solar_w=0.0, expected_load_w=1000.0,
            t=_t(19), params=P, reserve_floor_soc=30.0,
        )
        assert mode == "discharge"

    def test_export_window_idle_at_floor(self):
        # SOC at or below reserve floor: no export
        mode = decide(
            soc=25.0, next_price=20.0, expected_solar_w=0.0, expected_load_w=1000.0,
            t=_t(19), params=P, reserve_floor_soc=30.0,
        )
        assert mode == "idle"

    def test_solar_surplus_charges_when_below_hard_max(self):
        mode = decide(
            soc=50.0, next_price=20.0, expected_solar_w=3000.0, expected_load_w=1000.0,
            t=_t(9), params=P, reserve_floor_soc=20.0,
        )
        assert mode == "charge"

    def test_solar_surplus_idle_when_full(self):
        mode = decide(
            soc=100.0, next_price=20.0, expected_solar_w=3000.0, expected_load_w=1000.0,
            t=_t(9), params=P, reserve_floor_soc=20.0,
        )
        assert mode == "idle"

    def test_shortfall_self_consume_above_floor(self):
        mode = decide(
            soc=50.0, next_price=20.0, expected_solar_w=500.0, expected_load_w=2000.0,
            t=_t(9), params=P, reserve_floor_soc=20.0,
        )
        assert mode == "self_consume"

    def test_shortfall_idle_at_floor(self):
        mode = decide(
            soc=20.0, next_price=20.0, expected_solar_w=500.0, expected_load_w=2000.0,
            t=_t(9), params=P, reserve_floor_soc=25.0,
        )
        assert mode == "idle"


class TestSettle:
    def test_charge_increases_soc(self):
        result = settle("charge", solar_w=0.0, load_w=1000.0, prior_soc=50.0, params=P)
        assert result.settled_mode == "charge"
        assert result.new_soc > 50.0

    def test_charge_clamps_at_hard_max(self):
        result = settle("charge", solar_w=0.0, load_w=1000.0, prior_soc=99.9, params=P)
        assert result.new_soc <= P.soc_hard_max

    def test_discharge_exports_to_grid(self):
        # Discharge with no solar: grid must be negative (exporting)
        result = settle("discharge", solar_w=0.0, load_w=1000.0, prior_soc=60.0, params=P)
        assert result.settled_mode == "discharge"
        assert result.grid_signed_w < 0.0

    def test_discharge_clamps_at_hard_min(self):
        result = settle("discharge", solar_w=0.0, load_w=1000.0, prior_soc=5.1, params=P)
        assert result.new_soc >= P.soc_hard_min

    def test_self_consume_covers_shortfall_grid_neutral(self):
        # Battery covers load - solar exactly: grid near zero
        result = settle("self_consume", solar_w=500.0, load_w=2000.0, prior_soc=50.0, params=P)
        assert result.settled_mode == "self_consume"
        assert result.grid_signed_w == pytest.approx(0.0, abs=10.0)

    def test_idle_no_battery_movement(self):
        result = settle("idle", solar_w=1000.0, load_w=1000.0, prior_soc=50.0, params=P)
        assert result.settled_mode == "idle"
        assert result.battery_power_w == pytest.approx(0.0, abs=1.0)
        assert result.new_soc == pytest.approx(50.0, abs=0.01)

    def test_grid_positive_when_importing(self):
        # Charge with no solar: must import from grid
        result = settle("charge", solar_w=0.0, load_w=1000.0, prior_soc=50.0, params=P)
        assert result.grid_signed_w > 0.0

    def test_price_override_stops_at_hard_floor(self):
        # Discharge from near-empty: SOC must not go below hard_min
        result = settle("discharge", solar_w=0.0, load_w=1000.0, prior_soc=5.2, params=P)
        assert result.new_soc >= P.soc_hard_min


class TestReserveFloor:
    def test_floor_equals_target_with_no_load(self):
        # Empty load profile: floor = reserve_target_soc exactly
        floor = compute_reserve_floor(_t(10, 55), {}, P)
        assert floor == pytest.approx(P.reserve_target_soc, abs=0.1)

    def test_floor_higher_at_midnight_with_constant_load(self):
        # 500 W constant load, midnight to 11:00 = 11 h
        # Energy = 11 * 60/5 * 500 * 5/60 / 1000 = 11 * 0.5 / 1 = 5.5 kWh
        # floor = 15 + 100 * 5.5 / 40 = 15 + 13.75 = 28.75%
        profile = {mod: 500.0 for mod in range(24 * 60)}
        floor = compute_reserve_floor(_t(0, 0), profile, P)
        assert floor == pytest.approx(28.75, abs=0.5)

    def test_floor_capped_at_hard_max(self):
        heavy = {mod: 100_000.0 for mod in range(24 * 60)}
        floor = compute_reserve_floor(_t(0), heavy, P)
        assert floor <= P.soc_hard_max