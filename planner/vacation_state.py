"""
Vacation State Module

SQLite-backed state persistence for vacation mode features.
Uses the existing learning.sqlite_path database.

Rev K19: Anti-legionella cycle tracking.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

logger = logging.getLogger("darkstar.planner.vacation")


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create vacation_state table if not exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vacation_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
    """)
    conn.commit()


def load_last_anti_legionella(sqlite_path: str) -> Optional[datetime]:
    """
    Load the last anti-legionella run timestamp from SQLite.

    Args:
        sqlite_path: Path to the SQLite database file.

    Returns:
        datetime of last run, or None if never run.
    """
    try:
        conn = sqlite3.connect(sqlite_path)
        _ensure_table(conn)
        cursor = conn.execute(
            "SELECT value FROM vacation_state WHERE key = 'last_anti_legionella_at'"
        )
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None
    except Exception as e:
        logger.warning("Failed to load last_anti_legionella_at: %s", e)
        return None


def save_last_anti_legionella(sqlite_path: str, timestamp: datetime) -> None:
    """
    Save the anti-legionella run timestamp to SQLite.

    Args:
        sqlite_path: Path to the SQLite database file.
        timestamp: When the anti-legionella cycle was scheduled.
    """
    try:
        conn = sqlite3.connect(sqlite_path)
        _ensure_table(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO vacation_state (key, value, updated_at)
            VALUES ('last_anti_legionella_at', ?, ?)
            """,
            (timestamp.isoformat(), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
        logger.info("Saved last_anti_legionella_at: %s", timestamp.isoformat())
    except Exception as e:
        logger.error("Failed to save last_anti_legionella_at: %s", e)
