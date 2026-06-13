"""Daily archive: roll up the previous local day to a 5-minute Parquet file and
push it to the Synology NAS and Backblaze B2, each verified by checksum.

The rollup functions are pure (no InfluxDB, no Polars, no rclone) so they are unit
tested directly. Polars is imported lazily only when a Parquet file is written, and
rclone is shelled out only when a file is pushed. The app reads InfluxDB and writes
Parquet plus runs rclone; it never writes to InfluxDB.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    import paho.mqtt.client as mqtt

    from .settings import Settings

log = logging.getLogger("bluey.archive")

BUCKET = timedelta(minutes=5)

Agg = Literal["mean", "last"]
Value = float | str  # numeric sensors arrive as float, categorical states as str


@dataclass(frozen=True)
class VarSpec:
    """One archived column: the output name, its InfluxDB source, and the rollup."""

    column: str
    entity_id: str  # object_id as stored in InfluxDB (no domain prefix)
    agg: Agg
    field: str = "value"


# Default archive variable set. The object_ids that are confirmed in CLAUDE.md
# (goodwe_*, the simulation and P5 app entities) are used as-is; the remaining
# logical names (grid split, ev, non-ev, the split energy counters) are best-effort
# defaults that must be confirmed against the real InfluxDB entity_id tags on Bluey.
# Correcting one is a single-line edit here. The grid import/export *power* columns
# are derived from the signed grid meter (see GRID_SIGNED_ENTITY), not read directly.
GRID_SIGNED_ENTITY = "goodwe_meter_active_power_total"  # negative = import, positive = export

MEASURED_SPECS: tuple[VarSpec, ...] = (
    # Power, mean
    VarSpec("battery_signed_power", "battery_signed_power", "mean"),
    VarSpec("goodwe_pv_power_total", "goodwe_pv_power_total", "mean"),
    VarSpec("goodwe_house_consumption", "goodwe_house_consumption", "mean"),
    VarSpec("ev_power", "ev_power", "mean"),
    VarSpec("non_ev_load_power", "non_ev_load_power", "mean"),
    # SOC, mean
    VarSpec("battery_soc", "goodwe_battery_state_of_charge", "mean"),
    # Categorical, last
    VarSpec("goodwe_battery_mode", "goodwe_battery_mode", "last"),
    # Energy counters, last (import and export kept split, never netted). Grid energy
    # uses the grid-meter counters that match goodwe_meter_active_power_total, NOT the
    # inverter-side goodwe_total_energy_* nor the second meter (goodwe_meter_2_*).
    VarSpec("grid_import_energy", "goodwe_meter_total_energy_import", "last"),
    VarSpec("grid_export_energy", "goodwe_meter_total_energy_export", "last"),
    VarSpec("goodwe_total_load", "goodwe_total_load", "last"),
    VarSpec("goodwe_total_pv_generation", "goodwe_total_pv_generation", "last"),
    VarSpec("ev_energy_shelly_total", "ev_energy_shelly_total", "last"),
    VarSpec("non_ev_load_energy_total", "non_ev_load_energy_total", "last"),
    # Battery round-trip-efficiency inputs: cumulative LIFETIME counters (not the
    # daily-reset goodwe_today_* ones), so RTE is computable from deltas over any
    # multi-day window. These are measured at the battery DC terminals, so the
    # derived RTE is the battery DC round-trip and excludes inverter conversion;
    # full system AC-to-AC RTE is not available from these sensors.
    VarSpec("goodwe_total_battery_charge", "goodwe_total_battery_charge", "last"),
    VarSpec("goodwe_total_battery_discharge", "goodwe_total_battery_discharge", "last"),
)

# App entities (published by this add-on via MQTT discovery). HA derives the
# InfluxDB entity_id from the device name plus the entity name, so every app entity
# is prefixed bluey_data_platform_ (for example the P5 sensor is
# bluey_data_platform_p5_price_forecast). For the P5 sensor the price is the state
# (the "value" field); the AEMO RUN_DATETIME string is logged as the run_id_str field.
APP_SPECS: tuple[VarSpec, ...] = (
    VarSpec("p5_price_forecast", "bluey_data_platform_p5_price_forecast", "last"),
    VarSpec("p5_run_id", "bluey_data_platform_p5_price_forecast", "last", field="run_id_str"),
    VarSpec("simulation_soc", "bluey_data_platform_simulation_soc", "mean"),
    VarSpec("simulation_planned_mode", "bluey_data_platform_simulation_planned_mode", "last"),
    VarSpec("simulation_settled_mode", "bluey_data_platform_simulation_settled_mode", "last"),
    VarSpec("simulation_grid_signed", "bluey_data_platform_simulation_grid_signed", "mean"),
)


def build_specs() -> list[VarSpec]:
    """Assemble the full archive column spec (measured + battery RTE + app entities)."""
    return list(MEASURED_SPECS) + list(APP_SPECS)


def day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """UTC [start, stop) instants spanning one full local day (local midnight to next)."""
    tz = ZoneInfo(tz_name)
    start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
    stop_local = start_local + timedelta(days=1)  # next local midnight
    return start_local.astimezone(timezone.utc), stop_local.astimezone(timezone.utc)


def time_buckets(start_utc: datetime, stop_utc: datetime) -> list[datetime]:
    """5-minute bucket start instants (UTC) covering [start, stop)."""
    buckets: list[datetime] = []
    cursor = start_utc
    while cursor < stop_utc:
        buckets.append(cursor)
        cursor += BUCKET
    return buckets


def rollup_series(
    records: list[tuple[datetime, Value]],
    buckets: list[datetime],
    agg: Agg,
) -> list[Value | None]:
    """Roll raw points into one value per 5-minute bucket, forward-filling gaps.

    `records` is time-sorted and may include a single seed point before the first
    bucket. For each bucket: `mean` averages the points whose timestamp falls in
    [bucket_start, bucket_start + 5min); `last` takes the final such point. An empty
    bucket carries the last known value forward (this is what keeps flat sensors,
    such as grid power sitting at zero, from leaving gaps). A bucket with no value
    yet seen stays None.
    """
    out: list[Value | None] = []
    carry: Value | None = None
    i = 0
    n = len(records)
    for b_start in buckets:
        b_end = b_start + BUCKET
        in_bucket: list[Value] = []
        while i < n and records[i][0] < b_end:
            ts, val = records[i]
            if ts >= b_start:
                in_bucket.append(val)
            carry = val  # last known value advances over every consumed point
            i += 1
        if in_bucket:
            if agg == "mean":
                nums = [float(v) for v in in_bucket]
                out.append(sum(nums) / len(nums))
            else:
                out.append(in_bucket[-1])
        else:
            out.append(carry)
    return out


def split_grid_power(
    signed_records: list[tuple[datetime, Value]],
) -> tuple[list[tuple[datetime, Value]], list[tuple[datetime, Value]]]:
    """Split a signed grid meter series into (import, export) magnitude series.

    Convention from CLAUDE.md: negative = import, positive = export. Both are
    returned as non-negative magnitudes so a window that swings between directions
    keeps a sensible mean in each column.
    """
    imp: list[tuple[datetime, Value]] = []
    exp: list[tuple[datetime, Value]] = []
    for ts, v in signed_records:
        x = float(v)
        imp.append((ts, max(0.0, -x)))
        exp.append((ts, max(0.0, x)))
    return imp, exp


def daily_filename(day: date) -> str:
    return f"energy_5min_{day.isoformat()}.parquet"


def partition_path(day: date) -> str:
    """Year/month partition for the destination, e.g. 2026/06."""
    return f"{day.year:04d}/{day.month:02d}"


def write_parquet(
    path: Path,
    buckets: list[datetime],
    columns: dict[str, list[Value | None]],
    tz_name: str,
) -> None:
    """Write the rolled-up columns to Parquet (pyarrow engine via Polars).

    Adds ts_utc (the canonical instant) and ts_local (local wall clock) timestamp
    columns ahead of the data columns.
    """
    import polars as pl  # lazy: keeps the unit tests free of the Polars dependency

    tz = ZoneInfo(tz_name)
    data: dict[str, list[Any]] = {
        "ts_utc": list(buckets),
        "ts_local": [b.astimezone(tz).replace(tzinfo=None) for b in buckets],
    }
    data.update(columns)
    df = pl.DataFrame(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)


# --------------------------------------------------------------------------- #
# Orchestration (InfluxDB reads, Parquet write, dual rclone push, health).
# --------------------------------------------------------------------------- #


def build_day_parquet(settings: "Settings", day: date, out_dir: Path) -> tuple[Path, list[VarSpec]]:
    """Read the day's series from InfluxDB, roll them up, and write the Parquet file.

    Returns (parquet_path, specs_used). Raises if the token is unset (no data to read).
    """
    from . import sources

    if not settings.influxdb_token:
        raise RuntimeError("influxdb_token is not set; cannot read the day's data")

    start_utc, stop_utc = day_bounds(day, settings.timezone)
    buckets = time_buckets(start_utc, stop_utc)

    specs = build_specs()

    columns: dict[str, list[Value | None]] = {}

    # Derived grid import/export power from the signed grid meter.
    signed = sources.read_raw_series(settings.influxdb_token, GRID_SIGNED_ENTITY, start_utc, stop_utc)
    imp, exp = split_grid_power(signed)
    columns["grid_import_power"] = rollup_series(imp, buckets, "mean")
    columns["grid_export_power"] = rollup_series(exp, buckets, "mean")

    for spec in specs:
        records = sources.read_raw_series(
            settings.influxdb_token, spec.entity_id, start_utc, stop_utc, field=spec.field
        )
        columns[spec.column] = rollup_series(records, buckets, spec.agg)

    path = out_dir / daily_filename(day)
    write_parquet(path, buckets, columns, settings.timezone)
    log.info("Wrote %s (%d rows, %d columns)", path, len(buckets), len(columns) + 2)
    return path, specs


def _rclone(args: list[str], config_path: Path) -> bool:
    """Run rclone with the given args; return True on exit code 0."""
    try:
        proc = subprocess.run(
            ["rclone", "--config", str(config_path), *args],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except Exception as exc:
        log.error("rclone invocation failed (%s): %s", args[0] if args else "?", exc)
        return False
    if proc.returncode != 0:
        log.error("rclone %s failed: %s", args[0] if args else "?", proc.stderr.strip())
        return False
    return True


def _obscure(config_path: Path, secret: str) -> str:
    """Obscure a password for the rclone config (SMB requires this)."""
    try:
        proc = subprocess.run(
            ["rclone", "--config", str(config_path), "obscure", secret],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception as exc:
        log.error("rclone obscure failed: %s", exc)
    return ""


def write_rclone_config(settings: "Settings", config_path: Path) -> tuple[bool, bool]:
    """Write /data/rclone.conf from options. Returns (nas_configured, b2_configured).

    Secrets come only from add-on options and are written to the persistent volume,
    never committed.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []

    nas_ok = bool(settings.nas_share and settings.nas_user and settings.nas_password)
    if nas_ok:
        obscured = _obscure(config_path, settings.nas_password)
        sections.append(
            "[nas]\n"
            "type = smb\n"
            f"host = {settings.nas_host}\n"
            f"user = {settings.nas_user}\n"
            f"pass = {obscured}\n"
        )

    b2_ok = bool(settings.b2_bucket and settings.b2_key_id and settings.b2_key and settings.b2_endpoint)
    if b2_ok:
        sections.append(
            "[b2]\n"
            "type = s3\n"
            "provider = Other\n"
            f"access_key_id = {settings.b2_key_id}\n"
            f"secret_access_key = {settings.b2_key}\n"
            f"endpoint = {settings.b2_endpoint}\n"
        )

    config_path.write_text("\n".join(sections))
    return nas_ok, b2_ok


