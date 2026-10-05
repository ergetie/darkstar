"""Alembic migration d2a6f1c8e4b7: add known_prices_until to price_forecasts."""

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

PREV_REVISION = "a3f5c7e9b1d2"
REVISION = "d2a6f1c8e4b7"
COLUMN = "known_prices_until"
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
        return {row[1] for row in conn.execute("PRAGMA table_info(price_forecasts)")}


def _rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT slot_start, issue_timestamp, days_ahead, spot_p50 "
            "FROM price_forecasts ORDER BY slot_start"
        ).fetchall()


def test_upgrade_adds_nullable_column_and_keeps_data(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, PREV_REVISION)
    assert COLUMN not in _columns(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO price_forecasts (slot_start, issue_timestamp, days_ahead, spot_p50) "
            "VALUES (?, ?, ?, ?)",
            [
                ("2026-10-05T10:00:00+02:00", "2026-10-04T06:00:00+02:00", 1, 0.5),
                ("2026-10-05T10:15:00+02:00", "2026-10-04T06:00:00+02:00", 1, 0.6),
            ],
        )
    rows_before = _rows(db_path)

    command.upgrade(cfg, REVISION)

    assert COLUMN in _columns(db_path)
    assert _rows(db_path) == rows_before
    with sqlite3.connect(db_path) as conn:
        values = conn.execute(f"SELECT DISTINCT {COLUMN} FROM price_forecasts").fetchall()
    assert values == [(None,)]


def test_downgrade_removes_column(alembic_db: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_db
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREV_REVISION)

    assert COLUMN not in _columns(db_path)
