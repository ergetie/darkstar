"""Cost series: hourly buckets for a single day with a running net cost that matches /energy/range."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import get_cost_series, get_energy_range
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {"timezone": "Europe/Stockholm"}


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "test_learning.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


async def _add(store: LearningStore, rows: list[dict]) -> None:
    # Yesterday, so every slot has already started whatever time the test runs.
    today = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    async with store.AsyncSession() as session:
        for i, row in enumerate(rows):
            start = TZ.normalize(today + timedelta(minutes=15 * i))
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=(start + timedelta(minutes=15)).isoformat(),
                    **row,
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_hourly_buckets_and_running_net(store):
    # Hour 0: four slots importing 1 kWh at 2.0; hour 1: one slot exporting 2 kWh at 0.5.
    rows = [
        {
            "import_kwh": 1.0,
            "import_price_sek_kwh": 2.0,
            "export_kwh": 0.0,
            "export_price_sek_kwh": 0.5,
        }
    ] * 4
    rows.append(
        {
            "import_kwh": 0.0,
            "import_price_sek_kwh": 2.0,
            "export_kwh": 2.0,
            "export_price_sek_kwh": 0.5,
        }
    )
    await _add(store, rows)

    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
        total = await get_energy_range(period="yesterday", store=store)

    assert series["bucket"] == "hour"
    points = series["points"]
    assert len(points) == 2
    assert points[0]["import_cost_sek"] == pytest.approx(8.0)
    assert points[1]["export_revenue_sek"] == pytest.approx(1.0)
    assert points[1]["cumulative_net_cost_sek"] == pytest.approx(7.0)
    assert points[-1]["cumulative_net_cost_sek"] == pytest.approx(total["net_cost_sek"])


@pytest.mark.asyncio
async def test_multi_day_period_buckets_by_day(store):
    await _add(store, [{"import_kwh": 1.0, "import_price_sek_kwh": 1.0}] * 8)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="week", store=store)
    assert series["bucket"] == "day"
    assert len(series["points"]) == 1
    assert series["points"][0]["import_cost_sek"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_today_excludes_slots_that_have_not_started(store):
    tomorrow = TZ.localize(
        datetime.combine(datetime.now(TZ).date() + timedelta(days=1), datetime.min.time())
    )
    future = TZ.normalize(tomorrow - timedelta(minutes=15))
    async with store.AsyncSession() as session:
        session.add(
            SlotObservation(
                slot_start=future.isoformat(),
                slot_end=tomorrow.isoformat(),
                import_kwh=1.0,
                import_price_sek_kwh=1.0,
            )
        )
        await session.commit()
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="today", store=store)
    assert series["points"] == []


@pytest.mark.asyncio
async def test_invalid_custom_range_returns_error(store):
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(
            period="custom", start_date="2026-10-05", end_date="2026-10-01", store=store
        )
    assert series["points"] == []
    assert "error" in series
