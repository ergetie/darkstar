"""The raw ML residual survives the planner's re-upsert of forecast rows."""

import sqlite3
from datetime import datetime

import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 6, 15, 12, 0))


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "residual.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _row(**overrides):
    row = {
        "slot_start": START,
        "pv_forecast_kwh": 1.0,
        "openmeteo_pv_forecast_kwh": 0.9,
        "load_forecast_kwh": 0.3,
    }
    row.update(overrides)
    return row


def _stored_residual(store) -> float | None:
    with sqlite3.connect(store.db_path) as conn:
        return conn.execute("SELECT pv_ml_residual_raw_kwh FROM slot_forecasts").fetchone()[0]


@pytest.mark.asyncio
async def test_reupsert_without_residual_keeps_stored_value(store):
    await store.store_forecasts([_row(pv_ml_residual_raw_kwh=0.12)], forecast_version="aurora")
    await store.store_forecasts([_row(pv_forecast_kwh=1.1)], forecast_version="aurora")

    assert _stored_residual(store) == pytest.approx(0.12)


@pytest.mark.asyncio
async def test_reupsert_with_residual_overwrites(store):
    await store.store_forecasts([_row(pv_ml_residual_raw_kwh=0.12)], forecast_version="aurora")
    await store.store_forecasts([_row(pv_ml_residual_raw_kwh=0.30)], forecast_version="aurora")

    assert _stored_residual(store) == pytest.approx(0.30)
