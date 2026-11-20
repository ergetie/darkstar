"""Database safety for start-up: backup before a migration, restore on failure.

Command line (called by ``scripts/docker-entrypoint.sh`` and the add-on ``run.sh`` files)::

    python -m backend.db_safety pre-migrate        # prints the backup path, if one was made
    python -m backend.db_safety restore <backup>   # puts a backup back in place
    python -m backend.db_safety compact [<backup>] # prune, then one-time auto_vacuum switch

Only the standard library ``sqlite3`` is used for the database work. ``alembic`` is imported
lazily, only to read the migration heads.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import math
import os
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from zoneinfo import ZoneInfo

from backend.core.secrets import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

logger = logging.getLogger("darkstar.db_safety")

DEFAULT_DB_PATH = "data/planner_learning.db"
BACKUP_DIR_NAME = "backups"
BACKUP_PREFIX = "pre-migration-"
BACKUP_SUFFIX = ".db"
BACKUP_GLOB = f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"
KEEP_BACKUPS = 3
FREE_SPACE_MARGIN_BYTES = 64 * 1024 * 1024
_SQLITE_BUSY_TIMEOUT_S = 30
_BACKUP_PAGES_PER_STEP = 1024
_BACKUP_SLEEP_S = 0.01
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_AUTO_VACUUM_NONE = 0
_AUTO_VACUUM_INCREMENTAL = 2
_DEFAULT_TIMEZONE = "Europe/Stockholm"
_PRUNE_BATCH_ROWS = 5000
_PRUNE_PAUSE_S = 0.2
_VACUUM_PAGES = 1000
_VACUUM_PAUSE_S = 0.1
_VACUUM_BUDGET_S = 120.0
_COMPACT_SPACE_FACTOR = 1.2


class BackupError(Exception):
    """A backup could not be created or did not verify."""


def resolve_db_path() -> Path:
    """Return the database path the way the application does.

    ``DB_PATH`` env, else ``learning.sqlite_path`` from ``config.yaml``, else
    ``data/planner_learning.db``, resolved against the current directory.
    """
    configured = os.getenv("DB_PATH")
    if not configured:
        learning: object = load_yaml("config.yaml").get("learning")
        value: object = (
            cast("dict[str, object]", learning).get("sqlite_path")
            if isinstance(learning, dict)
            else None
        )
        configured = str(value) if value else DEFAULT_DB_PATH
    return Path(configured).resolve()


def backup_dir(db_path: Path) -> Path:
    """Folder that holds the backups: ``backups/`` next to the database file."""
    return db_path.parent / BACKUP_DIR_NAME


def _has_content(db_path: Path) -> bool:
    try:
        return db_path.stat().st_size > 0
    except FileNotFoundError:
        return False


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=_SQLITE_BUSY_TIMEOUT_S
    )


def _db_revisions(db_path: Path) -> set[str] | None:
    """Revisions stored in ``alembic_version``, or None when the table is missing."""
    conn = _connect_ro(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not has_table:
            return None
        return {str(row[0]) for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()


def script_heads(alembic_ini: Path) -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return set(ScriptDirectory.from_config(Config(str(alembic_ini))).get_heads())


def migration_pending(db_path: Path, alembic_ini: Path = _DEFAULT_ALEMBIC_INI) -> bool:
    """True when the database exists and its revisions differ from the Alembic heads.

    A missing or empty file is a fresh install, not pending. A database without an
    ``alembic_version`` table is a legacy database and is pending.
    """
    if not _has_content(db_path):
        return False
    revisions = _db_revisions(db_path)
    if revisions is None:
        return True
    return revisions != script_heads(alembic_ini)


def switch_pending(db_path: Path) -> bool:
    """True when the one-time ``auto_vacuum`` switch is still to do (mode 0)."""
    if not _has_content(db_path):
        return False
    conn = _connect_ro(db_path)
    try:
        return conn.execute("PRAGMA auto_vacuum").fetchone()[0] == _AUTO_VACUUM_NONE
    finally:
        conn.close()


def _revision_label(db_path: Path) -> str:
    try:
        revisions = _db_revisions(db_path)
    except sqlite3.Error:
        revisions = None
    if not revisions:
        return "none"
    return re.sub(r"[^A-Za-z0-9_+.-]", "", "+".join(sorted(revisions))) or "none"


def _remove_file(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    # Best effort: not every platform or filesystem allows opening a directory.
    with contextlib.suppress(OSError):
        _fsync_file(path)


def _quick_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA quick_check").fetchone()
    return str(row[0]) if row else "no result"


def create_backup(db_path: Path) -> Path:
    """Create a verified, self-contained backup and return its path.

    Raises BackupError on any failure; no partial file is left behind. Old backups
    are not pruned here, call ``prune_backups`` after a success.
    """
    if not _has_content(db_path):
        raise BackupError(f"Database file missing or empty: {db_path}")

    target_dir = backup_dir(db_path)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        needed = db_path.stat().st_size + FREE_SPACE_MARGIN_BYTES
        free = shutil.disk_usage(target_dir).free
    except OSError as exc:
        raise BackupError(f"Cannot prepare backup folder {target_dir}: {exc}") from exc
    if free < needed:
        raise BackupError(
            f"Not enough free disk space for a backup in {target_dir}: "
            f"need {needed // (1024 * 1024)} MB, have {free // (1024 * 1024)} MB"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    label = _revision_label(db_path)
    final = target_dir / f"{BACKUP_PREFIX}{stamp}-{label}{BACKUP_SUFFIX}"
    tmp = target_dir / f".{final.name}.tmp"
    try:
        src = _connect_ro(db_path)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst, pages=_BACKUP_PAGES_PER_STEP, sleep=_BACKUP_SLEEP_S)
                # The copy inherits WAL mode from the source; make it one plain file.
                dst.execute("PRAGMA journal_mode=DELETE")
                verdict = _quick_check(dst)
            finally:
                dst.close()
        finally:
            src.close()
        if verdict != "ok":
            raise BackupError(f"Backup verification failed: {verdict}")
        _fsync_file(tmp)
        tmp.replace(final)
        _fsync_dir(target_dir)
    except BackupError:
        _cleanup_temp(tmp)
        raise
    except (sqlite3.Error, OSError) as exc:
        _cleanup_temp(tmp)
        raise BackupError(f"Backup failed: {exc}") from exc
    except BaseException:
        _cleanup_temp(tmp)
        raise
    return final


def _cleanup_temp(tmp: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        _remove_file(tmp.with_name(tmp.name + suffix))


def prune_backups(directory: Path, keep: int = KEEP_BACKUPS) -> list[Path]:
    """Delete all but the ``keep`` newest ``pre-migration-*.db`` files; return the deleted."""
    if not directory.is_dir():
        return []
    backups = sorted(p for p in directory.glob(BACKUP_GLOB) if p.is_file())
    doomed = backups[: max(len(backups) - keep, 0)]
    for path in doomed:
        _remove_file(path)
    return doomed


def restore_backup(db_path: Path, backup_path: Path) -> None:
    """Replace the database with a backup, atomically, discarding ``-wal``/``-shm``."""
    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_path}")
    tmp = db_path.with_name(db_path.name + ".restore.tmp")
    sidecars = (db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm"))
    try:
        shutil.copyfile(backup_path, tmp)
        _fsync_file(tmp)
        # Stale WAL content must never be replayed into the restored file.
        for sidecar in sidecars:
            _remove_file(sidecar)
        tmp.replace(db_path)
        for sidecar in sidecars:
            _remove_file(sidecar)
        _fsync_dir(db_path.parent)
    except BaseException:
        _remove_file(tmp)
        raise


@dataclass(frozen=True)
class _RetentionRule:
    """How one retention key is read: where it lives, default, minimum, whether 0 is allowed."""

    section: str
    key: str
    default: int
    minimum: int
    allow_zero: bool


_RULES = {
    "execution_log": _RetentionRule("executor", "history_retention_days", 30, 7, False),
    "planner_debug": _RetentionRule("learning", "planner_debug_retention_days", 14, 1, False),
    "s_index_history": _RetentionRule("learning", "s_index_history_retention_days", 365, 90, False),
    "learning": _RetentionRule("learning", "retention_days", 0, 400, True),
    "price_forecasts": _RetentionRule("learning", "price_forecast_retention_days", 0, 400, True),
    "learning_runs": _RetentionRule("learning", "learning_runs_retention_days", 0, 365, True),
}


def _parse_days(value: object, rule: _RetentionRule) -> int:
    """Validate one retention value; never returns something that could delete extra data."""
    label = f"{rule.section}.{rule.key}"
    if value is None:
        return rule.default
    number: float | None = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        with contextlib.suppress(ValueError):
            number = float(value.strip())
    if number is None or not math.isfinite(number):
        logger.warning("Invalid %s=%r, using default %d", label, value, rule.default)
        return rule.default
    days = int(number)
    if days < 0 or (days == 0 and not rule.allow_zero):
        logger.warning("Invalid %s=%r, using default %d", label, value, rule.default)
        return rule.default
    if 0 < days < rule.minimum:
        logger.warning("%s=%d is below the minimum, using %d", label, days, rule.minimum)
        return rule.minimum
    return days


@dataclass(frozen=True)
class RetentionConfig:
    """Retention windows in days per table group; 0 means keep forever."""

    execution_log_days: int = _RULES["execution_log"].default
    planner_debug_days: int = _RULES["planner_debug"].default
    s_index_history_days: int = _RULES["s_index_history"].default
    learning_days: int = _RULES["learning"].default
    price_forecast_days: int = _RULES["price_forecasts"].default
    learning_runs_days: int = _RULES["learning_runs"].default
    timezone: str = _DEFAULT_TIMEZONE

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> RetentionConfig:
        """Build from a parsed ``config.yaml``; every invalid value falls back safely."""

        def read(name: str) -> int:
            rule = _RULES[name]
            section = config.get(rule.section)
            if not isinstance(section, dict):
                return rule.default
            return _parse_days(cast("Mapping[str, object]", section).get(rule.key), rule)

        tz_name = config.get("timezone")
        return cls(
            execution_log_days=read("execution_log"),
            planner_debug_days=read("planner_debug"),
            s_index_history_days=read("s_index_history"),
            learning_days=read("learning"),
            price_forecast_days=read("price_forecasts"),
            learning_runs_days=read("learning_runs"),
            timezone=str(tz_name) if tz_name else _DEFAULT_TIMEZONE,
        )


def load_retention(config_path: str = "config.yaml") -> RetentionConfig:
    """Read the retention settings from ``config.yaml`` (defaults when absent)."""
    return RetentionConfig.from_config(load_yaml(config_path))


_LOCAL = "local"  # ISO text with the configured zone's offset
_UTC = "utc"  # ISO text with +00:00
_NAIVE_UTC = "naive_utc"  # 'YYYY-MM-DD HH:MM:SS.ffffff' (SQLAlchemy DateTime)
# (table, cutoff column, cutoff format, RetentionConfig field)
_PRUNE_TARGETS = (
    ("execution_log", "executed_at", _LOCAL, "execution_log_days"),
    ("planner_debug", "created_at", _UTC, "planner_debug_days"),
    ("s_index_history", "created_at", _UTC, "s_index_history_days"),
    ("slot_observations", "slot_start", _LOCAL, "learning_days"),
    ("slot_plans", "slot_start", _LOCAL, "learning_days"),
    ("slot_forecasts", "slot_start", _LOCAL, "learning_days"),
    ("price_forecasts", "slot_start", _LOCAL, "price_forecast_days"),
    ("learning_runs", "started_at", _NAIVE_UTC, "learning_runs_days"),
)


def _cutoff(now: datetime, days: int, kind: str, tz: ZoneInfo) -> str:
    moment = now - timedelta(days=days)
    if kind == _LOCAL:
        return moment.astimezone(tz).isoformat()
    if kind == _UTC:
        return moment.astimezone(UTC).isoformat()
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ValueError, OSError, KeyError):
        logger.warning("Unknown timezone %r, using %s", name, _DEFAULT_TIMEZONE)
        return ZoneInfo(_DEFAULT_TIMEZONE)


def prune(
    db_path: Path,
    retention: RetentionConfig,
    now: datetime | None = None,
    batch: int = _PRUNE_BATCH_ROWS,
    pause: float = _PRUNE_PAUSE_S,
) -> dict[str, int]:
    """Delete rows older than their retention window; return deleted rows per table.

    Rows go in batches of ``batch`` with a commit and ``pause`` seconds in between, so a
    concurrent writer waits for one short transaction at most. Tables with a retention of 0
    (keep forever) or that do not exist are skipped. Errors, including ``database is
    locked``, propagate to the caller.
    """
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    tz = _zone(retention.timezone)
    deleted: dict[str, int] = {}
    conn = sqlite3.connect(db_path, timeout=_SQLITE_BUSY_TIMEOUT_S, isolation_level=None)
    try:
        existing = {
            str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, column, kind, field in _PRUNE_TARGETS:
            days: int = getattr(retention, field)
            if days <= 0 or table not in existing:
                continue
            cutoff = _cutoff(moment, days, kind, tz)
            sql = (
                f"DELETE FROM {table} WHERE rowid IN "
                f"(SELECT rowid FROM {table} WHERE {column} < ? LIMIT ?)"
            )
            total = 0
            while True:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    count = conn.execute(sql, (cutoff, batch)).rowcount
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                total += count
                if count < batch:
                    break
                time.sleep(pause)
            deleted[table] = total
    finally:
        conn.close()
    return deleted


def _pragma_int(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute(f"PRAGMA {name}").fetchone()[0])


def compact(
    db_path: Path,
    backup_path: str | Path | None,
    retention: RetentionConfig | None = None,
) -> str:
    """One-time prune and switch to ``auto_vacuum=INCREMENTAL``; returns ``switched``/``skipped``.

    Skipped (database untouched, except for a legitimate prune) when already incremental,
    when no verified backup was given, or when disk space is short. Never raises.
    """
    try:
        return _compact(db_path, backup_path, retention)
    except Exception as exc:
        logger.warning("Database compaction failed, continuing: %s", exc)
        return "skipped"


def _compact(
    db_path: Path, backup_path: str | Path | None, retention: RetentionConfig | None
) -> str:
    if not _has_content(db_path):
        return "skipped"
    if not switch_pending(db_path):
        logger.info("Database %s already uses incremental auto-vacuum.", db_path)
        return "skipped"
    if not backup_path or not Path(backup_path).is_file():
        logger.warning("No verified backup, skipping the storage-format switch.")
        return "skipped"

    deleted = prune(db_path, retention or load_retention())
    if any(deleted.values()):
        logger.info("Retention cleanup removed rows: %s", deleted)

    conn = sqlite3.connect(db_path, timeout=_SQLITE_BUSY_TIMEOUT_S, isolation_level=None)
    try:
        page_size = _pragma_int(conn, "page_size")
        used = (_pragma_int(conn, "page_count") - _pragma_int(conn, "freelist_count")) * page_size
        needed = int(used * _COMPACT_SPACE_FACTOR) + FREE_SPACE_MARGIN_BYTES
        free = shutil.disk_usage(db_path.parent).free
        if free < needed:
            logger.warning(
                "Not enough free disk space to shrink the database: need %d MB, have %d MB. "
                "Skipping.",
                needed // (1024 * 1024),
                free // (1024 * 1024),
            )
            return "skipped"
        # VACUUM writes a full temp copy; keep it on the volume that was just checked.
        previous_tmp = os.environ.get("SQLITE_TMPDIR")
        os.environ["SQLITE_TMPDIR"] = str(db_path.parent)
        try:
            conn.execute(f"PRAGMA auto_vacuum={_AUTO_VACUUM_INCREMENTAL}")
            conn.execute("VACUUM")
        finally:
            if previous_tmp is None:
                os.environ.pop("SQLITE_TMPDIR", None)
            else:
                os.environ["SQLITE_TMPDIR"] = previous_tmp
        mode = _pragma_int(conn, "auto_vacuum")
    finally:
        conn.close()
    if mode != _AUTO_VACUUM_INCREMENTAL:
        logger.warning("Auto-vacuum mode is %d after VACUUM, expected 2.", mode)
        return "skipped"
    logger.info("Database %s shrunk and switched to incremental auto-vacuum.", db_path)
    return "switched"


def incremental_vacuum(
    db_path: Path,
    pages: int = _VACUUM_PAGES,
    pause: float = _VACUUM_PAUSE_S,
    budget_s: float = _VACUUM_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Return free pages to the file system in short batches; return pages freed.

    A no-op unless ``auto_vacuum`` is 2. Never runs a full ``VACUUM``. Stops when the
    freelist is empty or ``budget_s`` is used, then does a passive WAL checkpoint.
    """
    conn = sqlite3.connect(db_path, timeout=_SQLITE_BUSY_TIMEOUT_S, isolation_level=None)
    try:
        if _pragma_int(conn, "auto_vacuum") != _AUTO_VACUUM_INCREMENTAL:
            logger.info("Auto-vacuum is not incremental, free pages are not returned.")
            return 0
        start = clock()
        before = _pragma_int(conn, "freelist_count")
        remaining = before
        while remaining > 0 and clock() - start < budget_s:
            conn.execute(f"PRAGMA incremental_vacuum({int(pages)})").fetchall()
            remaining = _pragma_int(conn, "freelist_count")
            if remaining > 0:
                time.sleep(pause)
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        return before - remaining
    finally:
        conn.close()


