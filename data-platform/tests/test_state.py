"""Unit tests for durable simulation state, including schema-version reset."""
from __future__ import annotations

import json
from pathlib import Path

from app.state import _STATE_VERSION, SimState, load_state, save_state


def test_round_trip_current_version(tmp_path: Path):
    state = SimState(simulated_soc=42.0, pending_planned_mode="charge", last_settled_dt=None)
    save_state(str(tmp_path), state)
    loaded = load_state(str(tmp_path))
    assert loaded is not None
    assert loaded.simulated_soc == 42.0
    assert loaded.version == _STATE_VERSION


def test_missing_returns_none(tmp_path: Path):
    assert load_state(str(tmp_path)) is None


def test_stale_unversioned_state_is_discarded(tmp_path: Path):
    # Pre-0.4.2 state had no version field; it must be dropped so the run re-seeds.
    (tmp_path / "sim_state.json").write_text(
        json.dumps({"simulated_soc": 50.0, "pending_planned_mode": None, "last_settled_dt": None})
    )
    assert load_state(str(tmp_path)) is None


def test_older_version_is_discarded(tmp_path: Path):
    (tmp_path / "sim_state.json").write_text(
        json.dumps({
            "simulated_soc": 50.0, "pending_planned_mode": None,
            "last_settled_dt": None, "version": _STATE_VERSION - 1,
        })
    )
    assert load_state(str(tmp_path)) is None
