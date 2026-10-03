"""EV attribution in the energy endpoints: solar bounded by PV surplus, grid is the remainder,
EV cost is grid import cost only (capped at the slot's import)."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import get_energy_range
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
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
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


async def _range(store: LearningStore) -> dict:
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        return await get_energy_range(period="today", store=store)


P = dict(import_price_sek_kwh=2.0, export_price_sek_kwh=0.5)


@pytest.mark.asyncio
async def test_night_charging_is_all_grid(store):
    await _add(store, [dict(ev_charging_kwh=1.5, pv_kwh=0.0, import_kwh=2.0, **P)])
    r = await _range(store)
    assert r["ev_grid_kwh"] == 1.5
    assert r["ev_solar_kwh"] == 0.0
    assert r["ev_cost_sek"] == pytest.approx(3.0)
    assert r["ev_solar_share"] == 0.0


@pytest.mark.asyncio
async def test_night_under_recorded_import_is_not_solar(store):
    await _add(store, [dict(ev_charging_kwh=1.65, pv_kwh=0.0, import_kwh=1.04, **P)])
    r = await _range(store)
    assert r["ev_solar_kwh"] == 0.0
    assert r["ev_grid_kwh"] == 1.65
    assert r["ev_solar_share"] == 0.0


@pytest.mark.asyncio
async def test_ev_cost_capped_at_slot_import(store):
    # ev_grid (1.65) exceeds import (1.04): cost uses import, never above import cost.
    await _add(store, [dict(ev_charging_kwh=1.65, pv_kwh=0.0, import_kwh=1.04, **P)])
    r = await _range(store)
    assert r["ev_grid_kwh"] > r["grid_import_kwh"]
    assert r["ev_cost_sek"] == pytest.approx(2.08)
    assert r["ev_cost_sek"] <= r["import_cost_sek"]


@pytest.mark.asyncio
async def test_midday_full_solar(store):
    await _add(
        store,
        [dict(ev_charging_kwh=1.5, pv_kwh=2.0, load_kwh=0.4, water_kwh=0.0, import_kwh=0.0, **P)],
    )
    r = await _range(store)
    assert r["ev_solar_kwh"] == 1.5
    assert r["ev_grid_kwh"] == 0.0
    assert r["ev_cost_sek"] == 0.0
    assert r["ev_solar_share"] == 1.0


@pytest.mark.asyncio
async def test_partial_surplus(store):
    await _add(
        store,
        [dict(ev_charging_kwh=1.5, pv_kwh=1.0, load_kwh=0.4, water_kwh=0.0, import_kwh=1.2, **P)],
    )
    r = await _range(store)
    assert r["ev_solar_kwh"] == pytest.approx(0.6)
    assert r["ev_grid_kwh"] == pytest.approx(0.9)
    # Only the grid part is priced; solar has no monetary value in the EV cost.
    assert r["ev_cost_sek"] == pytest.approx(1.8)
    assert r["ev_cost_sek"] <= r["import_cost_sek"]
    assert r["ev_grid_kwh"] + r["ev_solar_kwh"] == pytest.approx(r["ev_charging_kwh"])


@pytest.mark.asyncio
async def test_water_heating_reduces_surplus(store):
    await _add(
        store,
        [dict(ev_charging_kwh=1.5, pv_kwh=2.0, load_kwh=0.4, water_kwh=1.0, import_kwh=1.0, **P)],
    )
    r = await _range(store)
    assert r["ev_solar_kwh"] == pytest.approx(0.6)
    assert r["ev_grid_kwh"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_load_above_pv_is_all_grid(store):
    await _add(
        store,
        [dict(ev_charging_kwh=1.0, pv_kwh=0.3, load_kwh=0.5, water_kwh=0.0, import_kwh=1.2, **P)],
    )
    r = await _range(store)
    assert r["ev_solar_kwh"] == 0.0
    assert r["ev_grid_kwh"] == 1.0


@pytest.mark.asyncio
async def test_period_share_and_sum(store):
    await _add(
        store,
        [
            dict(ev_charging_kwh=6.0, pv_kwh=0.0, import_kwh=6.0, import_price_sek_kwh=1.0),
            dict(ev_charging_kwh=4.0, pv_kwh=5.0, load_kwh=0.5, import_kwh=0.0, import_price_sek_kwh=1.0),
        ],
    )
    r = await _range(store)
    assert r["ev_charging_kwh"] == 10.0
    assert r["ev_solar_share"] == pytest.approx(0.4)
    assert r["ev_cost_sek"] == pytest.approx(6.0)
    # Existing aggregates are untouched by the EV attribution.
    assert r["import_cost_sek"] == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_no_ev_energy(store):
    await _add(store, [dict(ev_charging_kwh=0.0, pv_kwh=3.0, import_kwh=2.0, import_price_sek_kwh=1.0)])
    r = await _range(store)
    assert r["ev_cost_sek"] == 0.0
    assert r["ev_grid_kwh"] == 0.0
    assert r["ev_solar_kwh"] == 0.0
    assert r["ev_solar_share"] is None


@pytest.mark.asyncio
async def test_null_prices_and_inputs_count_as_zero(store):
    await _add(store, [dict(ev_charging_kwh=1.0, import_kwh=None, pv_kwh=None, load_kwh=None)])
    r = await _range(store)
    assert r["ev_grid_kwh"] == 1.0
    assert r["ev_solar_kwh"] == 0.0
    assert r["ev_cost_sek"] == 0.0
    assert r["ev_solar_share"] == 0.0


@pytest.mark.asyncio
async def test_error_fallback_includes_ev_fields(store):
    with (
        patch("backend.api.routers.energy.load_yaml", return_value={"timezone": "Not/AZone"}),
    ):
        r = await get_energy_range(period="today", store=store)
    assert "error" in r
    assert r["ev_cost_sek"] == 0.0
    assert r["ev_solar_share"] is None


@pytest.mark.asyncio
async def test_energy_today_returns_ev_cost_fields(store):
    from backend.api.routers.energy import get_energy_today

    await _add(
        store,
        [dict(ev_charging_kwh=1.5, pv_kwh=1.0, load_kwh=0.4, import_kwh=1.2, **P)],
    )
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        r = await get_energy_today(store=store)
    assert r["ev_grid_kwh"] == pytest.approx(0.9)
    assert r["ev_solar_kwh"] == pytest.approx(0.6)
    assert r["ev_cost_sek"] == pytest.approx(1.8)
    assert r["ev_solar_share"] == pytest.approx(0.4, abs=0.01)
