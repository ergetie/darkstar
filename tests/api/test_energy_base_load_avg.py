"""Tests for the base-load daily average served by GET /api/energy/today."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import _base_load_avg_daily_kwh
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
# Mid-slot "now": the current slot starts at 12:00.
NOW = TZ.localize(datetime(2026, 9, 25, 12, 7))
CURRENT_SLOT = TZ.localize(datetime(2026, 9, 25, 12, 0))


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "test_learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


async def _add_slots(store: LearningStore, starts: list[datetime], load_kwh: float | None) -> None:
    async with store.AsyncSession() as session:
        for start in starts:
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=(start + timedelta(minutes=15)).isoformat(),
                    load_kwh=load_kwh,
                )
            )
        await session.commit()


def _completed_slots(n: int) -> list[datetime]:
    """The n most recent completed slots before the current slot."""
    return [CURRENT_SLOT - timedelta(minutes=15 * i) for i in range(1, n + 1)]


@pytest.mark.asyncio
async def test_full_window(store):
    await _add_slots(store, _completed_slots(96), 0.25)
    assert await _base_load_avg_daily_kwh(store, NOW) == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_exactly_87_slots_is_scaled(store):
    await _add_slots(store, _completed_slots(87), 0.25)
    # 87 * 0.25 = 21.75, scaled by 96/87 -> 24.0
    assert await _base_load_avg_daily_kwh(store, NOW) == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_86_slots_is_null(store):
    await _add_slots(store, _completed_slots(86), 0.25)
    assert await _base_load_avg_daily_kwh(store, NOW) is None


@pytest.mark.asyncio
async def test_in_progress_slot_excluded(store):
    await _add_slots(store, _completed_slots(96), 0.25)
    await _add_slots(store, [CURRENT_SLOT], 10.0)
    assert await _base_load_avg_daily_kwh(store, NOW) == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_slots_older_than_24h_excluded(store):
    await _add_slots(store, _completed_slots(96), 0.25)
    older = [CURRENT_SLOT - timedelta(minutes=15 * i) for i in range(97, 110)]
    await _add_slots(store, older, 10.0)
    assert await _base_load_avg_daily_kwh(store, NOW) == pytest.approx(24.0)


@pytest.mark.asyncio
async def test_window_is_96_slots_across_dst_change(store):
    # 2026-10-25 is the Stockholm fall-back day (25 wall-clock hours).
    now = TZ.localize(datetime(2026, 10, 25, 12, 7))
    current_slot = now.astimezone(pytz.utc).replace(minute=0, second=0, microsecond=0)
    in_window = [TZ.normalize((current_slot - timedelta(minutes=15 * i)).astimezone(TZ)) for i in range(1, 97)]
    # Same wall-clock time yesterday is 25 real hours back: outside the window.
    outside = [TZ.normalize((current_slot - timedelta(minutes=15 * i)).astimezone(TZ)) for i in range(97, 101)]
    await _add_slots(store, in_window, 0.25)
    await _add_slots(store, outside, 10.0)
    assert await _base_load_avg_daily_kwh(store, now) == pytest.approx(24.0)
