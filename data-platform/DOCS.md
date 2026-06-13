# Bluey Data Platform

## Installation

1. Add this repository to the Home Assistant add-on store
   (Settings > Add-ons > Add-on Store > top-right menu > Repositories), using
   `https://github.com/MightyArd/bluey-battery-data-app`.
2. Install the **Bluey Data Platform** add-on from the new entry.
3. Ensure the Mosquitto broker add-on is running (this add-on requires MQTT).
4. Start the add-on and check the log.

## Current behaviour (v0.5.2)

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

### Daily archive (v0.4.0)

Once a day, at `archive_time` (default 00:30 local), the add-on archives the
previous full local day:

1. Queries InfluxDB for every archived variable over the day.
2. Rolls each up to 5-minute resolution: mean for instantaneous quantities
   (power, SOC), last for cumulative kWh counters and categorical states; P5 and
   simulation values are taken as-is. Every 5-minute bucket is forward-filled, so
   sensors that sit flat (grid power in particular) leave no gaps.
3. Writes a Parquet file `energy_5min_YYYY-MM-DD.parquet` to `/data/archive/`.
4. Pushes it to the Synology NAS (SMB) and Backblaze B2 (S3 backend) with `rclone`,
   each verified after transfer by a downloaded-checksum comparison of the single
   uploaded file (the remote directory is checked with the file name included, so
   the comparison works on SMB, which has no server-side hash, as well as B2).
5. Publishes `sensor.bluey_data_platform_backup_nas_last_success` and
   `..._backup_cloud_last_success` timestamps, set only after a verified push.

Destinations are independent: if one fails (for example B2 is not yet configured)
the other still completes and reports, and the loop never crashes. The cloud leg is
skipped silently until the B2 options are set. Grid power is archived as separate
`grid_import_power` and `grid_export_power` columns, derived from the signed grid
meter. Grid energy is taken from the grid-meter counters
(`goodwe_meter_total_energy_import` and `_export`), which match the signed grid
power sensor, not the inverter-side or second-meter counters.

Battery round-trip-efficiency inputs are the cumulative lifetime counters
`goodwe_total_battery_charge` and `goodwe_total_battery_discharge` (not the
daily-reset `today_` counters), so RTE is computable from deltas over any
multi-day window. These are measured at the battery DC terminals, so the derived
RTE is the battery DC round-trip and excludes inverter conversion; full system
AC-to-AC RTE is not available from these sensors.

The `rclone` config is generated at runtime from the options below into
`/data/rclone.conf` (SMB passwords obscured); no secrets are committed. The file is
rewritten from the current options on every archive run, so it cannot go stale.

### B2 push diagnostics (v0.5.2)

When a B2 (cloud) destination is configured, each archive run logs a short
diagnostic block before the upload to help localise cloud-side failures (for
example an AccessDenied response): the key id, bucket, endpoint and destination
path; a non-revealing fingerprint of the secret key (length, first four and last
two characters, whitespace flag); the exact `rclone` copyto command; and the
`/data/rclone.conf` contents. Secrets are never logged in plaintext: the secret key
and the NAS password are always masked to `****`, and the secret key otherwise
appears only as the fingerprint. This is diagnostic logging only; it changes no
upload, verification, or path behaviour.

### Force backup button (v0.5.0)

The add-on publishes a momentary button,
`button.bluey_data_platform_run_archive` (friendly name "Force backup"), grouped
under the Bluey Data Platform device. Pressing it runs the same archive the daily
timer runs: rollup of the previous full local day, push to the NAS and B2,
checksum verification, and the backup-health timestamp updates. There is no new
archive logic; the press reuses the daily path as-is.

The press is handled safely. The MQTT callback only sets a thread-safe flag; the
archive itself runs in the main loop, never on the MQTT network thread, so a run
that takes several seconds cannot stall the heartbeat or trip an MQTT disconnect.
The single-threaded loop serialises manual and scheduled runs, so a press and the
03:00-ish daily timer can never run at the same time.

A press is purely additive: it does not change the daily-run bookkeeping, so it
neither skips the scheduled run nor is skipped because of it. A press while the
NAS is off (or `nas_share` is unset) completes the B2 leg and cleanly skips the
NAS leg, exactly like any other run. The press is logged distinctly from the
scheduled run (button pressed, manual run starting, manual run finished).

There is no option for the button; it is always present. The "press automatically
when the NAS comes back online" behaviour belongs in a Home Assistant automation,
not in this add-on.

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
| `soc_entity` | sensor.goodwe_battery_state_of_charge | HA entity for actual battery SOC |
| `solar_entity` | sensor.goodwe_pv_power_total | HA entity for solar generation |
| `reserve_load_entity` | sensor.goodwe_house_consumption | HA entity for house load |
| `usable_capacity_kwh` | 40.0 | Usable battery capacity |
| `max_charge_kw` | 6.5 | Maximum charge/discharge rate |
| `soc_hard_min` | 5 | % hard SOC floor (never discharged below this) |
| `soc_hard_max` | 100 | % hard SOC ceiling |
| `influxdb_token` | (empty) | InfluxDB API token; simulation uses actuals if set |
| `timezone` | Australia/Melbourne | IANA timezone for window evaluation |
| `archive_time` | 00:30 | Local time, HH:MM, for the daily archive run |
| `nas_host` | 192.168.50.214 | Synology SMB host |
| `nas_share` | (empty) | SMB share name; NAS push is skipped when empty |
| `nas_path` | energy-archive | Target folder within the share (also the B2 key prefix); may be left empty to write to the share root |
| `nas_user` | (empty) | SMB username |
| `nas_password` | (empty) | SMB password (obscured into /data/rclone.conf) |
| `b2_bucket` | (empty) | Backblaze B2 bucket; cloud push is skipped when empty |
| `b2_key_id` | (empty) | B2 application key id |
| `b2_key` | (empty) | B2 application key |
| `b2_endpoint` | (empty) | B2 S3 endpoint, e.g. s3.us-west-004.backblazeb2.com |

## Notes

- After deploy, add `sensor.bluey_data_platform_simulation_*` to the InfluxDB
  include globs in your Home Assistant InfluxDB integration configuration.
- The InfluxDB entity_id tag is the object_id (no domain prefix, e.g.
  `goodwe_house_consumption` not `sensor.goodwe_house_consumption`). Adjust the
  `soc_entity`, `solar_entity`, and `reserve_load_entity` options to match your
  InfluxDB schema if needed.
- This add-on's own published entities are logged by InfluxDB under
  `bluey_data_platform_*` (Home Assistant derives the entity_id from the device
  name plus the entity name). The archive reads the P5 price from the `value`
  field and the AEMO run id from the `run_id_str` field on
  `bluey_data_platform_p5_price_forecast`.
- `simulation_grid_signed` uses positive=import, negative=export, which is
  inverted relative to the GoodWe native sensor. The archive keeps this
  convention, matching `grid_import_power`/`grid_export_power`.