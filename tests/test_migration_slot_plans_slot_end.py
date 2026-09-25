"""Alembic migration b7d4e1f9a2c6: add slot_end to slot_plans."""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PREV_REVISION = "c5e8d2a7f913"
REVISION = "b7d4e1f9a2c6"
COLUMN = "slot_end"
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Config, Path]:
    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg, db_path


def _columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(slot_plans)")}


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT slot_start, planned_charge_kwh, planned_water_heating_kwh, "
            "planned_ev_charging_kwh FROM slot_plans ORDER BY slot_start"
        ).fetchall()


def test_upgrade_adds_nullable_column_and_keeps_data(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO slot_plans (slot_start, planned_charge_kwh, "
            "planned_water_heating_kwh, planned_ev_charging_kwh) VALUES (?, ?, ?, ?)",
            [
                ("2026-09-24T10:00:00+02:00", 0.5, 0.25, 2.75),
                ("2026-09-24T10:15:00+02:00", 0.0, 0.0, None),
            ],
        )
    rows_before = _rows(db_path)

    command.upgrade(cfg, REVISION)

    assert COLUMN in _columns(db_path)
    assert _rows(db_path) == rows_before
    with sqlite3.connect(db_path) as conn:
        values = conn.execute(f"SELECT DISTINCT {COLUMN} FROM slot_plans").fetchall()
    assert values == [(None,)]


def test_second_run_is_noop(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)
    # Re-run the upgrade against a schema that already has the column.
    command.stamp(cfg, PREV_REVISION)

    command.upgrade(cfg, REVISION)

    assert COLUMN in _columns(db_path)


def test_downgrade_removes_column(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREV_REVISION)

    assert COLUMN not in _columns(db_path)
