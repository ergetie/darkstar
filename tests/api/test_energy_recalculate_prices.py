"""Historical import price recalculation endpoint."""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz
from sqlalchemy import select

from backend.api.routers.energy import RecalculatePricesRequest, recalculate_prices
from backend.learning.models import Base, SlotObservation, SlotPlan
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {
    "timezone": "Europe/Stockholm",
    "pricing": {
        "vat_percent": 25.0,
        "grid_transfer_fee_sek": 0.2584,
        "energy_tax_sek": 0.36,
        "supplier_markup_sek_kwh": 0.1132,
        "transfer_fee_mode": "time_of_use",
        "transfer_fee_rules": [{"hours": {"start": 6, "end": 22}, "fee_sek": 0.76}],
    },
}


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "test_learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


def _slot(day: datetime, hour: int, spot: float | None) -> SlotObservation:
    start = TZ.localize(day.replace(hour=hour))
    return SlotObservation(
        slot_start=start.isoformat(),
        slot_end=(start + timedelta(minutes=15)).isoformat(),
        import_kwh=1.0,
        import_price_sek_kwh=9.99,
        export_price_sek_kwh=spot,
        quality_flags=json.dumps({"source": "recorder"}),
    )


@pytest.mark.asyncio
async def test_reprices_from_date_skips_null_and_earlier_rows(store):
    async with store.AsyncSession() as session:
        session.add_all(
            [
                _slot(datetime(2026, 9, 30), 12, 0.5),  # before from_date
                _slot(datetime(2026, 10, 1), 2, 0.5),  # off-peak -> flat fee
                _slot(datetime(2026, 10, 1), 12, 0.5),  # time-of-use window
                _slot(datetime(2026, 10, 1), 13, None),  # no spot -> skipped
            ]
        )
        await session.commit()

    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await recalculate_prices(
            RecalculatePricesRequest(from_date="2026-10-01"), store=store
        )

    assert result == {"from_date": "2026-10-01", "repriced": 2, "skipped": 1}
    async with store.AsyncSession() as session:
        rows = {
            r.slot_start: r.import_price_sek_kwh
            for r in (await session.execute(select(SlotObservation))).scalars()
        }
    by_hour = {datetime.fromisoformat(k).strftime("%m-%d %H"): v for k, v in rows.items()}
    assert by_hour["09-30 12"] == 9.99
    assert by_hour["10-01 02"] == pytest.approx((0.5 + 0.2584 + 0.36 + 0.1132) * 1.25)
    assert by_hour["10-01 12"] == pytest.approx((0.5 + 0.76 + 0.36 + 0.1132) * 1.25)
    assert by_hour["10-01 13"] == 9.99


@pytest.mark.asyncio
async def test_slot_plans_are_untouched(store):
    async with store.AsyncSession() as session:
        session.add(_slot(datetime(2026, 10, 1), 12, 0.5))
        session.add(
            SlotPlan(
                slot_start=TZ.localize(datetime(2026, 10, 1, 12)).isoformat(),
                planned_import_kwh=1.5,
            )
        )
        await session.commit()

    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        await recalculate_prices(RecalculatePricesRequest(from_date="2026-10-01"), store=store)

    async with store.AsyncSession() as session:
        plan = (await session.execute(select(SlotPlan))).scalars().one()
    assert plan.planned_import_kwh == 1.5
