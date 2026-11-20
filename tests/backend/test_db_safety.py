"""Backup, pending detection, pruning, restore and CLI of backend.db_safety."""

import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic.config import Config

from alembic import command
from backend import db_safety

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _make_db(path: Path, *, wal: bool = False, rows: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    if wal:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    return path


def _stamp(path: Path, *revisions: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("DELETE FROM alembic_version")
    conn.executemany("INSERT INTO alembic_version VALUES (?)", [(r,) for r in revisions])
    conn.commit()
    conn.close()


def _values(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def heads() -> set[str]:
    return db_safety.script_heads(REPO_ROOT / "alembic.ini")


@pytest.fixture
def two_head_ini(tmp_path: Path) -> Path:
    versions = tmp_path / "alembic_two" / "versions"
    versions.mkdir(parents=True)
    for rev in ("aaa111", "bbb222"):
        (versions / f"{rev}_x.py").write_text(
            f'revision = "{rev}"\ndown_revision = None\nbranch_labels = None\n'
            "depends_on = None\n\ndef upgrade():\n    pass\n\ndef downgrade():\n    pass\n"
        )
    ini = tmp_path / "two.ini"
    ini.write_text(f"[alembic]\nscript_location = {tmp_path / 'alembic_two'}\n")
    return ini


# --- 1.2 pending detection ---------------------------------------------------------


def test_fresh_install_is_not_pending(tmp_path: Path) -> None:
    missing = tmp_path / "none.db"
    empty = tmp_path / "empty.db"
    empty.touch()
    for db in (missing, empty):
        assert db_safety.migration_pending(db) is False
        assert db_safety.switch_pending(db) is False


def test_at_head_is_not_pending(tmp_path: Path, heads: set[str]) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, *heads)
    assert db_safety.migration_pending(db) is False


def test_behind_is_pending(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, "000000000000")
    assert db_safety.migration_pending(db) is True


def test_legacy_without_version_table_is_pending(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    assert db_safety.migration_pending(db) is True


def test_multi_head_compares_sets(tmp_path: Path, two_head_ini: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, "aaa111", "bbb222")
    assert db_safety.migration_pending(db, two_head_ini) is False
    _stamp(db, "aaa111")
    assert db_safety.migration_pending(db, two_head_ini) is True


def test_pending_check_does_not_modify_database(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    before = db.read_bytes()
    db_safety.migration_pending(db)
    db_safety.switch_pending(db)
    assert db.read_bytes() == before


def test_switch_pending_follows_auto_vacuum(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()
    assert db_safety.switch_pending(db) is False
    assert db_safety.switch_pending(_make_db(tmp_path / "b.db")) is True


def test_real_alembic_head_matches_upgraded_database(tmp_path: Path) -> None:
    db = tmp_path / "up.db"
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    old = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = str(db)
    try:
        command.upgrade(cfg, "head")
    finally:
        if old is None:
            os.environ.pop("DB_PATH")
        else:
            os.environ["DB_PATH"] = old
    assert db_safety.migration_pending(db) is False


# --- 1.3 create_backup -------------------------------------------------------------


def test_backup_contains_wal_only_rows(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "data" / "live.db", wal=True)
    _stamp(db, "abc123")
    keeper = sqlite3.connect(db)  # keeps the WAL alive
    keeper.execute("PRAGMA wal_autocheckpoint=0")
    keeper.execute("INSERT INTO t (v) VALUES ('wal-only')")
    keeper.commit()
    assert (tmp_path / "data" / "live.db-wal").stat().st_size > 0
    try:
        backup = db_safety.create_backup(db)
    finally:
        keeper.close()
    assert backup.parent == tmp_path / "data" / "backups"
    assert backup.name.startswith("pre-migration-") and backup.name.endswith("-abc123.db")
    assert "wal-only" in _values(backup)
    assert not list(backup.parent.glob("*-wal"))
    assert [p.name for p in backup.parent.iterdir()] == [backup.name]


def test_backup_label_without_revision(tmp_path: Path) -> None:
    backup = db_safety.create_backup(_make_db(tmp_path / "a.db"))
    assert backup.name.endswith("-none.db")


def test_failed_verification_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _make_db(tmp_path / "a.db")

    def corrupt(_conn: sqlite3.Connection) -> str:
        return "*** corrupt page 7"

    monkeypatch.setattr(db_safety, "_quick_check", corrupt)
    with pytest.raises(db_safety.BackupError, match="verification"):
        db_safety.create_backup(db)
    assert list((tmp_path / "backups").iterdir()) == []


def test_insufficient_space_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _make_db(tmp_path / "a.db")

    def tiny_disk(_path: Path) -> SimpleNamespace:
        return SimpleNamespace(free=1)

    monkeypatch.setattr(db_safety.shutil, "disk_usage", tiny_disk)
    with pytest.raises(db_safety.BackupError, match="free disk space"):
        db_safety.create_backup(db)
    assert list((tmp_path / "backups").iterdir()) == []


def test_missing_database_cannot_be_backed_up(tmp_path: Path) -> None:
    with pytest.raises(db_safety.BackupError):
        db_safety.create_backup(tmp_path / "nope.db")


# --- 1.4 prune_backups -------------------------------------------------------------


def test_prune_keeps_three_newest_and_ignores_others(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    names = [f"pre-migration-2026010{i}T000000Z-rev.db" for i in range(1, 6)]
    others = ["planner_learning_20260101_000000.db.bak", "manual.db", "pre-migration-x.db.bak"]
    for name in names + others:
        (folder / name).write_text(name)

    deleted = db_safety.prune_backups(folder)

    assert sorted(p.name for p in deleted) == names[:2]
    assert sorted(p.name for p in folder.iterdir()) == sorted(names[2:] + others)


def test_prune_missing_folder_is_noop(tmp_path: Path) -> None:
    assert db_safety.prune_backups(tmp_path / "absent") == []


# --- 1.5 restore_backup ------------------------------------------------------------


def test_restore_replaces_db_and_drops_stale_wal(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "live.db", wal=True)
    backup = db_safety.create_backup(db)

    keeper = sqlite3.connect(db)
    keeper.execute("PRAGMA wal_autocheckpoint=0")
    keeper.execute("INSERT INTO t (v) VALUES ('after-backup')")
    keeper.commit()
    wal = tmp_path / "live.db-wal"
    assert wal.exists()
    # Snapshot the files as a crashed process would leave them.
    stale = {p: p.read_bytes() for p in (wal, tmp_path / "live.db-shm") if p.exists()}
    keeper.close()
    for path, data in stale.items():
        path.write_bytes(data)

    db_safety.restore_backup(db, backup)

    assert not wal.exists()
    assert not (tmp_path / "live.db-shm").exists()
    assert not (tmp_path / "live.db.restore.tmp").exists()
    assert _values(db) == ["row0", "row1", "row2"]


def test_restore_missing_backup_leaves_db(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "live.db")
    before = db.read_bytes()
    with pytest.raises(FileNotFoundError):
        db_safety.restore_backup(db, tmp_path / "missing.db")
    assert db.read_bytes() == before


# --- 1.6 CLI -----------------------------------------------------------------------


def _cli(
    tmp_path: Path, *args: str, db: Path, prelude: str = ""
) -> subprocess.CompletedProcess[str]:
    code = textwrap.dedent(
        f"""
        import sys
        {prelude}
        from backend.db_safety import main
        sys.exit(main({list(args)!r}))
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "DB_PATH"}
    env["DB_PATH"] = str(db)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_cli_nothing_pending(tmp_path: Path, heads: set[str]) -> None:
    db = _make_db(tmp_path / "a.db")
    conn = sqlite3.connect(db)
    conn.execute("VACUUM")  # keep auto_vacuum 0 ...
    conn.close()
    # ... so make the switch not pending by creating an incremental database at head.
    inc = tmp_path / "inc.db"
    conn = sqlite3.connect(inc)
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
    conn.execute("CREATE TABLE t (id INTEGER, v TEXT)")
    conn.commit()
    conn.close()
    _stamp(inc, *heads)

    result = _cli(tmp_path, "pre-migrate", db=inc)

    assert result.returncode == 0
    assert result.stdout == ""
    assert not (tmp_path / "backups").exists()


def test_cli_fresh_install(tmp_path: Path) -> None:
    result = _cli(tmp_path, "pre-migrate", db=tmp_path / "new" / "x.db")
    assert result.returncode == 0
    assert result.stdout == ""
    assert not (tmp_path / "new" / "backups").exists()


def test_cli_migration_pending_prints_backup_path(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, "000000000000")

    result = _cli(tmp_path, "pre-migrate", db=db)

    assert result.returncode == 0
    backup = Path(result.stdout.strip())
    assert backup.parent == tmp_path / "backups"
    assert _values(backup) == ["row0", "row1", "row2"]


def test_cli_prunes_to_three(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    folder = tmp_path / "backups"
    folder.mkdir()
    for i in range(1, 5):
        (folder / f"pre-migration-2020010{i}T000000Z-old.db").write_text("x")

    result = _cli(tmp_path, "pre-migrate", db=db)

    assert result.returncode == 0
    assert len(list(folder.glob("pre-migration-*.db"))) == 3


_NO_SPACE = "import shutil, types; shutil.disk_usage = lambda _p: types.SimpleNamespace(free=1)"


def test_cli_insufficient_space_aborts_pending_migration(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, "000000000000")
    before = db.read_bytes()

    result = _cli(tmp_path, "pre-migrate", db=db, prelude=_NO_SPACE)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "free disk space" in result.stderr
    assert db.read_bytes() == before
    assert list((tmp_path / "backups").glob("pre-migration-*")) == []


def test_cli_switch_only_backup_failure_is_not_fatal(tmp_path: Path, heads: set[str]) -> None:
    db = _make_db(tmp_path / "a.db")
    _stamp(db, *heads)

    result = _cli(tmp_path, "pre-migrate", db=db, prelude=_NO_SPACE)

    assert result.returncode == 0
    assert result.stdout == ""
    assert "skipping" in result.stderr


def test_cli_restore(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    backup = db_safety.create_backup(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO t (v) VALUES ('later')")
    conn.commit()
    conn.close()

    result = _cli(tmp_path, "restore", str(backup), db=db)

    assert result.returncode == 0
    assert _values(db) == ["row0", "row1", "row2"]


def test_cli_restore_missing_backup_fails(tmp_path: Path) -> None:
    db = _make_db(tmp_path / "a.db")
    result = _cli(tmp_path, "restore", str(tmp_path / "missing.db"), db=db)
    assert result.returncode == 1
    assert _values(db) == ["row0", "row1", "row2"]


def test_documented_restore_command_works(tmp_path: Path) -> None:
    """docs/OPERATIONS.md: `python -m backend.db_safety restore data/backups/<file>` (cwd = app dir)."""
    db = _make_db(tmp_path / "data" / "planner_learning.db")
    backup = db_safety.create_backup(db)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO t (v) VALUES ('later')")
    conn.commit()
    conn.close()
    env = {k: v for k, v in os.environ.items() if k != "DB_PATH"}
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        [sys.executable, "-m", "backend.db_safety", "restore", f"data/backups/{backup.name}"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert _values(db) == ["row0", "row1", "row2"]