def push_verified(local_path: Path, remote: str, config_path: Path) -> bool:
    """Copy one file to a remote and verify it by checksum.

    `remote` is a full rclone destination directory, e.g. "nas:share/energy-archive/2026/06"
    or "b2:bucket/energy-archive/2026/06". Verification downloads the remote copy and
    compares its hash to the local file, which works for every backend including SMB
    (which has no server-side hash).
    """
    dest_file = f"{remote}/{local_path.name}"
    if not _rclone(["copyto", str(local_path), dest_file], config_path):
        return False
    # --download compares byte hashes; --one-way ignores extra files at the remote.
    if not _rclone(
        ["check", "--one-way", "--download", str(local_path), dest_file], config_path
    ):
        log.error("Checksum verification failed for %s", dest_file)
        return False
    log.info("Pushed and verified %s", dest_file)
    return True


def run_archive(client: "mqtt.Client", settings: "Settings", day: date | None = None) -> None:
    """Run the daily archive for `day` (defaults to yesterday, local time).

    Builds the Parquet, then pushes to the NAS and B2 independently. A failure of
    one destination still attempts the other and reports; the loop is never crashed.
    Health timestamps are published only after a verified push.
    """
    from . import publisher

    if day is None:
        tz = ZoneInfo(settings.timezone)
        day = (datetime.now(tz) - timedelta(days=1)).date()

    log.info("Daily archive starting for %s", day.isoformat())

    staging = Path(settings.data_dir) / "archive"
    try:
        parquet_path, _ = build_day_parquet(settings, day, staging)
    except Exception as exc:
        log.error("Archive build failed for %s: %s", day, exc, exc_info=True)
        return

    config_path = Path(settings.data_dir) / "rclone.conf"
    nas_ok, b2_ok = write_rclone_config(settings, config_path)
    part = partition_path(day)

    if nas_ok:
        remote = f"nas:{settings.nas_share}/{settings.nas_path}/{part}"
        try:
            if push_verified(parquet_path, remote, config_path):
                publisher.publish_backup_health(client, "nas", _now_iso(settings))
        except Exception as exc:
            log.error("NAS push errored: %s", exc, exc_info=True)
    else:
        log.warning("NAS destination not configured; skipping NAS push")

    if b2_ok:
        remote = f"b2:{settings.b2_bucket}/{settings.nas_path}/{part}"
        try:
            if push_verified(parquet_path, remote, config_path):
                publisher.publish_backup_health(client, "cloud", _now_iso(settings))
        except Exception as exc:
            log.error("B2 push errored: %s", exc, exc_info=True)
    else:
        log.info("B2 destination not configured; skipping cloud push (NAS leg still runs)")

    log.info("Daily archive complete for %s", day.isoformat())


def _now_iso(settings: "Settings") -> str:
    return datetime.now(ZoneInfo(settings.timezone)).isoformat()
