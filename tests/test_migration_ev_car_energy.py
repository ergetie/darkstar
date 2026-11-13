"""Alembic migration b7e2c4a9f1d3: car-side energy on ev_charger_observations."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

from alembic.config import Config

from alembic import command

PREV_REVISION = "d2a6f1c8e4b7"
REVISION = "b7e2c4a9f1d3"
NEW_COLUMNS = {"car_energy_kwh", "car_energy_source"}
REPO_ROOT = Path(__file__).resolve().parent.parent
AlembicDbFactory = Callable[[str], tuple[Config, Path]]


def _columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(ev_charger_observations)")}


def test_upgrade_adds_nullable_columns_and_keeps_data(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(PREV_REVISION)
    assert not NEW_COLUMNS & _columns(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO ev_charger_observations (slot_start, charger_id, energy_kwh) "
            "VALUES ('2026-10-11T10:00:00+02:00', 'ev1', 1.5)"
        )

    command.upgrade(cfg, REVISION)

    assert _columns(db_path) >= NEW_COLUMNS
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT energy_kwh, car_energy_kwh, car_energy_source FROM ev_charger_observations"
        ).fetchall()
    assert rows == [(1.5, None, None)]


def test_downgrade_removes_columns(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(REVISION)

    command.downgrade(cfg, PREV_REVISION)

    assert not NEW_COLUMNS & _columns(db_path)
