"""Restore the pre-migration database backup during an updater rollback.

Stdlib only: the updater image contains `updater/` but not `backend/`. The backup itself is made by
the new Darkstar container right before it migrates (`backend/db_safety.py`); this module only finds
and puts it back. Keep the file naming in sync with `BACKUP_PREFIX`/`backup_dir` there.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sqlite3
from pathlib import Path

BACKUP_DIR_NAME = "backups"
BACKUP_GLOB = "pre-migration-*.db"
# Allow for coarse filesystem timestamps between the apply start and the backup write.
MTIME_SLACK_S = 2.0


class RestoreError(RuntimeError):
    """The backup could not be verified or put in place."""


def find_backup(db_path: str, since: float) -> Path | None:
    """Newest `pre-migration-*.db` next to the database written at or after `since` (minus slack)."""
    directory = Path(db_path).parent / BACKUP_DIR_NAME
    newest: tuple[float, Path] | None = None
    try:
        candidates = list(directory.glob(BACKUP_GLOB))
    except OSError:
        return None
    for path in candidates:
        try:
            if not path.is_file():
                continue
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < since - MTIME_SLACK_S:
            continue
        if newest is None or (mtime, path.name) > (newest[0], newest[1].name):
            newest = (mtime, path)
    return newest[1] if newest else None


def _quick_check(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise RestoreError(f"Backup is not a readable database: {exc}") from exc
    if rows != [("ok",)]:
        raise RestoreError("Backup failed the integrity check")


def _fsync(path: Path, flags: int = os.O_RDONLY) -> None:
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def restore(db_path: str, backup: Path) -> None:
    """Replace the database with `backup` atomically and discard `-wal`/`-shm`."""
    db = Path(db_path)
    tmp = db.with_name(db.name + ".restore.tmp")
    sidecars = (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm"))
    try:
        shutil.copyfile(backup, tmp)
        _quick_check(tmp)
        _fsync(tmp)
        # Stale WAL content must never be replayed into the restored file.
        for sidecar in sidecars:
            _remove(sidecar)
        tmp.replace(db)
        for sidecar in sidecars:
            _remove(sidecar)
        _fsync(db.parent)
    except BaseException:
        _remove(tmp)
        raise
