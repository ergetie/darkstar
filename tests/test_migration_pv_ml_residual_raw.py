"""Alembic migration c3a9e5d7b1f2: pv_ml_residual_raw_kwh on slot_forecasts."""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PREV_REVISION = "b7e2c4a9f1d3"
REVISION = "c3a9e5d7b1f2"
COLUMN = "pv_ml_residual_raw_kwh"
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
        return {row[1] for row in conn.execute("PRAGMA table_info(slot_forecasts)")}


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT slot_start, forecast_version, pv_forecast_kwh FROM slot_forecasts "
            "ORDER BY slot_start"
        ).fetchall()


def test_upgrade_adds_nullable_column_and_keeps_data(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    assert COLUMN not in _columns(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO slot_forecasts (slot_start, forecast_version, pv_forecast_kwh, "
            "load_forecast_kwh) VALUES (?, ?, ?, 0.3)",
            [
                ("2026-10-17T10:00:00+02:00", "aurora", 0.5),
                ("2026-10-17T10:15:00+02:00", "aurora", 0.6),
            ],
        )
    rows_before = _rows(db_path)

    command.upgrade(cfg, REVISION)

    assert COLUMN in _columns(db_path)
    assert _rows(db_path) == rows_before
    with sqlite3.connect(db_path) as conn:
        values = conn.execute(f"SELECT DISTINCT {COLUMN} FROM slot_forecasts").fetchall()
    assert values == [(None,)]


def test_downgrade_removes_column_and_keeps_rows(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO slot_forecasts (slot_start, forecast_version, pv_forecast_kwh, "
            f"load_forecast_kwh, {COLUMN}) VALUES ('2026-10-17T10:00:00+02:00', 'aurora', 0.5, 0.3, 0.4)"
        )

    command.downgrade(cfg, PREV_REVISION)

    assert COLUMN not in _columns(db_path)
    assert _rows(db_path) == [("2026-10-17T10:00:00+02:00", "aurora", 0.5)]
