import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("darkstar.strategy.history")

HISTORY_FILE = Path("data/strategy_history.json")
MAX_HISTORY_ENTRIES = 100


def _ensure_data_dir():
    if not HISTORY_FILE.parent.exists():
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)


def append_strategy_event(
    event_type: str, message: str, details: dict[str, Any] | None = None
) -> None:
    """
    Append a new event to the strategy history log.

    Args:
        event_type: Category of event (e.g., 'STRATEGY_CHANGE', 'PRICE_ALERT').
        message: Human-readable summary.
        details: Optional dictionary with technical details (e.g., old/new values).
    """
    _ensure_data_dir()

    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "message": message,
        "details": details or {},
    }

    history: list[dict[str, Any]] = []
    try:
        if HISTORY_FILE.exists():
            with HISTORY_FILE.open(encoding="utf-8") as f:
                history = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read strategy history: {e}")
        history = []

    # Prepend new entry
    history.insert(0, entry)

    # Trim
    if len(history) > MAX_HISTORY_ENTRIES:
        history = history[:MAX_HISTORY_ENTRIES]

    try:
        with HISTORY_FILE.open("w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write strategy history: {e}")


def get_strategy_history(limit: int = 50) -> list[dict[str, Any]]:
    """
    Retrieve the latest strategy history entries.
    """
    try:
        if not HISTORY_FILE.exists():
            return []
        with HISTORY_FILE.open(encoding="utf-8") as f:
            history = json.load(f)
        return history[:limit]
    except Exception as e:
        logger.error(f"Failed to read strategy history: {e}")
        return []
