"""Stored forecast rows record when they were last written."""

import asyncio
from datetime import datetime

import pytest
import pytz
from sqlalchemy import select

from backend.learning.models import Base, SlotForecast
from backend.learning.store import LearningStore


async def _read_row(store: LearningStore) -> SlotForecast:
    async with store.AsyncSession() as session:
        return (await session.execute(select(SlotForecast))).scalar_one()


@pytest.mark.asyncio
async def test_forecast_created_at_refreshed_on_overwrite():
    tz = pytz.timezone("Europe/Stockholm")
    store = LearningStore(":memory:", tz)
    try:
        await store.ensure_wal_mode()
        async with store.async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        slot = tz.localize(datetime(2026, 1, 1, 12, 0)).isoformat()
        first = {
            "slot_start": slot,
            "pv_forecast_kwh": 1.0,
            "openmeteo_pv_forecast_kwh": 0.7,
            "load_forecast_kwh": 0.5,
        }
        await store.store_forecasts([first], "aurora")
        row1 = await _read_row(store)
        created1, pv1 = row1.created_at, row1.pv_forecast_kwh
        assert created1 is not None

        await asyncio.sleep(1.1)  # CURRENT_TIMESTAMP has 1 s resolution
        second = {**first, "pv_forecast_kwh": 2.0, "openmeteo_pv_forecast_kwh": None}
        await store.store_forecasts([second], "aurora")
        row2 = await _read_row(store)

        assert pv1 == 1.0
        assert row2.pv_forecast_kwh == 2.0
        assert row2.created_at is not None and row2.created_at > created1
        # Existing coalesce behaviour is unchanged
        assert row2.openmeteo_pv_forecast_kwh == 0.7
    finally:
        await store.async_engine.dispose()
