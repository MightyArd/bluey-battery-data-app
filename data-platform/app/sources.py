"""External data sources: HA Supervisor API and InfluxDB."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("bluey.sources")

_HA_API = "http://supervisor/core/api"
_INFLUX_URL = "http://ec9cbdb7-influxdb2:8086"
_INFLUX_ORG = "home"
_INFLUX_BUCKET = "home_assistant"


def _object_id(entity_id: str) -> str:
    """Strip domain prefix: sensor.foo -> foo (matches HA InfluxDB default storage)."""
    return entity_id.split(".", 1)[-1]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_soc(soc_entity: str, supervisor_token: str) -> float | None:
    """Read current actual SOC (%) from the HA Supervisor API."""
    try:
        resp = requests.get(
            f"{_HA_API}/states/{soc_entity}",
            headers={"Authorization": f"Bearer {supervisor_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return float(resp.json()["state"])
    except Exception as exc:
        log.warning("Failed to read SOC (%s): %s", soc_entity, exc)
        return None


def _flux_mean(
    influx_token: str,
    entity_id: str,
    start: datetime,
    stop: datetime,
) -> float | None:
    """Mean value of an HA entity over a UTC time window, with forward-fill."""
    from influxdb_client import InfluxDBClient  # type: ignore[import]

    oid = _object_id(entity_id)
    q = (
        f'from(bucket: "{_INFLUX_BUCKET}")'
        f'  |> range(start: {start.strftime("%Y-%m-%dT%H:%M:%SZ")},'
        f'            stop:  {stop.strftime("%Y-%m-%dT%H:%M:%SZ")})'
        f'  |> filter(fn: (r) => r["entity_id"] == "{oid}")'
        f'  |> fill(usePrevious: true)'
        f'  |> mean()'
    )
    try:
        with InfluxDBClient(url=_INFLUX_URL, token=influx_token, org=_INFLUX_ORG) as c:
            for table in c.query_api().query(q):
                for rec in table.records:
                    v = rec.get_value()
                    if v is not None:
                        return float(v)
    except Exception as exc:
        log.warning("InfluxDB mean failed (%s): %s", entity_id, exc)
    return None


def read_period_actuals(
    influx_token: str,
    solar_entity: str,
    load_entity: str,
    period_start: datetime,
    period_end: datetime,
) -> tuple[float, float]:
    """Return (solar_w, load_w) means for a closed 5-minute period.

    Falls back to 0.0 if InfluxDB is unavailable or the token is empty.
    """
    if not influx_token:
        return 0.0, 0.0
    solar = _flux_mean(influx_token, solar_entity, period_start, period_end) or 0.0
    load = _flux_mean(influx_token, load_entity, period_start, period_end) or 0.0
    return solar, load


def _flux_profile(
    influx_token: str,
    entity_id: str,
    tz: ZoneInfo,
    days: int,
) -> dict[int, float]:
    """7-day trailing average of one entity, keyed by local minute-of-day."""
    from influxdb_client import InfluxDBClient  # type: ignore[import]

    oid = _object_id(entity_id)
    q = (
        f'from(bucket: "{_INFLUX_BUCKET}")'
        f'  |> range(start: -{days}d)'
        f'  |> filter(fn: (r) => r["entity_id"] == "{oid}")'
        f'  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)'
        f'  |> fill(usePrevious: true)'
    )
    acc: dict[int, list[float]] = defaultdict(list)
    try:
        with InfluxDBClient(url=_INFLUX_URL, token=influx_token, org=_INFLUX_ORG) as c:
            for table in c.query_api().query(q):
                for rec in table.records:
                    val = rec.get_value()
                    if val is None:
                        continue
                    local_t = rec.get_time().astimezone(tz)
                    acc[local_t.hour * 60 + local_t.minute].append(float(val))
    except Exception as exc:
        log.warning("InfluxDB profile failed (%s): %s", entity_id, exc)
        return {}
    return {k: sum(v) / len(v) for k, v in acc.items()}


def read_load_profile(
    influx_token: str,
    load_entity: str,
    solar_entity: str,
    tz_name: str,
    days: int = 7,
) -> tuple[dict[int, float], dict[int, float]]:
    """Return (load_profile, solar_profile), each {minute_of_day: mean_w}.

    Returns empty dicts if the token is empty or InfluxDB is unreachable.
    """
    if not influx_token:
        return {}, {}
    tz = ZoneInfo(tz_name)
    return (
        _flux_profile(influx_token, load_entity, tz, days),
        _flux_profile(influx_token, solar_entity, tz, days),
    )


def read_raw_series(
    influx_token: str,
    entity_id: str,
    start: datetime,
    stop: datetime,
    field: str = "value",
    seed_lookback_days: int = 30,
) -> list[tuple[datetime, "float | str"]]:
    """Raw points for one entity over [start, stop), plus one seed point before start.

    Returns a time-sorted list of (utc_datetime, value). The seed point is the last
    value strictly before `start`, so a sensor that has sat flat since before the
    window still has a value to forward-fill from. Values are returned untouched
    (float for numeric sensors, str for categorical states); the caller rolls them
    up. Returns an empty list if InfluxDB is unreachable.
    """
    from influxdb_client import InfluxDBClient  # type: ignore[import]

    oid = _object_id(entity_id)
    flt = f'|> filter(fn: (r) => r["entity_id"] == "{oid}" and r["_field"] == "{field}")'
    base = f'from(bucket: "{_INFLUX_BUCKET}")'
    q_seed = (
        f"{base}"
        f'  |> range(start: {_iso(start - timedelta(days=seed_lookback_days))}, stop: {_iso(start)})'
        f"  {flt}"
        f"  |> last()"
    )
    q_main = (
        f"{base}"
        f"  |> range(start: {_iso(start)}, stop: {_iso(stop)})"
        f"  {flt}"
    )
    records: list[tuple[datetime, float | str]] = []
    try:
        with InfluxDBClient(url=_INFLUX_URL, token=influx_token, org=_INFLUX_ORG) as c:
            api = c.query_api()
            for q in (q_seed, q_main):
                for table in api.query(q):
                    for rec in table.records:
                        v = rec.get_value()
                        if v is not None:
                            records.append((rec.get_time(), v))
    except Exception as exc:
        log.warning("InfluxDB raw read failed (%s, field=%s): %s", entity_id, field, exc)
        return []
    records.sort(key=lambda r: r[0])
    return records
