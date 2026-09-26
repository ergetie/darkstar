"""Alembic migration a3f5c7e9b1d2: add ev_charger_observations table."""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PREV_REVISION = "b7d4e1f9a2c6"
REVISION = "a3f5c7e9b1d2"
TABLE = "ev_charger_observations"
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg, db_path


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_creates_table_with_composite_key(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    assert TABLE not in _tables(db_path)

    command.upgrade(cfg, REVISION)

    assert TABLE in _tables(db_path)
    with sqlite3.connect(db_path) as conn:
        cols = {row[1]: row[5] for row in conn.execute(f"PRAGMA table_info({TABLE})")}
        assert set(cols) == {"slot_start", "charger_id", "energy_kwh", "created_at"}
        assert cols["slot_start"] == 1 and cols["charger_id"] == 2
        conn.execute(f"INSERT INTO {TABLE} (slot_start, charger_id, energy_kwh) VALUES ('s', 'ev1', 1.0)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"INSERT INTO {TABLE} (slot_start, charger_id, energy_kwh) VALUES ('s', 'ev1', 2.0)"
            )


def test_second_run_is_noop(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)
    command.stamp(cfg, PREV_REVISION)

    command.upgrade(cfg, REVISION)

    assert TABLE in _tables(db_path)


def test_downgrade_drops_table(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREV_REVISION)

    assert TABLE not in _tables(db_path)
