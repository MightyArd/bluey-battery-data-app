"""Durable simulation state persisted to /data."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("bluey.state")

_STATE_FILE = "sim_state.json"

# Schema version of the persisted simulation state. Bump this to force the next run
# to discard any older persisted state and cold-start (re-seed simulated SOC from
# the actual battery SOC). Bumped to 2 with the soc_entity name correction: earlier
# state was seeded from a non-existent entity, so it must be re-seeded.
_STATE_VERSION = 2


@dataclass
class SimState:
    simulated_soc: float
    pending_planned_mode: str | None
    last_settled_dt: str | None  # AEMO format "YYYY/MM/DD HH:MM:SS"
    version: int = field(default=_STATE_VERSION)


def load_state(data_dir: str) -> SimState | None:
    """Load persisted state, or None if absent, unreadable, or a stale schema version.

    A version mismatch (including older state with no version field) is discarded so
    the caller cold-starts and re-seeds.
    """
    path = Path(data_dir) / _STATE_FILE
    try:
        d = json.loads(path.read_text())
    except Exception:
        return None
    if d.get("version") != _STATE_VERSION:
        log.info(
            "Discarding stale simulation state (version %s, expected %s); will re-seed",
            d.get("version"), _STATE_VERSION,
        )
        return None
    try:
        return SimState(**d)
    except Exception:
        return None


def save_state(data_dir: str, state: SimState) -> None:
    path = Path(data_dir) / _STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state.version = _STATE_VERSION
    path.write_text(json.dumps(asdict(state)))
