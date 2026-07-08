import json
import logging
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger("darkstar.core.ev_state")

STATE_FILE_PATH = Path("data/ev_multi_day_state.json")
last_darkstar_write: dict[str, float] = {}


def read_ev_state() -> dict[str, dict[str, Any]]:
    """Read the EV multi-day state file. Returns an empty dict if not found or invalid."""
    if not STATE_FILE_PATH.exists():
        return {}
    try:
        with STATE_FILE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return cast("dict[str, dict[str, Any]]", data)
    except Exception as exc:
        logger.warning("Could not read EV state file: %s", exc)
    return {}


def write_ev_state(state: dict[str, dict[str, Any]]) -> None:
    """Write the EV multi-day state file atomically using a temp file."""
    try:
        STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = STATE_FILE_PATH.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        tmp_path.replace(STATE_FILE_PATH)
    except Exception as exc:
        logger.error("Failed to write EV state file: %s", exc)
        raise
