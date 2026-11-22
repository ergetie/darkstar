"""ORM models for learned parameters create exactly the designed tables."""

import sqlite3
from pathlib import Path

import sqlalchemy as sa

from backend.learning.models import Base

EXPECTED = {
    "learned_parameters": {
        "key",
        "learned_value",
        "confidence",
        "evidence_json",
        "estimated_at",
        "applied_value",
        "applied_at",
        "status_note",
        "locked",
        "locked_value",
        "updated_at",
    },
    "learned_parameter_history": {
        "id",
        "key",
        "at",
        "event",
        "old_value",
        "new_value",
        "confidence",
        "evidence_json",
        "notify_state",
        "notified_at",
    },
    "inverter_loss_observations": {"slot_start", "loss_kwh", "created_at"},
}


def test_create_all_builds_the_three_tables(tmp_path: Path) -> None:
    db = tmp_path / "models.db"
    engine = sa.create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    engine.dispose()

    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table, columns in EXPECTED.items():
            assert table in tables
            assert {r[1] for r in conn.execute(f"PRAGMA table_info({table})")} == columns
        indexes = conn.execute("PRAGMA index_list(learned_parameter_history)").fetchall()
        index_cols = {
            tuple(c[2] for c in conn.execute(f"PRAGMA index_info({i[1]})")) for i in indexes
        }
        assert ("key", "at") in index_cols
