"""Fetch and parse AEMO P5MIN 5-minute predispatch reports."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import requests

log = logging.getLogger("bluey.p5")

NEMWEB_BASE = "https://nemweb.com.au/Reports/Current/P5_Reports/"
FETCH_TIMEOUT = 20
RETRY_ATTEMPTS = 3
RETRY_DELAY = 5


class P5Result(NamedTuple):
    rrp: float
    run_datetime: str  # AEMO format: "YYYY/MM/DD HH:MM:SS"


def parse_csv(text: str) -> P5Result:
    """Parse P5MIN CSV text -> (rrp, run_datetime) for VIC1 5-minute-ahead interval.

    Pure function; raises ValueError if the required data cannot be found.
    """
    lines = text.splitlines()

    header_cols: list[str] | None = None
    for line in lines:
        if line.startswith("I") and "REGIONSOLUTION" in line:
            header_cols = next(csv.reader([line]))
            break

    if header_cols is None:
        raise ValueError("REGIONSOLUTION header not found in P5MIN file")

    run_dt_idx = header_cols.index("RUN_DATETIME")
    interval_dt_idx = header_cols.index("INTERVAL_DATETIME")
    regionid_idx = header_cols.index("REGIONID")
    rrp_idx = header_cols.index("RRP")

    vic1_rows: list[list[str]] = []
    for line in lines:
        if not line.startswith("D"):
            continue
        row = next(csv.reader([line]))
        if len(row) <= rrp_idx:
            continue
        if row[2] != "REGIONSOLUTION":
            continue
        if row[regionid_idx] == "VIC1":
            vic1_rows.append(row)

    if not vic1_rows:
        raise ValueError("No VIC1 rows found in REGIONSOLUTION table")

    run_dt_str = vic1_rows[0][run_dt_idx]
    run_dt = datetime.strptime(run_dt_str, "%Y/%m/%d %H:%M:%S")
    target_dt_str = (run_dt + timedelta(minutes=5)).strftime("%Y/%m/%d %H:%M:%S")

    for row in vic1_rows:
        if row[interval_dt_idx] == target_dt_str:
            return P5Result(rrp=float(row[rrp_idx]), run_datetime=run_dt_str)

    # Fall back to first available interval if the +5-min row is absent.
    log.warning("5-min-ahead VIC1 row not found; using first available interval")
    return P5Result(rrp=float(vic1_rows[0][rrp_idx]), run_datetime=run_dt_str)


def parse_p5(data: bytes) -> P5Result:
    """Unzip P5MIN bytes and parse the embedded CSV."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        csv_bytes = z.read(z.namelist()[0])
    return parse_csv(csv_bytes.decode("utf-8", errors="replace"))


def _latest_filename() -> str:
    """Fetch the NEMWeb directory listing and return the most recent P5MIN filename."""
    resp = requests.get(NEMWEB_BASE, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    names = re.findall(r"PUBLIC_P5MIN_\d{12}_\d{14}\.zip", resp.text)
    if not names:
        raise ValueError("No P5MIN files found in NEMWeb listing")
    return sorted(names)[-1]


def fetch_latest() -> tuple[str, bytes]:
    """Return (filename, raw_zip_bytes) for the most recent P5MIN file."""
    filename = _latest_filename()
    url = NEMWEB_BASE + filename
    resp = requests.get(url, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    return filename, resp.content


def fetch_and_parse(last_run_dt: str | None = None) -> P5Result | None:
    """Fetch the latest P5MIN file, parse it, and apply dedupe.

    Returns None if this run has already been processed or if all retries fail.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            filename, data = fetch_latest()
            result = parse_p5(data)
            if result.run_datetime == last_run_dt:
                log.info("P5 run %s already processed; skipping", result.run_datetime)
                return None
            log.info(
                "P5 fetched: run=%s rrp=%.4f file=%s",
                result.run_datetime,
                result.rrp,
                filename,
            )
            return result
        except Exception as exc:
            log.warning("P5 fetch attempt %d/%d failed: %s", attempt, RETRY_ATTEMPTS, exc)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    log.error("P5 fetch failed after %d attempts", RETRY_ATTEMPTS)
    return None


def load_last_run(data_dir: str) -> str | None:
    path = Path(data_dir) / "last_run_id.json"
    try:
        return json.loads(path.read_text())["run_datetime"]
    except Exception:
        return None


def save_last_run(data_dir: str, run_datetime: str) -> None:
    path = Path(data_dir) / "last_run_id.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_datetime": run_datetime}))