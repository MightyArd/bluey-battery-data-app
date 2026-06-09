"""Battery dispatch simulation: settle + decide per tick."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

from .settings import Settings
from .state import SimState, load_state, save_state

log = logging.getLogger("bluey.simulator")


@dataclass(frozen=True)
class SimParams:
    charge_window_start_h: int
    charge_window_start_m: int
    charge_window_end_h: int
    charge_window_end_m: int
    export_window_start_h: int
    export_window_start_m: int
    export_window_end_h: int
    export_window_end_m: int
    reserve_target_soc: float
    price_override_threshold: float
    export_limit_w: float
    usable_capacity_kwh: float
    max_charge_kw: float
    soc_hard_min: float
    soc_hard_max: float
    tz_name: str


@dataclass
class SettleResult:
    settled_mode: str
    new_soc: float
    battery_power_w: float  # positive = charging, negative = discharging
    grid_signed_w: float    # positive = import, negative = export


def _in_window(t: datetime, sh: int, sm: int, eh: int, em: int) -> bool:
    current = t.hour * 60 + t.minute
    return (sh * 60 + sm) <= current < (eh * 60 + em)


def compute_reserve_floor(
    t: datetime,
    load_profile: dict[int, float],
    params: SimParams,
) -> float:
    """reserve_target_soc + 100 * expected_load_to_next_charge_start / usable_capacity."""
    charge_start = t.replace(
        hour=params.charge_window_start_h,
        minute=params.charge_window_start_m,
        second=0,
        microsecond=0,
    )
    if charge_start <= t:
        charge_start += timedelta(days=1)

    total_kwh = 0.0
    cursor = t.replace(second=0, microsecond=0)
    while cursor < charge_start:
        mod = cursor.hour * 60 + cursor.minute
        total_kwh += load_profile.get(mod, 0.0) * (5.0 / 60.0) / 1000.0
        cursor += timedelta(minutes=5)

    floor = params.reserve_target_soc + 100.0 * total_kwh / params.usable_capacity_kwh
    return min(floor, params.soc_hard_max)


def settle(
    planned_mode: str,
    solar_w: float,
    load_w: float,
    prior_soc: float,
    params: SimParams,
) -> SettleResult:
    """Settle a closed 5-minute period using the planned mode and actual solar/load."""
    if planned_mode == "charge":
        battery_power = params.max_charge_kw * 1000.0
    elif planned_mode == "discharge":
        needed = params.export_limit_w + max(0.0, load_w - solar_w)
        battery_power = -min(needed, params.max_charge_kw * 1000.0)
    elif planned_mode == "self_consume":
        shortfall = max(0.0, load_w - solar_w)
        battery_power = -min(shortfall, params.max_charge_kw * 1000.0)
    else:
        battery_power = 0.0

    # Clamp by available SOC headroom (enforces hard SOC limits)
    if battery_power > 0.0:
        headroom_kwh = (params.soc_hard_max - prior_soc) / 100.0 * params.usable_capacity_kwh
        battery_power = max(0.0, min(battery_power, headroom_kwh / (5.0 / 60.0) * 1000.0))
    elif battery_power < 0.0:
        available_kwh = (prior_soc - params.soc_hard_min) / 100.0 * params.usable_capacity_kwh
        battery_power = min(0.0, max(battery_power, -(available_kwh / (5.0 / 60.0) * 1000.0)))

    if battery_power > 50.0:
        settled_mode = "charge"
    elif battery_power < -50.0:
        settled_mode = "discharge" if planned_mode == "discharge" else "self_consume"
    else:
        settled_mode = "idle"

    energy_kwh = battery_power * (5.0 / 60.0) / 1000.0
    new_soc = max(
        params.soc_hard_min,
        min(params.soc_hard_max, prior_soc + energy_kwh / params.usable_capacity_kwh * 100.0),
    )
    # Power balance: solar + grid_import = load + battery_charging
    # => grid_import (positive=import) = load - solar + battery_power
    # Note: this is inverted relative to the GoodWe native sensor (negative=import).
    grid_signed_w = load_w - solar_w + battery_power

    return SettleResult(
        settled_mode=settled_mode,
        new_soc=new_soc,
        battery_power_w=battery_power,
        grid_signed_w=grid_signed_w,
    )


def decide(
    soc: float,
    next_price: float,
    expected_solar_w: float,
    expected_load_w: float,
    t: datetime,
    params: SimParams,
    reserve_floor_soc: float,
) -> str:
    """Decide the mode for the upcoming 5-minute period.

    Precedence: price override > charge window > export window > baseline.
    Hard SOC limits are enforced implicitly in each branch.
    """
    # Price override: breaches reserve floor but stops at hard floor
    if next_price >= params.price_override_threshold and soc > params.soc_hard_min:
        return "discharge"

    above_floor = soc > reserve_floor_soc

    # Charge window: fill toward hard_max from solar then grid
    if _in_window(t, params.charge_window_start_h, params.charge_window_start_m,
                  params.charge_window_end_h, params.charge_window_end_m):
        if soc < params.soc_hard_max:
            return "charge"

    # Export window: only when above reserve floor
    if _in_window(t, params.export_window_start_h, params.export_window_start_m,
                  params.export_window_end_h, params.export_window_end_m):
        if above_floor:
            return "discharge"

    # Baseline: solar-priority self-consumption
    surplus = expected_solar_w - expected_load_w
    if surplus > 0.0:
        return "charge" if soc < params.soc_hard_max else "idle"
    return "self_consume" if above_floor else "idle"


def _params_from_settings(s: Settings) -> SimParams:
    return SimParams(
        charge_window_start_h=s.charge_window_start_h,
        charge_window_start_m=s.charge_window_start_m,
        charge_window_end_h=s.charge_window_end_h,
        charge_window_end_m=s.charge_window_end_m,
        export_window_start_h=s.export_window_start_h,
        export_window_start_m=s.export_window_start_m,
        export_window_end_h=s.export_window_end_h,
        export_window_end_m=s.export_window_end_m,
        reserve_target_soc=float(s.reserve_target_soc),
        price_override_threshold=float(s.price_override_threshold),
        export_limit_w=float(s.export_limit_w),
        usable_capacity_kwh=float(s.usable_capacity_kwh),
        max_charge_kw=float(s.max_charge_kw),
        soc_hard_min=float(s.soc_hard_min),
        soc_hard_max=float(s.soc_hard_max),
        tz_name=s.timezone,
    )


def run_step(
    client: mqtt.Client,
    settings: Settings,
    last_p5_rrp: float | None,
) -> None:
    """Run one simulation tick: settle the closed period, then decide the next one."""
    from . import publisher, sources  # lazy: avoids paho dep during unit tests

    params = _params_from_settings(settings)
    tz = ZoneInfo(params.tz_name)
    state = load_state(settings.data_dir)

    if state is None:
        # Cold start: seed simulated SOC from the actual battery SOC
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        actual_soc = sources.read_soc(settings.soc_entity, token)
        if actual_soc is None:
            log.warning("Cold start: SOC unavailable, seeding at 50%%")
            actual_soc = 50.0
        state = SimState(simulated_soc=actual_soc, pending_planned_mode=None, last_settled_dt=None)
        log.info("Simulation cold start: seeded SOC=%.1f%%", actual_soc)
    elif state.pending_planned_mode is not None:
        # Settle the period that just closed (align to most recent 5-min boundary)
        now_utc = datetime.now(timezone.utc)
        boundary_ts = (now_utc.timestamp() // 300) * 300
        period_end = datetime.fromtimestamp(boundary_ts, tz=timezone.utc)
        period_start = period_end - timedelta(minutes=5)

        solar_w, load_w = sources.read_period_actuals(
            settings.influxdb_token,
            settings.solar_entity,
            settings.reserve_load_entity,
            period_start,
            period_end,
        )
        result = settle(state.pending_planned_mode, solar_w, load_w, state.simulated_soc, params)
        publisher.publish_simulation_settled(client, result)
        state.simulated_soc = result.new_soc
        log.info(
            "Settled: planned=%s settled=%s soc=%.1f%% solar=%.0fW load=%.0fW grid=%.0fW",
            state.pending_planned_mode, result.settled_mode, result.new_soc,
            solar_w, load_w, result.grid_signed_w,
        )

    # Load profile for reserve floor and expected load/solar in the decide step
    load_profile, solar_profile = sources.read_load_profile(
        settings.influxdb_token,
        settings.reserve_load_entity,
        settings.solar_entity,
        params.tz_name,
    )

    t_local = datetime.now(tz=tz).replace(tzinfo=None)
    mod = t_local.hour * 60 + t_local.minute
    expected_load = load_profile.get(mod, 500.0)
    expected_solar = solar_profile.get(mod, 0.0)
    reserve_floor = compute_reserve_floor(t_local, load_profile, params)
    next_price = last_p5_rrp if last_p5_rrp is not None else 0.0

    mode = decide(
        state.simulated_soc, next_price, expected_solar, expected_load,
        t_local, params, reserve_floor,
    )
    publisher.publish_simulation_planned(client, mode)

    state.pending_planned_mode = mode
    state.last_settled_dt = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    save_state(settings.data_dir, state)

    log.info(
        "Decided: mode=%s soc=%.1f%% floor=%.1f%% price=%.2f solar=%.0fW load=%.0fW",
        mode, state.simulated_soc, reserve_floor, next_price, expected_solar, expected_load,
    )