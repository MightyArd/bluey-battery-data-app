"""Deterministic parser tests against a saved real-data fixture."""
import zipfile
from pathlib import Path

import pytest

from app.p5 import P5Result, parse_csv, parse_p5

FIXTURE_ZIP = Path(__file__).parent / "fixtures" / "p5_vic1_trimmed.zip"


def _fixture_text() -> str:
    with zipfile.ZipFile(FIXTURE_ZIP) as z:
        return z.read(z.namelist()[0]).decode("utf-8", errors="replace")


def test_parse_csv_extracts_vic1_5min_ahead():
    result = parse_csv(_fixture_text())
    assert result.run_datetime == "2026/06/09 08:55:00"
    assert result.rrp == pytest.approx(20.7779, rel=1e-4)


def test_parse_p5_wraps_parse_csv():
    data = FIXTURE_ZIP.read_bytes()
    result = parse_p5(data)
    assert result.run_datetime == "2026/06/09 08:55:00"
    assert result.rrp == pytest.approx(20.7779, rel=1e-4)


def test_parse_csv_ignores_non_vic1_regions():
    result = parse_csv(_fixture_text())
    # NSW1 RRP at the same interval is 66.17559, not the VIC1 value
    assert result.rrp != pytest.approx(66.17559, rel=1e-4)


def test_parse_csv_returns_named_tuple():
    result = parse_csv(_fixture_text())
    assert isinstance(result, P5Result)
    assert isinstance(result.rrp, float)
    assert isinstance(result.run_datetime, str)


def test_parse_csv_raises_on_missing_regionsolution():
    with pytest.raises(ValueError, match="REGIONSOLUTION header not found"):
        parse_csv("C,NEMP.WORLD,P5MIN\nI,P5MIN,CASESOLUTION,2,RUN_DATETIME\n")


def test_parse_csv_raises_on_missing_vic1():
    text = _fixture_text().replace("VIC1", "SA1")
    with pytest.raises(ValueError, match="No VIC1 rows found"):
        parse_csv(text)