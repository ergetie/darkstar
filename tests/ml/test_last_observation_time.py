"""get_last_observation_time returns the latest completed recorded slot.

store_slot_prices writes future day-ahead/forecast price rows into slot_observations;
counting them made the startup backfill think data was up to date and skip gaps.
All times are fixed and `now` is injected, so the tests do not read the wall clock.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 6, 10, 12, 7, 30))
QUARTER = timedelta(minutes=15)


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "obs.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _price_row(start: datetime) -> dict:
    return {
        "start_time": start,
        "end_time": start + QUARTER,
        "import_price_sek_kwh": 3.0,
        "export_price_sek_kwh": 2.0,
    }


def _observation(start: datetime) -> dict:
    return {
        "slot_start": start,
        "slot_end": start + QUARTER,
        "load_kwh": 0.3,
        "pv_kwh": 0.0,
        "import_kwh": 0.3,
        "export_kwh": 0.0,
        "soc_start_percent": 50.0,
        "soc_end_percent": 50.0,
    }


async def _record(store, *starts: datetime) -> None:
    await store.store_slot_observations(pd.DataFrame([_observation(s) for s in starts]))


@pytest.mark.asyncio
async def test_future_price_rows_do_not_count_as_observations(store):
    last_recorded = TZ.localize(datetime(2026, 6, 10, 9, 0))
    await _record(store, last_recorded)
    await store.store_slot_prices(
        [_price_row(TZ.localize(datetime(2026, 6, 10 + d, 0, 0))) for d in (0, 1, 2)]
    )

    assert await store.get_last_observation_time(NOW) == last_recorded


@pytest.mark.asyncio
async def test_price_rows_only_means_no_observation(store):
    await store.store_slot_prices([_price_row(NOW - timedelta(hours=1))])

    assert await store.get_last_observation_time(NOW) is None


@pytest.mark.asyncio
async def test_price_merged_into_recorded_slot_still_counts(store):
    slot = TZ.localize(datetime(2026, 6, 10, 11, 45))
    await _record(store, slot)
    await store.store_slot_prices([_price_row(slot)])

    assert await store.get_last_observation_time(NOW) == slot


@pytest.mark.asyncio
async def test_slot_in_progress_does_not_count(store):
    completed = TZ.localize(datetime(2026, 6, 10, 11, 45))
    in_progress = NOW - timedelta(minutes=10)  # started 11:57:30
    await _record(store, completed, in_progress)

    assert await store.get_last_observation_time(NOW) == completed


@pytest.mark.asyncio
async def test_slot_exactly_one_slot_old_counts(store):
    now = TZ.localize(datetime(2026, 6, 10, 12, 15))
    slot = TZ.localize(datetime(2026, 6, 10, 12, 0))
    await _record(store, slot)

    assert await store.get_last_observation_time(now) == slot


@pytest.mark.asyncio
async def test_autumn_dst_orders_by_instant(store):
    # 02:30+02:00 (00:30Z) is earlier than 02:15+01:00 (01:15Z) although it sorts later as text.
    first = TZ.localize(datetime(2026, 10, 25, 2, 30), is_dst=True)
    second = TZ.localize(datetime(2026, 10, 25, 2, 15), is_dst=False)
    assert first.isoformat().endswith("+02:00") and second.isoformat().endswith("+01:00")
    await _record(store, first, second)
    now = TZ.localize(datetime(2026, 10, 25, 6, 0))

    assert await store.get_last_observation_time(now) == second


@pytest.mark.asyncio
async def test_autumn_dst_cutoff_compares_instants(store):
    # now = 02:40+01:00 (01:40Z); cutoff 01:25Z. 02:30+02:00 (00:30Z) counts,
    # 02:30+01:00 (01:30Z) is later than the cutoff and must not.
    early = TZ.localize(datetime(2026, 10, 25, 2, 30), is_dst=True)
    late = TZ.localize(datetime(2026, 10, 25, 2, 30), is_dst=False)
    await _record(store, early, late)
    now = TZ.localize(datetime(2026, 10, 25, 2, 40), is_dst=False)

    assert await store.get_last_observation_time(now) == early


@pytest.mark.asyncio
async def test_spring_dst_orders_by_instant(store):
    before = TZ.localize(datetime(2026, 3, 29, 1, 45))  # +01:00
    after = TZ.localize(datetime(2026, 3, 29, 3, 0))  # +02:00, 15 minutes later
    await _record(store, before, after)
    now = TZ.localize(datetime(2026, 3, 29, 5, 0))

    assert await store.get_last_observation_time(now) == after
