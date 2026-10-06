from __future__ import annotations

import json
from datetime import UTC, datetime, time as datetime_time, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import get_cost_series
from backend.battery_comparison import BatteryModel, CalibrationResult, FitDiagnostics, GridModel
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {
        "has_battery": True,
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 10,
            "max_soc_percent": 95,
            "max_charge_w": 2000,
            "max_discharge_w": 2000,
            "charge_efficiency": 0.95,
            "discharge_efficiency": 0.95,
        },
    },
    "battery_economics": {"battery_cycle_cost_kwh": 0.2},
}
DIAGNOSTICS = FitDiagnostics(
    GridModel(0.8, 0.9),
    BatteryModel(0.92, 0.9),
    960,
    240,
    200,
    50,
    "2026-09-01T00:00:00+00:00",
    "2026-09-20T00:00:00+00:00",
    "2026-09-20T00:15:00+00:00",
    "2026-09-30T00:00:00+00:00",
    0.1,
    0.0,
    0.1,
    0.0,
    0.0,
    10.0,
)


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "comparison-api.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


async def seed_yesterday(store: LearningStore, count: int = 96, *, first_soc: float | None = 50.0):
    start = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    async with store.AsyncSession() as session:
        for index in range(count):
            slot = TZ.normalize(start + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0.0,
                    export_kwh=0.0,
                    import_price_sek_kwh=2.0,
                    export_price_sek_kwh=1.0,
                    pv_kwh=1.0,
                    load_kwh=0.8,
                    water_kwh=0.0,
                    ev_charging_kwh=0.0,
                    batt_charge_kwh=0.0,
                    batt_discharge_kwh=0.0,
                    soc_start_percent=first_soc if index == 0 else 50.0,
                    soc_end_percent=50.0,
                    quality_flags=json.dumps({"source": "recorder"}),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_insufficient_data_status_keeps_metered_and_legacy_fields(store):
    await seed_yesterday(store)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        result = await get_cost_series(period="yesterday", store=store)
    assert result["battery_comparison"]["status"] == "insufficient_data"
    assert "saving_sek" not in result["battery_comparison"]
    assert result["baseline"] is not None
    assert result["points"][-1]["cumulative_net_cost_sek"] == 0.0
    assert "baseline_cumulative_net_cost_sek" in result["points"][-1]


@pytest.mark.asyncio
async def test_unreliable_fit_exposes_diagnostics_but_no_amounts(store):
    await seed_yesterday(store)
    fit = CalibrationResult("unreliable_model", "holdout_validation_failed", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "unreliable_model"
    assert comparison["reason"] == "holdout_validation_failed"
    assert comparison["calibration"]["grid_rmse_kwh"] == pytest.approx(0.1)
    assert "saving_sek" not in comparison and "points" not in comparison


@pytest.mark.asyncio
async def test_available_api_comparison_reconciles_summaries_and_points(store):
    await seed_yesterday(store)
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    assert "saving_sek" in comparison and comparison["points"]
    assert comparison["darkstar"]["comparison_cost_sek"] == pytest.approx(0)
    assert comparison["self_use"]["comparison_cost_sek"] == pytest.approx(0)
    assert comparison["saving_sek"] == pytest.approx(0)
    assert comparison["points"][-1]["darkstar_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["darkstar"]["comparison_cost_sek"]
    )
    assert comparison["points"][-1]["self_use_cumulative_comparison_cost_sek"] == pytest.approx(
        comparison["self_use"]["comparison_cost_sek"]
    )
    assert result["points"][-1]["cumulative_net_cost_sek"] == 0


@pytest.mark.asyncio
async def test_missing_initial_soc_is_incomplete_even_with_valid_calibration(store):
    await seed_yesterday(store, first_soc=None)
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "incomplete_period"
    assert comparison["reason"] == "missing_start_soc"
    assert "saving_sek" not in comparison


@pytest.mark.asyncio
async def test_missing_bucket_end_soc_is_incomplete(store):
    await seed_yesterday(store)
    async with store.AsyncSession() as session:
        slot = TZ.localize(
            datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
        )
        row = await session.get(SlotObservation, slot.isoformat())
        assert row is not None
        row.soc_end_percent = None
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    assert result["battery_comparison"]["status"] == "incomplete_period"
    assert "saving_sek" not in result["battery_comparison"]


@pytest.mark.asyncio
async def test_current_started_slot_stays_metered_but_is_excluded_from_comparison(store):
    today = TZ.localize(datetime.combine(datetime.now(TZ).date(), datetime_time.min))
    async with store.AsyncSession() as session:
        for index in range(49):
            slot = TZ.normalize(today + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0.0,
                    export_kwh=0.0,
                    import_price_sek_kwh=2.0,
                    export_price_sek_kwh=1.0,
                    pv_kwh=1.0,
                    load_kwh=0.8,
                    water_kwh=0.0,
                    ev_charging_kwh=0.0,
                    batt_charge_kwh=0.0,
                    batt_discharge_kwh=0.0,
                    soc_start_percent=50.0,
                    soc_end_percent=50.0,
                    quality_flags=json.dumps({"source": "recorder"}),
                )
            )
        await session.commit()
    fixed_local = TZ.localize(datetime.combine(today.date(), datetime_time(12, 7)))

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_local if tz is None else fixed_local.astimezone(tz)

    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.datetime", FixedNow),
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="today", store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    assert comparison["through"] == (today + timedelta(hours=12)).astimezone(UTC).isoformat()
    assert len(comparison["points"]) == 12
    assert result["points"][-1]["start"].startswith(today.strftime("%Y-%m-%dT12:00"))


@pytest.mark.asyncio
@pytest.mark.parametrize("day,count", [("2026-03-29", 92), ("2026-10-25", 100)])
async def test_completed_dst_day_uses_local_midnight_and_elapsed_slots(store, day, count):
    from backend.api.routers import energy

    start = TZ.localize(datetime.fromisoformat(day))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 27, 12, tzinfo=UTC).astimezone(tz)

    async with store.AsyncSession() as session:
        for index in range(count):
            slot = TZ.normalize(start + timedelta(minutes=15 * index))
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0,
                    export_kwh=0,
                    import_price_sek_kwh=2,
                    export_price_sek_kwh=1,
                    pv_kwh=1,
                    load_kwh=0.8,
                    water_kwh=0,
                    ev_charging_kwh=0,
                    batt_charge_kwh=0,
                    batt_discharge_kwh=0,
                    soc_start_percent=50,
                    soc_end_percent=50,
                )
            )
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch.object(energy, "datetime", Clock),
        patch.object(energy, "load_yaml", return_value=CONFIG),
        patch.object(energy, "_calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="custom", start_date=day, end_date=day, store=store)
    comparison = result["battery_comparison"]
    assert comparison["status"] == "available"
    next_day = TZ.localize(datetime.fromisoformat(day) + timedelta(days=1))
    assert datetime.fromisoformat(comparison["through"]) == next_day
    assert len(comparison["points"]) == count // 4
    previous_day = datetime.fromisoformat(day) - timedelta(days=1)
    previous_start = TZ.localize(previous_day)
    async with store.AsyncSession() as session:
        for index in range(96):
            slot = previous_start + timedelta(minutes=15 * index)
            session.add(
                SlotObservation(
                    slot_start=slot.isoformat(),
                    slot_end=(slot + timedelta(minutes=15)).isoformat(),
                    import_kwh=0,
                    export_kwh=0,
                    import_price_sek_kwh=2,
                    export_price_sek_kwh=1,
                    pv_kwh=1,
                    load_kwh=0.8,
                    water_kwh=0,
                    ev_charging_kwh=0,
                    batt_charge_kwh=0,
                    batt_discharge_kwh=0,
                    soc_start_percent=50,
                    soc_end_percent=50,
                )
            )
        await session.commit()
    with (
        patch.object(energy, "datetime", Clock),
        patch.object(energy, "load_yaml", return_value=CONFIG),
        patch.object(energy, "_calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(
            period="custom", start_date=previous_day.strftime("%Y-%m-%d"), end_date=day, store=store
        )
    assert result["battery_comparison"]["status"] == "available"
    assert len(result["battery_comparison"]["points"]) == 2
    # One local-midnight bucket per date, even when the date has two UTC offsets.
    assert result["battery_comparison"]["points"][-1]["start"] == start.isoformat()


@pytest.mark.asyncio
async def test_period_model_failure_has_unreliable_status(store):
    await seed_yesterday(store)
    async with store.AsyncSession() as session:
        from sqlalchemy import update

        await session.execute(update(SlotObservation).values(import_kwh=1))
        await session.commit()
    fit = CalibrationResult("available", "validated", DIAGNOSTICS)
    with (
        patch("backend.api.routers.energy.load_yaml", return_value=CONFIG),
        patch("backend.api.routers.energy._calibrated_fit", new=AsyncMock(return_value=fit)),
    ):
        result = await get_cost_series(period="yesterday", store=store)
    assert result["battery_comparison"]["status"] == "unreliable_model"
    assert result["battery_comparison"]["reason"] == "period_validation_failed"
