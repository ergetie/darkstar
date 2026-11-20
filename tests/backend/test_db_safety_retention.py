"""Retention config, prune, one-time auto-vacuum switch and incremental vacuum."""

import logging
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

from backend import db_safety
from backend.db_safety import RetentionConfig

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
STOCKHOLM = ZoneInfo("Europe/Stockholm")


# --- RetentionConfig -------------------------------------------------------------------------


def test_defaults_without_config() -> None:
    cfg = RetentionConfig.from_config({})
    assert cfg == RetentionConfig()
    assert (cfg.execution_log_days, cfg.planner_debug_days, cfg.s_index_history_days) == (
        30,
        14,
        365,
    )
    assert (cfg.learning_days, cfg.price_forecast_days, cfg.learning_runs_days) == (0, 0, 0)


@pytest.mark.parametrize(
    ("section", "key", "field", "value", "expected"),
    [
        ("executor", "history_retention_days", "execution_log_days", 90, 90),
        ("executor", "history_retention_days", "execution_log_days", 3, 7),
        ("executor", "history_retention_days", "execution_log_days", 0, 30),
        ("executor", "history_retention_days", "execution_log_days", -5, 30),
        ("executor", "history_retention_days", "execution_log_days", "abc", 30),
        ("learning", "planner_debug_retention_days", "planner_debug_days", 0, 14),
        ("learning", "planner_debug_retention_days", "planner_debug_days", 1, 1),
        ("learning", "s_index_history_retention_days", "s_index_history_days", 30, 90),
        ("learning", "s_index_history_retention_days", "s_index_history_days", 0, 365),
        ("learning", "retention_days", "learning_days", 0, 0),
        ("learning", "retention_days", "learning_days", 30, 400),
        ("learning", "retention_days", "learning_days", 500, 500),
        ("learning", "retention_days", "learning_days", "abc", 0),
        ("learning", "retention_days", "learning_days", True, 0),
        ("learning", "retention_days", "learning_days", float("nan"), 0),
        ("learning", "retention_days", "learning_days", "600", 600),
        ("learning", "price_forecast_retention_days", "price_forecast_days", 10, 400),
        ("learning", "price_forecast_retention_days", "price_forecast_days", "abc", 0),
        ("learning", "learning_runs_retention_days", "learning_runs_days", 100, 365),
        ("learning", "learning_runs_retention_days", "learning_runs_days", 400, 400),
        ("learning", "learning_runs_retention_days", "learning_runs_days", None, 0),
    ],
)
def test_retention_validation(
    section: str, key: str, field: str, value: object, expected: int
) -> None:
    cfg = RetentionConfig.from_config({section: {key: value}})
    assert getattr(cfg, field) == expected


def test_timezone_and_non_mapping_sections() -> None:
    cfg = RetentionConfig.from_config({"timezone": "Europe/Berlin", "learning": None})
    assert cfg.timezone == "Europe/Berlin"
    assert cfg.learning_days == 0


def test_config_default_yaml_has_every_key_with_documented_default() -> None:
    data = yaml.safe_load((REPO_ROOT / "config.default.yaml").read_text(encoding="utf-8"))
    expected = {
        ("executor", "history_retention_days"): 30,
        ("learning", "planner_debug_retention_days"): 14,
        ("learning", "s_index_history_retention_days"): 365,
        ("learning", "retention_days"): 0,
        ("learning", "price_forecast_retention_days"): 0,
        ("learning", "learning_runs_retention_days"): 0,
    }
    for (section, key), default in expected.items():
        assert data[section][key] == default, f"{section}.{key}"
    assert RetentionConfig.from_config(data) == RetentionConfig(timezone=data["timezone"])


# --- prune -----------------------------------------------------------------------------------

_SCHEMA = {
    "execution_log": "executed_at",
    "planner_debug": "created_at",
    "s_index_history": "created_at",
    "slot_observations": "slot_start",
    "slot_plans": "slot_start",
    "slot_forecasts": "slot_start",
    "price_forecasts": "slot_start",
    "learning_runs": "started_at",
}


_LOCAL_TABLES = (
    "execution_log",
    "slot_observations",
    "slot_plans",
    "slot_forecasts",
    "price_forecasts",
)


def _fmt(table: str, moment: datetime) -> str:
    if table in _LOCAL_TABLES:
        return moment.astimezone(STOCKHOLM).isoformat()
    if table in ("planner_debug", "s_index_history"):
        return moment.astimezone(UTC).isoformat()
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _make_learning_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    for table, column in _SCHEMA.items():
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, {column} TEXT, pad TEXT)")
    conn.commit()
    conn.close()
    return path


def _insert(db: Path, table: str, moments: list[datetime]) -> None:
    column = _SCHEMA[table]
    conn = sqlite3.connect(db)
    conn.executemany(
        f"INSERT INTO {table} ({column}, pad) VALUES (?, ?)",
        [(_fmt(table, m), "x" * 200) for m in moments],
    )
    conn.commit()
    conn.close()


