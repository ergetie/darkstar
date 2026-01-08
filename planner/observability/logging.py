"""
Observability Logging

Handles persistence of debug payloads and other observability metrics.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def ensure_learning_schema(db_path: str) -> None:
    """Create sqlite tables when learning is enabled."""
    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS planner_debug (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        conn.commit()


def record_debug_payload(payload: dict[str, Any], learning_config: dict[str, Any]) -> None:
    """
    Persist planner debug payloads for observability.

    Args:
        payload: The debug payload dictionary
        learning_config: Learning configuration dictionary
    """
    if not learning_config.get("enable", False):
        return

    db_path = learning_config.get("sqlite_path", "data/learning.db")

    # Ensure schema exists
    ensure_learning_schema(db_path)

    timestamp = datetime.now(UTC).isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO planner_debug (created_at, payload)
                VALUES (?, ?)
                """,
                (timestamp, json.dumps(payload)),
            )
            conn.commit()
    except Exception as e:
        print(f"[observability] Failed to record debug payload: {e}")
