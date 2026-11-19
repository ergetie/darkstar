"""Import-weighted average prices in /api/energy/range: spot (export_price_sek_kwh, the pure
Nordpool spot) and all-in (import_price_sek_kwh), weighted by import_kwh, NULL prices excluded,
fixed fees never included."""

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


async def _range(store: LearningStore, config: dict | None = None) -> dict:
    with patch("backend.api.routers.energy.load_yaml", return_value=config or CONFIG):
        return await get_energy_range(period="today", store=store)


@pytest.mark.asyncio
async def test_weighted_by_imported_kwh_not_simple_mean(store):
    await _add(
        store,
        [
            dict(import_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0),
            dict(import_kwh=3.0, export_price_sek_kwh=2.0, import_price_sek_kwh=4.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == pytest.approx(1.75)
    assert r["avg_import_price_sek_kwh"] == pytest.approx(3.5)


@pytest.mark.asyncio
async def test_null_price_excluded_from_numerator_and_denominator(store):
    await _add(
        store,
        [
            dict(import_kwh=5.0, export_price_sek_kwh=None, import_price_sek_kwh=None),
            dict(import_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=3.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == pytest.approx(1.0)
    assert r["avg_import_price_sek_kwh"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_prices_excluded_independently(store):
    await _add(
        store,
        [
            dict(import_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=None),
            dict(import_kwh=1.0, export_price_sek_kwh=3.0, import_price_sek_kwh=5.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == pytest.approx(2.0)
    assert r["avg_import_price_sek_kwh"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_zero_and_negative_prices_are_real_values(store):
    await _add(
        store,
        [
            dict(import_kwh=2.0, export_price_sek_kwh=0.0, import_price_sek_kwh=0.0),
            dict(import_kwh=2.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0),
            dict(import_kwh=1.0, export_price_sek_kwh=-0.5, import_price_sek_kwh=1.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == pytest.approx(1.5 / 5.0)
    assert r["avg_import_price_sek_kwh"] == pytest.approx(5.0 / 5.0)


@pytest.mark.asyncio
async def test_zero_or_null_import_ignored(store):
    await _add(
        store,
        [
            dict(import_kwh=0.0, export_price_sek_kwh=9.0, import_price_sek_kwh=9.0),
            dict(import_kwh=None, export_price_sek_kwh=9.0, import_price_sek_kwh=9.0),
            dict(import_kwh=2.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == pytest.approx(1.0)
    assert r["avg_import_price_sek_kwh"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_no_slots_yields_null(store):
    r = await _range(store)
    assert "error" not in r
    assert r["avg_import_spot_sek_kwh"] is None
    assert r["avg_import_price_sek_kwh"] is None


@pytest.mark.asyncio
async def test_no_qualifying_import_yields_null(store):
    await _add(
        store,
        [
            dict(
                import_kwh=0.0, export_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0
            ),
            dict(import_kwh=1.0, export_price_sek_kwh=None, import_price_sek_kwh=None),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] is None
    assert r["avg_import_price_sek_kwh"] is None


@pytest.mark.asyncio
async def test_rounded_to_four_decimals(store):
    await _add(
        store,
        [
            dict(import_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0),
            dict(import_kwh=2.0, export_price_sek_kwh=0.0, import_price_sek_kwh=0.0),
        ],
    )
    r = await _range(store)
    assert r["avg_import_spot_sek_kwh"] == 0.3333
    assert r["avg_import_price_sek_kwh"] == 0.6667


@pytest.mark.asyncio
async def test_fixed_fees_do_not_change_averages(store):
    await _add(
        store,
        [
            dict(import_kwh=1.0, export_price_sek_kwh=1.0, import_price_sek_kwh=2.0),
            dict(import_kwh=3.0, export_price_sek_kwh=2.0, import_price_sek_kwh=4.0),
        ],
    )
    plain = await _range(store)
    fee_config = {
        **CONFIG,
        "pricing": {"subscription_fee_sek_per_month": 300.0, "supplier_fee_sek_per_year": 600.0},
    }
    with_fees = await _range(store, fee_config)
    assert with_fees["fixed_fees_sek"] > 0
    assert plain["fixed_fees_sek"] == 0.0
    assert with_fees["avg_import_spot_sek_kwh"] == plain["avg_import_spot_sek_kwh"] == 1.75
    assert with_fees["avg_import_price_sek_kwh"] == plain["avg_import_price_sek_kwh"] == 3.5


@pytest.mark.asyncio
async def test_error_fallback_has_null_averages(store):
    with patch("backend.api.routers.energy.load_yaml", return_value={"timezone": "Not/AZone"}):
        r = await get_energy_range(period="today", store=store)
    assert "error" in r
    assert "avg_import_spot_sek_kwh" in r and r["avg_import_spot_sek_kwh"] is None
    assert "avg_import_price_sek_kwh" in r and r["avg_import_price_sek_kwh"] is None