def _count(db: Path, table: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


_ALL_ON = RetentionConfig(
    execution_log_days=30,
    planner_debug_days=14,
    s_index_history_days=365,
    learning_days=500,
    price_forecast_days=500,
    learning_runs_days=400,
)
_WINDOWS = {
    "execution_log": 30,
    "planner_debug": 14,
    "s_index_history": 365,
    "slot_observations": 500,
    "slot_plans": 500,
    "slot_forecasts": 500,
    "price_forecasts": 500,
    "learning_runs": 400,
}


@pytest.mark.parametrize("table", list(_SCHEMA))
def test_prune_cutoff_per_table(tmp_path: Path, table: str) -> None:
    db = _make_learning_db(tmp_path / "p.db")
    days = _WINDOWS[table]
    _insert(db, table, [NOW - timedelta(days=days + 1), NOW - timedelta(days=days - 1), NOW])
    deleted = db_safety.prune(db, _ALL_ON, now=NOW, pause=0)
    assert deleted[table] == 1
    assert _count(db, table) == 2
    conn = sqlite3.connect(db)
    oldest = conn.execute(f"SELECT MIN({_SCHEMA[table]}) FROM {table}").fetchone()[0]
    conn.close()
    assert oldest == _fmt(table, NOW - timedelta(days=days - 1))


def test_prune_batches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_learning_db(tmp_path / "p.db")
    _insert(db, "execution_log", [NOW - timedelta(days=100)] * 12_000)
    _insert(db, "execution_log", [NOW])
    sleeps: list[float] = []
    monkeypatch.setattr(db_safety.time, "sleep", sleeps.append)
    deleted = db_safety.prune(db, RetentionConfig(), now=NOW, batch=5000, pause=0.2)
    assert deleted == {"execution_log": 12_000, "planner_debug": 0, "s_index_history": 0}
    assert _count(db, "execution_log") == 1
    assert sleeps == [0.2, 0.2]  # 5000, 5000, 2000: three batches, a pause after each full one


def test_default_config_keeps_learning_tables_forever(tmp_path: Path) -> None:
    db = _make_learning_db(tmp_path / "p.db")
    old = [NOW - timedelta(days=3 * 365)] * 4
    forever = (
        "slot_observations",
        "slot_plans",
        "slot_forecasts",
        "price_forecasts",
        "learning_runs",
    )
    for table in forever:
        _insert(db, table, old)
    deleted = db_safety.prune(db, RetentionConfig(), now=NOW, pause=0)
    for table in forever:
        assert table not in deleted
        assert _count(db, table) == 4


def test_prune_skips_missing_tables(tmp_path: Path) -> None:
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE s_index_history (id INTEGER PRIMARY KEY, created_at TEXT)")
    conn.commit()
    conn.close()
    assert db_safety.prune(db, RetentionConfig(), now=NOW, pause=0) == {"s_index_history": 0}


def test_prune_propagates_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _make_learning_db(tmp_path / "p.db")
    _insert(db, "execution_log", [NOW - timedelta(days=100)])
    monkeypatch.setattr(db_safety, "_SQLITE_BUSY_TIMEOUT_S", 0.05)
    blocker = sqlite3.connect(db)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db_safety.prune(db, RetentionConfig(), now=NOW, pause=0)
    finally:
        blocker.rollback()
        blocker.close()
    assert _count(db, "execution_log") == 1


# --- compact / incremental_vacuum ------------------------------------------------------------


def _big_db(path: Path, *, old_rows: int = 3000) -> Path:
    db = _make_learning_db(path)
    _insert(db, "execution_log", [NOW - timedelta(days=200)] * old_rows)
    _insert(db, "execution_log", [datetime.now(UTC)] * 10)
    return db


def _backup_file(tmp_path: Path) -> Path:
    path = tmp_path / "backup.db"
    path.write_bytes(b"x")
    return path


def _auto_vacuum(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
    finally:
        conn.close()


def _traced_statements(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    statements: list[str] = []
    real_connect = sqlite3.connect

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn: sqlite3.Connection = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)  # pyright: ignore[reportUnknownMemberType]
        return conn

    monkeypatch.setattr(db_safety.sqlite3, "connect", connect)
    return statements


def test_compact_switches_and_shrinks(tmp_path: Path) -> None:
    db = _big_db(tmp_path / "c.db")
    before = db.stat().st_size
    assert _auto_vacuum(db) == 0
    assert db_safety.compact(db, _backup_file(tmp_path), RetentionConfig()) == "switched"
    assert _auto_vacuum(db) == 2
    assert db.stat().st_size < before
    assert _count(db, "execution_log") == 10


def test_compact_second_call_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _big_db(tmp_path / "c.db")
    backup = _backup_file(tmp_path)
    assert db_safety.compact(db, backup, RetentionConfig()) == "switched"
    statements = _traced_statements(monkeypatch)
    assert db_safety.compact(db, backup, RetentionConfig()) == "skipped"
    assert not any(s.lstrip().upper().startswith(("VACUUM", "DELETE")) for s in statements)


@pytest.mark.parametrize("backup", [None, "", "missing.db"])
def test_compact_skips_without_backup(tmp_path: Path, backup: str | None) -> None:
    db = _big_db(tmp_path / "c.db")
    before = db.read_bytes()
    given = str(tmp_path / backup) if backup else backup
    assert db_safety.compact(db, given, RetentionConfig()) == "skipped"
    assert db.read_bytes() == before


def test_compact_low_space_leaves_file_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing to prune, so the file must be byte-identical after the skip.
    db = _make_learning_db(tmp_path / "c.db")
    _insert(db, "execution_log", [datetime.now(UTC)] * 10)
    before = db.read_bytes()

    # Patch only db_safety's view of shutil: the real module is shared process-wide.
    monkeypatch.setattr(
        db_safety, "shutil", SimpleNamespace(disk_usage=lambda _p: SimpleNamespace(free=1))
    )
    # Capture with a private handler so other tests' logging state (disabled loggers,
    # levels, propagate=False) cannot hide the record.
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = db_safety.logger
    handler = _Collect(level=logging.WARNING)
    monkeypatch.setattr(logger, "disabled", False)
    monkeypatch.setattr(logger, "level", logging.WARNING)
    monkeypatch.setattr(logging.root.manager, "disable", 0)
    logger.addHandler(handler)
    try:
        assert db_safety.compact(db, _backup_file(tmp_path), RetentionConfig()) == "skipped"
    finally:
        logger.removeHandler(handler)
    assert db.read_bytes() == before
    assert any("Not enough free disk space" in r.getMessage() for r in records)


def test_compact_exception_returns_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _big_db(tmp_path / "c.db")

    def boom(*_a: object, **_k: object) -> dict[str, int]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db_safety, "prune", boom)
    assert db_safety.compact(db, _backup_file(tmp_path), RetentionConfig()) == "skipped"
    assert _auto_vacuum(db) == 0


def test_compact_restores_sqlite_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SQLITE_TMPDIR", raising=False)
    db = _big_db(tmp_path / "c.db", old_rows=10)
    assert db_safety.compact(db, _backup_file(tmp_path), RetentionConfig()) == "switched"
    assert "SQLITE_TMPDIR" not in os.environ


def _incremental_db(tmp_path: Path) -> Path:
    db = _big_db(tmp_path / "i.db", old_rows=4000)
    assert (
        db_safety.compact(db, _backup_file(tmp_path), RetentionConfig(execution_log_days=400))
        == "switched"
    )
    return db


def _freelist(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    finally:
        conn.close()


def test_incremental_vacuum_empties_freelist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _incremental_db(tmp_path)
    size = db.stat().st_size
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM execution_log WHERE id <= 2000")
    conn.commit()
    conn.close()
    assert _freelist(db) > 0
    statements = _traced_statements(monkeypatch)
    freed = db_safety.incremental_vacuum(db, pages=10, pause=0)
    assert freed > 0
    assert _freelist(db) == 0
    assert db.stat().st_size < size
    assert not any(s.lstrip().upper().startswith("VACUUM") for s in statements)
    assert any("incremental_vacuum" in s for s in statements)


def test_incremental_vacuum_budget_stops_early(tmp_path: Path) -> None:
    db = _incremental_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM execution_log WHERE id <= 2000")
    conn.commit()
    conn.close()
    before = _freelist(db)
    ticks = iter([0.0, 0.0, 1.0, 999.0, 999.0, 999.0])
    freed = db_safety.incremental_vacuum(
        db, pages=1, pause=0, budget_s=120, clock=lambda: next(ticks)
    )
    assert 0 < freed < before
    assert _freelist(db) == before - freed > 0


def test_incremental_vacuum_noop_when_not_incremental(tmp_path: Path) -> None:
    db = _big_db(tmp_path / "n.db", old_rows=100)
    conn = sqlite3.connect(db)
    conn.execute("DELETE FROM execution_log")
    conn.commit()
    conn.close()
    before = _freelist(db)
    assert db_safety.incremental_vacuum(db, pause=0) == 0
    assert _freelist(db) == before > 0


# --- CLI -------------------------------------------------------------------------------------


def _run_cli(tmp_path: Path, db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "DB_PATH"}
    env["DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "backend.db_safety", *args],
        cwd=tmp_path,  # no config.yaml here: default retention
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_cli_compact_shrinks(tmp_path: Path) -> None:
    db = _big_db(tmp_path / "x.db")
    before = db.stat().st_size
    result = _run_cli(tmp_path, db, "compact", str(_backup_file(tmp_path)))
    assert result.returncode == 0, result.stderr
    assert _auto_vacuum(db) == 2
    assert db.stat().st_size < before
    assert _count(db, "execution_log") == 10


@pytest.mark.parametrize("with_arg", [False, True])
def test_cli_compact_without_backup_skips_and_exits_zero(tmp_path: Path, with_arg: bool) -> None:
    db = _big_db(tmp_path / "x.db")
    before = db.read_bytes()
    result = _run_cli(tmp_path, db, "compact", *([""] if with_arg else []))
    assert result.returncode == 0, result.stderr
    assert db.read_bytes() == before
    assert "No verified backup" in result.stderr


def test_cli_compact_missing_database_exits_zero(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, tmp_path / "none.db", "compact", str(_backup_file(tmp_path)))
    assert result.returncode == 0, result.stderr
