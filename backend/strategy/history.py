import json
import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger("darkstar.strategy.history")

HISTORY_FILE = os.path.join("data", "strategy_history.json")
MAX_HISTORY_ENTRIES = 100


def _ensure_data_dir():
    if not os.path.exists("data"):
        os.makedirs("data")


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
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
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
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write strategy history: {e}")


def get_strategy_history(limit: int = 50) -> list[dict[str, Any]]:
    """
    Retrieve the latest strategy history entries.
    """
    try:
        if not os.path.exists(HISTORY_FILE):
            return []
        with open(HISTORY_FILE) as f:
            history = json.load(f)
        return history[:limit]
    except Exception as e:
        logger.error(f"Failed to read strategy history: {e}")
        return []
