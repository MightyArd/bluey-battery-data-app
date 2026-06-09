# Bluey Data Platform

## Installation

1. Add this repository to the Home Assistant add-on store
   (Settings > Add-ons > Add-on Store > top-right menu > Repositories), using
   `https://github.com/MightyArd/bluey-battery-data-app`.
2. Install the **Bluey Data Platform** add-on from the new entry.
3. Ensure the Mosquitto broker add-on is running (this add-on requires MQTT).
4. Start the add-on and check the log.

## Current behaviour (v0.3.0)

Every 5 minutes (aligned to AEMO dispatch boundaries, +2 min offset):

1. Fetches the latest P5MIN predispatch ZIP from NEMWeb and publishes
   `sensor.bluey_data_platform_p5_price_forecast` (VIC1 5-min-ahead RRP).
2. Runs the shadow battery dispatch simulation:
   - **Settle**: reads actual solar and load from InfluxDB for the period that
     just closed, applies the planned mode from the previous tick, and computes
     the realised SOC, settled mode, and grid power. Publishes
     `simulation_settled_mode` and `simulation_grid_signed`.
   - **Decide**: loads the 7-day trailing load/solar profile from InfluxDB,
     computes the dynamic reserve floor, and selects the planned mode for the
     upcoming period (charge, discharge, self_consume, or idle). Publishes
     `simulation_planned_mode` and `simulation_soc`.
   - Shadow-mode only: the simulation computes and logs; it never actuates
     the battery or inverter.

### Simulation modes

- `charge`: battery charging from solar surplus then grid, up to hard SOC max.
- `discharge`: exporting to grid at the configured limit while covering load.
- `self_consume`: battery covering load shortfall below solar, down to reserve floor.
- `idle`: battery inactive; solar exports directly and/or grid covers load.

### Decision precedence

1. Price override: if the next P5 price exceeds the threshold, discharge to
   the hard SOC floor regardless of the reserve floor.
2. Charge window (default 11:00-14:00): charge to hard SOC max.
3. Export window (default 18:00-21:00): discharge if above the reserve floor.
4. Baseline: solar-priority; charge from surplus, self-consume from shortfall
   down to the reserve floor, idle otherwise.

### Dynamic reserve floor

```
reserve_floor_soc = reserve_target_soc
    + 100 * expected_load_kWh(now -> next 11:00) / usable_capacity_kWh
```

Derived from the trailing 7-day load average by time-of-day.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `log_level` | info | trace/debug/info/notice/warning/error/fatal |
| `charge_window_start` | 11:00 | Local time, HH:MM |
| `charge_window_end` | 14:00 | Local time, HH:MM |
| `export_window_start` | 18:00 | Local time, HH:MM |
| `export_window_end` | 21:00 | Local time, HH:MM |
| `reserve_target_soc` | 15 | % SOC to hold at the start of each charge window |
| `price_override_threshold` | 500 | $/MWh above which the battery exports |
| `export_limit_w` | 500 | W maximum grid export (DNSP cap) |
| `soc_entity` | sensor.goodwe_battery_soc | HA entity for actual battery SOC |
| `solar_entity` | sensor.goodwe_pv_power_total | HA entity for solar generation |
| `reserve_load_entity` | sensor.goodwe_house_consumption | HA entity for house load |
| `usable_capacity_kwh` | 40.0 | Usable battery capacity |
| `max_charge_kw` | 6.5 | Maximum charge/discharge rate |
| `soc_hard_min` | 5 | % hard SOC floor (never discharged below this) |
| `soc_hard_max` | 100 | % hard SOC ceiling |
| `influxdb_token` | (empty) | InfluxDB API token; simulation uses actuals if set |
| `timezone` | Australia/Melbourne | IANA timezone for window evaluation |

## Notes

- After deploy, add `sensor.bluey_data_platform_simulation_*` to the InfluxDB
  include globs in your Home Assistant InfluxDB integration configuration.
- The InfluxDB entity_id tag is assumed to be the object_id (no domain prefix,
  e.g. `goodwe_house_consumption` not `sensor.goodwe_house_consumption`). Adjust
  the `soc_entity`, `solar_entity`, and `reserve_load_entity` options to match
  your InfluxDB schema if needed.
- `simulation_grid_signed` uses positive=import, negative=export. This is
  inverted relative to the GoodWe native sensor. Verify and align when building
  the archive increment.