def _pre_migrate() -> int:
    db_path = resolve_db_path()
    try:
        migration = migration_pending(db_path)
        switch = switch_pending(db_path)
    except Exception as exc:
        logger.error("Cannot read database state of %s: %s", db_path, exc)
        return 1
    if not (migration or switch):
        logger.info("Database %s: nothing pending, no backup needed.", db_path)
        return 0

    try:
        backup = create_backup(db_path)
    except BackupError as exc:
        if migration:
            logger.error("Backup before migration failed, migration aborted: %s", exc)
            return 1
        logger.warning("Backup failed, skipping the storage-format switch: %s", exc)
        return 0

    for old in prune_backups(backup.parent):
        logger.info("Removed old backup %s", old.name)
    logger.info("Database backup created: %s", backup)
    sys.stdout.write(f"{backup}\n")
    return 0


def _restore(backup_path: str) -> int:
    db_path = resolve_db_path()
    try:
        restore_backup(db_path, Path(backup_path))
    except Exception as exc:
        logger.error("Restore of %s from %s failed: %s", db_path, backup_path, exc)
        return 1
    logger.info("Database %s restored from %s", db_path, backup_path)
    return 0


def _compact_cli(backup_path: str | None) -> int:
    try:
        compact(resolve_db_path(), backup_path)
    except Exception as exc:  # compact never raises; this guards path resolution
        logger.warning("Database compaction failed, continuing: %s", exc)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.db_safety")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pre-migrate", help="back up the database if a migration or switch is pending")
    restore = sub.add_parser("restore", help="replace the database with a backup")
    restore.add_argument("backup", help="path of the backup file")
    compact_cmd = sub.add_parser("compact", help="prune and switch to incremental auto-vacuum")
    compact_cmd.add_argument("backup", nargs="?", default="", help="verified backup path")
    args = parser.parse_args(argv)

    handler = logging.StreamHandler()  # stderr: stdout is reserved for the backup path
    handler.setFormatter(logging.Formatter("[db_safety] %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if args.command == "pre-migrate":
        return _pre_migrate()
    if args.command == "compact":
        return _compact_cli(args.backup)
    return _restore(args.backup)


if __name__ == "__main__":
    sys.exit(main())
