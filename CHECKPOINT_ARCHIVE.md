# Checkpoint: Daily archive to Synology and cloud (v0.4.0)

Read `CLAUDE.md` first. This file is the contract for this increment. It is the
final planned increment. Stop and report at the end.

## Objective

Add the once-a-day archive: query InfluxDB for the previous day, roll up to
5-minute resolution, write Parquet, push the file to the Synology and to
Backblaze B2 with checksum verification, and publish a health timestamp per
destination. Push from Bluey to both destinations directly, so each link is
verified at the origin.

## In scope

- `app/archive.py`: the daily rollup query, Parquet write, dual `rclone` push with
  verification, and health publishing.
- `app/sources.py`: extend with the daily rollup read (InfluxDB, forward-filled).
- `app/settings.py`: add the archive and destination options.
- `app/publisher.py`: extend with discovery for the two backup-health sensors.
- `app/main.py`: add a daily timer that runs the archive (separate from the
  5-minute loop).
- `tests/`: unit tests for the rollup (mean vs last, forward-fill) and the
  filename/partition logic.
- Bump version to 0.4.0; update `DOCS.md` and `CHANGELOG.md`.

## Out of scope

Nothing further. This completes the platform.

## Daily run

- A daily timer at a configurable time (default 00:30 local) queries the previous
  full local day.
- On a destination failure, still complete the other destination and report.
  Never crash the loop.

## Rollup rules

- Mean for instantaneous quantities (power, SOC, temperature).
- Last for cumulative kWh counters and categorical states.
- P5 and simulation values are 5-minute-native; take them as-is.
- Forward-fill across empty 5-minute windows. HA logs only on state change, so a
  sensor flat at a constant value is sparse; every 5-minute bucket must carry the
  last known value, not a gap. This is essential, the grid power sensors in
  particular sit flat at zero for long periods.

## Variables to archive

Measured (existing HA entities):

- Power (mean): `grid_import_power`, `grid_export_power` (stored as separate
  variables, because a window can contain both directions), `battery_signed_power`,
  `goodwe_pv_power_total`, `goodwe_house_consumption`, `ev_power`,
  `non_ev_load_power`.
- SOC (mean) and `goodwe_battery_mode` (last).
- Energy counters (last): grid import energy, grid export energy (kept split),
  `goodwe_total_load`, PV generation, `ev_energy_shelly_total`,
  `non_ev_load_energy_total`.
- Round-trip efficiency inputs: detect battery charge-energy and
  discharge-energy counters in the `kWh` measurement (entity_id query). If they
  exist, include them (last). If they do not, note their absence in the report;
  do not synthesise them.

App entities (namespaced `sensor.bluey_data_platform_*`):

- `p5_price_forecast` (last) and its `run_id` attribute.
- `simulation_soc` (mean), `simulation_planned_mode` (last),
  `simulation_settled_mode` (last), `simulation_grid_signed` (mean).

## Destinations

Push the daily Parquet to both, each verified by checksum after transfer, using
`rclone` with two remotes configured from add-on options (never committed):

- Synology over SMB. Host `192.168.50.214` (server DiskStationNAS). The share or
  folder, SMB username and password come from options. Suggested target folder:
  `energy-archive`.
- Backblaze B2 (S3-compatible). Bucket, application key id and key, and endpoint
  come from options. The cloud leg is skipped gracefully if B2 options are
  unset, so the NAS leg works before B2 is created.

## Health monitoring

- Publish `sensor.bluey_data_platform_backup_nas_last_success` and
  `sensor.bluey_data_platform_backup_cloud_last_success` as timestamps, set only
  after a verified push.
- The staleness alert itself is a small HA automation the user adds (notify if
  either timestamp is older than ~26 hours); the app's job is to publish the
  timestamps truthfully.

## Constraints

InfluxDB reads only; the app writes Parquet files and runs `rclone`, never writes
to InfluxDB. Forward-fill all reads. Secrets only via options, never committed.
Australian English, no em dashes. Follow `CLAUDE.md`.

## Acceptance criteria

- pytest green. Cover: mean-versus-last per variable type; forward-fill produces a
  value in every 5-minute bucket including across flat periods; the RTE counters
  are included when present and cleanly omitted when absent.
- A manual run produces a dated Parquet for a chosen day containing all the
  variables above at 5-minute resolution, with no gaps from flat sensors.
- Both pushes succeed and verify by checksum; the two health timestamps update.
- Failing one destination (for example B2 not yet configured) still completes the
  other and reports it, without crashing.

## Setup actions for the user (outside this repo)

- Set the InfluxDB `home_assistant` bucket retention to 30 days.
- Create the B2 bucket and an application key; put them in the add-on options.
- Create or choose the NAS share/folder and an SMB user; put the share path and
  credentials in the add-on options.
- Confirm the InfluxDB include globs cover every archived entity, including
  `sensor.bluey_data_platform_*`.
- Add the staleness alert automation in HA.

## Stop and report

1. Summary of what was built.
2. Files added or changed.
3. Decisions and assumptions made (for example the RTE counter names found or not
   found, the Parquet schema and partitioning, the rollup time zone). Log them.
4. How it was verified (tests plus a manual run for a real day).
5. Open questions.
6. Risks and limitations.
7. Recommended next step.

Note: this increment changes the measured grid storage from a single signed value
to separate `grid_import_power` and `grid_export_power`. Update `CLAUDE.md`'s data
scope to match (it currently lists `grid_signed_power`).
