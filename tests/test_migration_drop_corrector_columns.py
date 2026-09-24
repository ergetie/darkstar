"""Alembic migration bb3329253f22: drop dead corrector columns from slot_forecasts."""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PREV_REVISION = "b7c9d1e2f3a4"
REVISION = "bb3329253f22"
DEAD_COLUMNS = {"pv_correction_kwh", "load_correction_kwh", "correction_source"}
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


def _unique_constraints(db_path: Path) -> list[list[str]]:
    with sqlite3.connect(db_path) as conn:
        indexes = conn.execute("PRAGMA index_list(slot_forecasts)").fetchall()
        return sorted(
            [row[2] for row in conn.execute(f"PRAGMA index_info('{idx[1]}')")]
            for idx in indexes
            if idx[2]  # unique
        )


def _seed(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO slot_forecasts (slot_start, pv_forecast_kwh, load_forecast_kwh, "
            "pv_p10, forecast_version, pv_correction_kwh, load_correction_kwh, "
            "correction_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("2026-03-10T10:00:00+01:00", 1.5, 0.7, 1.1, "aurora", 0.2, 0.1, "ml"),
                ("2026-03-10T10:15:00+01:00", 1.6, 0.8, None, "aurora", 0.0, 0.0, "none"),
                ("2026-03-10T10:00:00+01:00", 1.4, 0.6, 1.0, "baseline_7_day_avg", 0, 0, "none"),
            ],
        )


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, pv_p10, forecast_version "
            "FROM slot_forecasts ORDER BY slot_start, forecast_version"
        ).fetchall()


def test_upgrade_drops_columns_and_keeps_data(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    assert DEAD_COLUMNS <= _columns(db_path)
    _seed(db_path)
    rows_before = _rows(db_path)
    uniques_before = _unique_constraints(db_path)

    command.upgrade(cfg, REVISION)

    assert not DEAD_COLUMNS & _columns(db_path)
    assert _rows(db_path) == rows_before
    assert _unique_constraints(db_path) == uniques_before
    assert ["slot_start", "forecast_version"] in uniques_before


def test_upgrade_is_noop_when_columns_absent(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)
    columns_after_first = _columns(db_path)

    # Re-run the revision's upgrade against a DB that already lacks the columns.
    command.stamp(cfg, PREV_REVISION)
    command.upgrade(cfg, REVISION)

    assert _columns(db_path) == columns_after_first


def test_downgrade_restores_columns_with_defaults(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    _seed(db_path)
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREV_REVISION)

    assert DEAD_COLUMNS <= _columns(db_path)
    with sqlite3.connect(db_path) as conn:
        values = conn.execute(
            "SELECT DISTINCT pv_correction_kwh, load_correction_kwh, correction_source "
            "FROM slot_forecasts"
        ).fetchall()
    assert values == [(0, 0, "none")]
