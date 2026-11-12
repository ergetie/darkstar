"""Database revision gate: never move to code that lacks the DB's alembic revision."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .repo import Repo


def db_revision(db_path: str) -> str | None:
    """Current alembic revision of the DB, or None if absent/empty/unreadable."""
    path = Path(db_path)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] else None


def blocked_message(repo: Repo, db_path: str, ref: str, channel: str) -> str | None:
    """Return the blocking message if `ref` lacks the DB revision, else None."""
    current = db_revision(db_path)
    if current is None:
        return None
    if current in repo.revisions_at(ref):
        return None
    return f"{channel.capitalize()} doesn't include your database version yet"
