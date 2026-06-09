"""Durable simulation state persisted to /data."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_STATE_FILE = "sim_state.json"


@dataclass
class SimState:
    simulated_soc: float
    pending_planned_mode: str | None
    last_settled_dt: str | None  # AEMO format "YYYY/MM/DD HH:MM:SS"


def load_state(data_dir: str) -> SimState | None:
    path = Path(data_dir) / _STATE_FILE
    try:
        d = json.loads(path.read_text())
        return SimState(**d)
    except Exception:
        return None


def save_state(data_dir: str, state: SimState) -> None:
    path = Path(data_dir) / _STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state)))
