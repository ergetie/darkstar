"""Backfill never persists fabricated zeros: unavailable history writes no slot_observations row."""

import asyncio
import sqlite3
import pandas as pd
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore
from tests.backend.test_slot_energy_gaps import BASE, SLOT, SOURCES, _backfill_engine, _states


def _rows(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            "SELECT slot_start, load_kwh, pv_kwh, import_kwh, batt_charge_kwh FROM slot_observations"
        ).fetchall()


async def _new_store(tmp_path) -> LearningStore:
    store = LearningStore(str(tmp_path / "learning.db"), pytz.UTC)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return store


def test_unavailable_history_reaches_the_database_as_no_row(tmp_path):
    asyncio.run(_check(tmp_path))


async def _check(tmp_path):
    store = await _new_store(tmp_path)
    engine = _backfill_engine()
    history = {
        "sensor.load": _states([(0, "unavailable"), (2 * 900, "3.0")]),
        "sensor.wh": _states([(0, "unavailable")]),
    }
    slots = [BASE + i * SLOT for i in range(4)]
    records = engine.integrate_slots(SOURCES, None, history, slots)
    await store.store_slot_observations(pd.DataFrame(records), authoritative=False)
    rows = _rows(str(tmp_path / "learning.db"))
    assert [row[0] for row in rows] == [slot.isoformat() for slot in slots[2:]]
    assert all(row[1] == 0.75 for row in rows)

    empty = engine.integrate_slots(
        SOURCES, None, {"sensor.load": _states([(0, "unavailable")])}, slots
    )
    assert empty == []
    await store.store_slot_observations(pd.DataFrame(empty), authoritative=False)
    assert len(_rows(str(tmp_path / "learning.db"))) == 2
