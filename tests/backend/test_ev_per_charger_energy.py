"""Per-charger recorded EV energy (ev-per-charger-energy)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
import pytz
from sqlalchemy import select

from backend.learning.models import Base, EvChargerObservation, SlotObservation
from backend.learning.store import LearningStore
from planner.pipeline import _ev_delivered_today_kwh

TZ = pytz.timezone("Europe/Stockholm")
DAY = TZ.localize(datetime(2026, 9, 26, 0, 0))


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _record(start: datetime, per_charger: dict[str, float] | None) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "slot_start": start,
                "slot_end": start + timedelta(minutes=15),
                "import_kwh": 1.0,
                "ev_charging_kwh": sum((per_charger or {}).values()),
                "ev_charger_energy": per_charger,
            }
        ]
    )


async def _rows(store: LearningStore) -> list[tuple[str, str, float]]:
    async with store.AsyncSession() as session:
        result = await session.execute(
            select(
                EvChargerObservation.slot_start,
                EvChargerObservation.charger_id,
                EvChargerObservation.energy_kwh,
            ).order_by(EvChargerObservation.slot_start, EvChargerObservation.charger_id)
        )
        return [tuple(r) for r in result.all()]


@pytest.mark.asyncio
async def test_two_chargers_recorded(store):
    start = DAY + timedelta(hours=1)
    await store.store_slot_observations(_record(start, {"ev1": 1.2, "ev2": 0.8}))

    rows = await _rows(store)
    assert [(c, e) for _, c, e in rows] == [("ev1", 1.2), ("ev2", 0.8)]
    async with store.AsyncSession() as session:
        slot = (await session.execute(select(SlotObservation))).scalar_one()
    assert slot.ev_charging_kwh == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_re_record_replaces_rows(store):
    start = DAY + timedelta(hours=1)
    await store.store_slot_observations(_record(start, {"ev1": 1.2, "ev2": 0.8}))
    await store.store_slot_observations(_record(start, {"ev1": 1.5}))

    rows = await _rows(store)
    assert [(c, e) for _, c, e in rows] == [("ev1", 1.5)]


@pytest.mark.asyncio
async def test_backfill_does_not_touch_per_charger_rows(store):
    start = DAY + timedelta(hours=1)
    await store.store_slot_observations(_record(start, {"ev1": 1.2}))
    backfill = _record(start, None).drop(columns=["ev_charger_energy"])
    await store.store_slot_observations(backfill, authoritative=False)

    assert len(await _rows(store)) == 1


@pytest.mark.asyncio
async def test_delivered_today_is_per_charger(store):
    for i in range(4):
        start = DAY + timedelta(hours=8, minutes=15 * i)
        await store.store_slot_observations(_record(start, {"ev1": 1.25, "ev2": 0.75}))
    # Yesterday's energy never counts toward today.
    await store.store_slot_observations(_record(DAY - timedelta(hours=1), {"ev1": 9.0}))

    now = DAY + timedelta(hours=12)
    assert _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now) == pytest.approx(5.0)
    assert _ev_delivered_today_kwh(store.db_path, "ev2", TZ, now) == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_delivered_honours_effective_now(store):
    for i in range(4):
        start = DAY + timedelta(hours=8, minutes=15 * i)
        await store.store_slot_observations(_record(start, {"ev1": 1.0}))

    # A now_override inside the block only counts the slots before it.
    now = DAY + timedelta(hours=8, minutes=30)
    assert _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now) == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_delivered_unknown_without_rows(store, tmp_path):
    now = DAY + timedelta(hours=12)
    assert _ev_delivered_today_kwh(store.db_path, "ev1", TZ, now) is None
    # A database from before the migration (no table) is unknown too.
    assert _ev_delivered_today_kwh(str(tmp_path / "empty.db"), "ev1", TZ, now) is None
