"""Updater DB restore: find the newest backup of this apply and put it back safely."""

from __future__ import annotations

import os
import sqlite3
import time
from typing import TYPE_CHECKING

import pytest

from updater.db_restore import RestoreError, find_backup, restore

if TYPE_CHECKING:
    from pathlib import Path


def _db(path: Path, value: str) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("DELETE FROM t")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return path


def _value(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT v FROM t").fetchone()[0]
    finally:
        conn.close()


def _backup(tmp_path: Path, name: str, age_s: float) -> Path:
    directory = tmp_path / "backups"
    directory.mkdir(exist_ok=True)
    path = _db(directory / name, name)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_newest_backup_is_picked(tmp_path: Path) -> None:
    _backup(tmp_path, "pre-migration-a.db", 30)
    newest = _backup(tmp_path, "pre-migration-b.db", 10)
    _backup(tmp_path, "other.db", 1)  # not a pre-migration backup
    assert find_backup(str(tmp_path / "x.db"), time.time() - 60) == newest


def test_backup_older_than_apply_is_ignored(tmp_path: Path) -> None:
    _backup(tmp_path, "pre-migration-a.db", 600)
    assert find_backup(str(tmp_path / "x.db"), time.time() - 60) is None


def test_slack_allows_slightly_early_mtime(tmp_path: Path) -> None:
    path = _backup(tmp_path, "pre-migration-a.db", 61)
    assert find_backup(str(tmp_path / "x.db"), time.time() - 60) == path


def test_missing_backup_dir(tmp_path: Path) -> None:
    assert find_backup(str(tmp_path / "x.db"), 0) is None


def test_restore_replaces_db_and_removes_wal_files(tmp_path: Path) -> None:
    db = _db(tmp_path / "x.db", "migrated")
    backup = _backup(tmp_path, "pre-migration-a.db", 5)
    wal = tmp_path / "x.db-wal"
    shm = tmp_path / "x.db-shm"
    wal.write_text("stale")
    shm.write_text("stale")
    restore(str(db), backup)
    assert _value(db) == "pre-migration-a.db"
    assert not wal.exists()
    assert not shm.exists()
    assert not (tmp_path / "x.db.restore.tmp").exists()
    assert backup.exists()


def test_corrupt_backup_is_rejected_and_db_untouched(tmp_path: Path) -> None:
    db = _db(tmp_path / "x.db", "live")
    (tmp_path / "backups").mkdir()
    bad = tmp_path / "backups" / "pre-migration-a.db"
    bad.write_bytes(b"this is not sqlite" * 200)
    with pytest.raises(RestoreError):
        restore(str(db), bad)
    assert _value(db) == "live"
    assert not (tmp_path / "x.db.restore.tmp").exists()
