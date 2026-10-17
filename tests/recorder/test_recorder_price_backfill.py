"""Price backfill of unpriced slots: completeness, no overwrite, idempotence."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import pytz
from sqlalchemy import select

from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore
from backend.recorder import backfill_missing_prices

TZ = pytz.timezone("Europe/Stockholm")


def _base() -> datetime:
    day = datetime.now(TZ).date() - timedelta(days=1)
    return TZ.localize(datetime.combine(day, datetime.min.time()))


def _slot(i: int) -> datetime:
    return (_base().astimezone(pytz.UTC) + timedelta(minutes=15 * i)).astimezone(TZ)


@pytest_asyncio.fixture
async def db_path(tmp_path):
    path = str(tmp_path / "learning.db")
    store = LearningStore(path, TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await store.close()
    return path


async def _seed(path: str, rows: dict[int, tuple[float | None, float | None]]) -> None:
    store = LearningStore(path, TZ)
    async with store.AsyncSession() as session:
        for i, (imp, exp) in rows.items():
            start = _slot(i)
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=_slot(i + 1).isoformat(),
                    import_price_sek_kwh=imp,
                    export_price_sek_kwh=exp,
                )
            )
        await session.commit()
    await store.close()


async def _prices(path: str) -> dict[str, tuple[float | None, float | None]]:
    store = LearningStore(path, TZ)
    async with store.AsyncSession() as session:
        result = await session.execute(
            select(
                SlotObservation.slot_start,
                SlotObservation.import_price_sek_kwh,
                SlotObservation.export_price_sek_kwh,
            )
        )
        out = {r[0]: (r[1], r[2]) for r in result.all()}
    await store.close()
    return out


def _nordpool(indices: list[int]) -> list[dict]:
    return [
        {
            "start_time": _slot(i),
            "import_price_sek_kwh": 10.0 + i,
            "export_price_sek_kwh": 5.0 + i,
        }
        for i in indices
    ]


async def _run(path: str, indices: list[int]) -> AsyncMock:
    config = {"learning": {"sqlite_path": path}, "timezone": "Europe/Stockholm"}
    nordpool = AsyncMock(return_value=_nordpool(indices))
    with (
        patch("backend.recorder._load_config", return_value=config),
        patch("backend.core.prices.get_nordpool_data", nordpool),
        patch.object(
            LearningStore, "store_slot_prices", autospec=True, side_effect=LearningStore.store_slot_prices
        ) as spy,
    ):
        await backfill_missing_prices()
    return spy


async def test_get_history_range_returns_export_price(db_path):
    await _seed(db_path, {0: (1.5, 0.7)})
    store = LearningStore(db_path, TZ)
    rows = await store.get_history_range(_slot(0) - timedelta(hours=1), _slot(1))
    await store.close()
    assert rows[0]["export_price_sek_kwh"] == 0.7
    assert rows[0]["import_price_sek_kwh"] == 1.5


async def test_gap_slots_filled_next_to_priced_slots(db_path):
    await _seed(db_path, {0: (1.0, 0.5), 1: (None, None), 2: (2.0, 0.6), 3: (None, None)})
    spy = await _run(db_path, [0, 1, 2, 3])

    prices = await _prices(db_path)
    assert prices[_slot(1).isoformat()] == (11.0, 6.0)
    assert prices[_slot(3).isoformat()] == (13.0, 8.0)
    # Existing prices untouched, and only patched slots were sent to storage
    assert prices[_slot(0).isoformat()] == (1.0, 0.5)
    assert prices[_slot(2).isoformat()] == (2.0, 0.6)
    sent = spy.call_args.args[1]
    assert {r["slot_start"] for r in sent} == {_slot(1).isoformat(), _slot(3).isoformat()}


async def test_existing_export_price_kept_when_import_missing(db_path):
    await _seed(db_path, {0: (None, 0.9)})
    await _run(db_path, [0])
    assert (await _prices(db_path))[_slot(0).isoformat()] == (10.0, 0.9)


async def test_slot_without_nordpool_price_stays_unpriced(db_path):
    await _seed(db_path, {0: (None, None), 1: (None, None), 2: (None, None)})
    await _run(db_path, [0, 2])
    prices = await _prices(db_path)
    assert prices[_slot(0).isoformat()] == (10.0, 5.0)
    assert prices[_slot(1).isoformat()] == (None, None)
    assert prices[_slot(2).isoformat()] == (12.0, 7.0)


async def test_backfill_is_idempotent(db_path):
    await _seed(db_path, {0: (None, None), 1: (1.0, 0.5)})
    await _run(db_path, [0, 1])
    before = await _prices(db_path)
    spy = await _run(db_path, [0, 1])
    assert spy.call_count == 0
    assert await _prices(db_path) == before
