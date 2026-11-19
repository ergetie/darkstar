"""The forward pass's temp_c survives the planner's re-upsert of forecast rows.

The planner persists its forecast_data (no weather keys) every run; without COALESCE
that wiped temp_c across the whole price horizon.
"""

import sqlite3
from datetime import datetime

import pytest
import pytest_asyncio
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 11, 19, 12, 0))


@pytest_asyncio.fixture
async def store(tmp_path):
    store = LearningStore(str(tmp_path / "temp.db"), TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield store
    await store.close()


def _forward_row(**overrides):
    row = {"slot_start": START, "pv_forecast_kwh": 0.1, "load_forecast_kwh": 0.4, "temp_c": 1.5}
    row.update(overrides)
    return row


def _planner_row(**overrides):
    # Shape of backend.core.forecasts.get_forecast_data slots: start_time, no temp_c.
    row = {"start_time": START, "pv_forecast_kwh": 0.1, "load_forecast_kwh": 0.4}
    row.update(overrides)
    return row


def _stored_temp(store) -> float | None:
    with sqlite3.connect(store.db_path) as conn:
        return conn.execute("SELECT temp_c FROM slot_forecasts").fetchone()[0]


@pytest.mark.asyncio
async def test_planner_reupsert_keeps_forward_temperature(store):
    await store.store_forecasts([_forward_row()], forecast_version="aurora")
    await store.store_forecasts([_planner_row()], forecast_version="aurora")

    assert _stored_temp(store) == pytest.approx(1.5)


@pytest.mark.asyncio
async def test_new_forward_temperature_overwrites(store):
    await store.store_forecasts([_forward_row()], forecast_version="aurora")
    await store.store_forecasts([_forward_row(temp_c=-2.0)], forecast_version="aurora")

    assert _stored_temp(store) == pytest.approx(-2.0)
