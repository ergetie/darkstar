import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from script_stubs import dump_db, log_lines, make_behind_db, make_stub_bin, run_script


def test_production_entrypoint_does_not_launch_standalone_recorder():
    """Spec: Single Live Recorder Instance - entrypoint relies on in-process recorder."""
    entrypoint = Path("scripts/docker-entrypoint.sh").read_text(encoding="utf-8")

    assert "python -m backend.recorder" not in entrypoint
    assert "[RECORDER]" not in entrypoint
    assert entrypoint.count("uvicorn backend.main:app") == 1


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "docker-entrypoint.sh"


def test_entrypoint_uses_db_safety_instead_of_raw_copy():
    text = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'cp "$DB_FILE"' not in text
    assert "/data/planner_learning.db" not in text
    assert "/data/backups" not in text
    assert "python3 -m backend.db_safety pre-migrate" in text
    assert 'python3 -m backend.db_safety restore "$DB_BACKUP"' in text
    assert 'python3 -m backend.db_safety compact "$DB_BACKUP"' in text
    # backup, then migrate, then compact
    assert (
        text.index("db_safety pre-migrate")
        < text.index("alembic upgrade head")
        < text.index("db_safety compact")
    )


def test_entrypoint_syntax():
    result = subprocess.run(
        ["bash", "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def app(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    for name in ("config.yaml", "secrets.yaml"):
        (app_dir / name).write_text("{}\n", encoding="utf-8")
    (app_dir / "alembic.ini").write_text("", encoding="utf-8")
    (app_dir / "VERSION").write_text("0.0.0\n", encoding="utf-8")
    db = app_dir / "data" / "planner_learning.db"
    return SimpleNamespace(
        dir=app_dir,
        db=db,
        backups=db.parent / "backups",
        bin=make_stub_bin(tmp_path / "bin"),
        log=tmp_path / "calls.log",
    )


def _run(app, *, alembic_fails=False):
    return run_script(
        ENTRYPOINT,
        cwd=app.dir,
        stub_bin=app.bin,
        log=app.log,
        env={"APP_DIR": str(app.dir), "DB_PATH": str(app.db)},
        alembic_fails=alembic_fails,
    )


def test_failed_migration_restores_backup_and_exits_nonzero(app):
    make_behind_db(app.db)
    before = dump_db(app.db)

    result = _run(app, alembic_fails=True)

    assert result.returncode == 1, result.stdout + result.stderr
    assert dump_db(app.db) == before  # half-migrated table is gone
    assert len(list(app.backups.glob("pre-migration-*.db"))) == 1
    assert "Database restored from backup" in result.stdout
    calls = log_lines(app.log)
    assert calls == ["alembic upgrade head"]  # no compact, server not started


def test_successful_migration_compacts_with_backup_path(app):
    make_behind_db(app.db)

    result = _run(app)

    assert result.returncode == 0, result.stdout + result.stderr
    (backup,) = app.backups.glob("pre-migration-*.db")
    assert log_lines(app.log) == [
        "alembic upgrade head",
        f"compact -m backend.db_safety compact {backup}",
        "uvicorn backend.main:app --host 0.0.0.0 --port 5000 --log-level info",
    ]


def test_backup_failure_aborts_before_migration(app):
    make_behind_db(app.db)
    app.backups.write_text("not a directory", encoding="utf-8")
    before = dump_db(app.db)

    result = _run(app)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "migration aborted" in result.stdout
    assert dump_db(app.db) == before
    assert log_lines(app.log) == []  # alembic never ran


def test_fresh_install_makes_no_backup_and_passes_empty_path(app):
    result = _run(app)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not app.backups.exists()
    calls = log_lines(app.log)
    assert calls[0] == "alembic upgrade head"
    assert calls[1].rstrip() == "compact -m backend.db_safety compact"
