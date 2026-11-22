"""Alembic migration d4b8f2a6c1e9: learned parameter tables, drop Reflex tables."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

from alembic.config import Config

from alembic import command

PREV_REVISION = "c3a9e5d7b1f2"
REVISION = "d4b8f2a6c1e9"
NEW_TABLES = {"learned_parameters", "learned_parameter_history", "inverter_loss_observations"}
OLD_TABLES = {"reflex_state", "learning_daily_metrics"}
AlembicDbFactory = Callable[[str], tuple[Config, Path]]


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_creates_new_and_drops_old_tables(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(PREV_REVISION)
    assert OLD_TABLES <= _tables(db_path)

    command.upgrade(cfg, REVISION)

    tables = _tables(db_path)
    assert NEW_TABLES <= tables
    assert not OLD_TABLES & tables


def test_stale_base_factor_row_is_gone_after_upgrade(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(PREV_REVISION)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO learning_daily_metrics (date, s_index_base_factor) "
            "VALUES ('2026-03-15', 1.4066)"
        )

    command.upgrade(cfg, REVISION)

    assert "learning_daily_metrics" not in _tables(db_path)


def test_second_run_is_noop(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(REVISION)
    command.stamp(cfg, PREV_REVISION)

    command.upgrade(cfg, REVISION)

    assert NEW_TABLES <= _tables(db_path)
    assert not OLD_TABLES & _tables(db_path)


def test_downgrade_restores_old_tables_empty(alembic_db: AlembicDbFactory) -> None:
    cfg, db_path = alembic_db(REVISION)

    command.downgrade(cfg, PREV_REVISION)

    tables = _tables(db_path)
    assert OLD_TABLES <= tables
    assert not NEW_TABLES & tables
    with sqlite3.connect(db_path) as conn:
        for table in OLD_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
