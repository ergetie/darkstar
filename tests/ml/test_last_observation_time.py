"""get_last_observation_time ignores price-only and future rows.

store_slot_prices writes future day-ahead/forecast price rows into slot_observations;
counting them made the startup backfill think data was up to date and skip gaps.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "obs.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _slot(offset: timedelta) -> datetime:
    now = datetime.now(TZ)
    base = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return base + offset


def _price_row(start: datetime) -> dict:
    return {
        "start_time": start,
        "end_time": start + timedelta(minutes=15),
        "import_price_sek_kwh": 3.0,
        "export_price_sek_kwh": 2.0,
    }


def _observation(start: datetime) -> dict:
    return {
        "slot_start": start,
        "slot_end": start + timedelta(minutes=15),
        "load_kwh": 0.3,
        "pv_kwh": 0.0,
        "import_kwh": 0.3,
        "export_kwh": 0.0,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
    }


@pytest.mark.asyncio
async def test_future_price_rows_do_not_count_as_observations(store):
    last_recorded = _slot(timedelta(hours=-3))
    await store.store_slot_observations(pd.DataFrame([_observation(last_recorded)]))
    await store.store_slot_prices([_price_row(_slot(timedelta(days=d))) for d in (0, 1, 2)])

    result = await store.get_last_observation_time()

    assert result == last_recorded


@pytest.mark.asyncio
async def test_price_rows_only_means_no_observation(store):
    await store.store_slot_prices([_price_row(_slot(timedelta(hours=-1)))])

    assert await store.get_last_observation_time() is None


@pytest.mark.asyncio
async def test_price_merged_into_recorded_slot_still_counts(store):
    slot = _slot(timedelta(minutes=-15))
    await store.store_slot_observations(pd.DataFrame([_observation(slot)]))
    await store.store_slot_prices([_price_row(slot)])

    assert await store.get_last_observation_time() == slot
