"""Grid-only API tests replacing the retired battery-model comparison contract."""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz
from sqlalchemy import event

from backend.api.routers import energy
from backend.api.routers.energy import get_cost_series
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "grid-only-api.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


def recorded_flags():
    return json.dumps({"source": "recorder"})


async def add_rows(store, starts, **values):
    async with store.AsyncSession() as session:
        for start in starts:
            start_utc = start.astimezone(UTC)
            fields = {
                "import_kwh": 0.0,
                "export_kwh": 0.0,
                "import_price_sek_kwh": 2.0,
                "export_price_sek_kwh": 1.0,
                "load_kwh": 1.0,
                "water_kwh": 0.0,
                "ev_charging_kwh": 0.0,
                "quality_flags": recorded_flags(),
            }
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=(start_utc + timedelta(minutes=15)).astimezone(TZ).isoformat(),
                    **(fields | values),
                )
            )
        await session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config",
    [
        {"timezone": "Europe/Stockholm", "system": {"has_battery": False, "has_solar": True}},
        {"timezone": "Europe/Stockholm", "system": {"has_battery": True, "has_solar": False}},
        {"timezone": "Europe/Stockholm", "system": {"has_battery": False, "has_solar": False}},
    ],
)
async def test_comparison_is_independent_of_battery_solar_pv_and_soc(store, config):
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    start = TZ.localize(datetime.combine(yesterday, datetime.min.time()))
    battery_present = config["system"]["has_battery"]
    await add_rows(
        store,
        [start],
        pv_kwh=None,
        batt_charge_kwh=0.0 if battery_present else None,
        batt_discharge_kwh=0.0 if battery_present else None,
        soc_start_percent=None,
        soc_end_percent=None,
    )
    config = config | {"battery_economics": {"battery_cycle_cost_kwh": 0.2}}
    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["grid_only_comparison"]
    assert comparison["status"] == "partial"
    assert comparison["grid_only_cost_sek"] == pytest.approx(2.0)
    assert comparison["ds_cost_sek"] == pytest.approx(0.0)
    assert comparison["saving_sek"] == pytest.approx(2.0)
    assert comparison["ds_wear_cost_sek"] == 0.0
    assert comparison["grid_only_wear_cost_sek"] == 0.0


@pytest.mark.asyncio
async def test_request_reads_only_selected_period_and_does_not_simulate_calibrate_or_write(
    store, monkeypatch
):
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    start = TZ.localize(datetime.combine(yesterday, datetime.min.time()))
    await add_rows(store, [start], batt_charge_kwh=0.0, batt_discharge_kwh=0.0)
    before = await store.get_observations_range(start, start + timedelta(days=1))
    statements: list[str] = []
    event.listen(
        store.async_engine.sync_engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, _params, _context, _many: statements.append(statement),
    )
    statements.clear()

    def fail(*_args, **_kwargs):
        raise AssertionError("retired battery comparison work was invoked")

    import backend.baseline as baseline
    import backend.battery_comparison as battery_comparison

    monkeypatch.setattr(baseline, "simulate_self_use_with_end_state", fail)
    monkeypatch.setattr(battery_comparison, "fit_calibration", fail)
    with patch(
        "backend.api.routers.energy.load_yaml",
        return_value={"timezone": "Europe/Stockholm", "system": {"has_battery": True}},
    ):
        result = await get_cost_series(period="yesterday", store=store)
    endpoint_statements = list(statements)
    after = await store.get_observations_range(start, start + timedelta(days=1))

    select_statements = [
        statement.lower()
        for statement in endpoint_statements
        if "slot_observations" in statement.lower()
    ]
    assert len(select_statements) == 1
    assert "slot_start >=" in select_statements[0]
    assert "slot_start <" in select_statements[0]
    assert before == after
    assert result["grid_only_comparison"]["coverage"]["covered_slots"] == 1


@pytest.mark.asyncio
async def test_configured_battery_missing_flow_excludes_slot_and_measured_wear_reconciles(store):
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    start = TZ.localize(datetime.combine(yesterday, datetime.min.time()))
    await add_rows(
        store,
        [start, start + timedelta(minutes=15)],
        import_kwh=2.0,
        export_kwh=0.5,
        load_kwh=1.0,
        batt_charge_kwh=20.0,
        batt_discharge_kwh=8.0,
    )
    async with store.AsyncSession() as session:
        from sqlalchemy import select

        row = (await session.execute(select(SlotObservation).order_by(SlotObservation.slot_start))).scalars().first()
        assert row is not None
        row.batt_discharge_kwh = None
        await session.commit()
    config = {
        "timezone": "Europe/Stockholm",
        "system": {"has_battery": True},
        "battery_economics": {"battery_cycle_cost_kwh": 0.2},
    }
    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_cost_series(period="yesterday", store=store)

    comparison = result["grid_only_comparison"]
    # The first configured-battery flow has charge but no discharge, so it is
    # excluded. The second slot carries its flows and one eligible bill amount.
    assert comparison["coverage"] == {"covered_slots": 1, "total_slots": 96, "excluded_slots": 95}
    assert comparison["status"] == "partial"
    assert comparison["ds_electricity_cost_sek"] == pytest.approx(3.5)
    assert comparison["ds_wear_cost_sek"] == pytest.approx(2.8)
    assert comparison["ds_cost_sek"] == pytest.approx(6.3)
    assert comparison["grid_only_wear_cost_sek"] == 0.0
    assert comparison["saving_sek"] == pytest.approx(comparison["grid_only_cost_sek"] - 6.3)


@pytest.mark.asyncio
async def test_nonfinite_configured_cycle_cost_makes_battery_comparison_unavailable(store):
    yesterday = datetime.now(TZ).date() - timedelta(days=1)
    start = TZ.localize(datetime.combine(yesterday, datetime.min.time()))
    await add_rows(
        store,
        [start],
        batt_charge_kwh=0.0,
        batt_discharge_kwh=0.0,
    )
    config = {
        "timezone": "Europe/Stockholm",
        "system": {"has_battery": True},
        "battery_economics": {"battery_cycle_cost_kwh": float("inf")},
    }
    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        result = await get_cost_series(period="yesterday", store=store)
    comparison = result["grid_only_comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["reason"] == "no_usable_observations"
    assert "saving_sek" not in comparison


@pytest.mark.asyncio
async def test_started_slot_remains_in_actual_points_but_is_excluded_from_both_comparison_bills(
    store, monkeypatch
):
    fixed_now = TZ.localize(datetime(2026, 10, 5, 10, 7)).astimezone(UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz is not None else fixed_now.replace(tzinfo=None)

    local_day = datetime(2026, 10, 5)
    starts = [
        TZ.localize(local_day.replace(hour=9, minute=45)),
        TZ.localize(local_day.replace(hour=10, minute=0)),
        TZ.localize(local_day.replace(hour=10, minute=15)),
    ]
    await add_rows(store, starts, import_kwh=1.0, load_kwh=1.0)
    monkeypatch.setattr(energy, "datetime", FrozenDateTime)
    with patch(
        "backend.api.routers.energy.load_yaml",
        return_value={"timezone": "Europe/Stockholm", "system": {"has_battery": False}},
    ):
        result = await get_cost_series(period="today", store=store)

    assert len(result["points"]) == 2
    assert result["points"][-1]["import_cost_sek"] == pytest.approx(2.0)
    comparison = result["grid_only_comparison"]
    assert comparison["coverage"] == {"covered_slots": 1, "total_slots": 40, "excluded_slots": 39}
    assert comparison["through"] == "2026-10-05T10:00:00+02:00"
    assert comparison["ds_cost_sek"] == pytest.approx(2.0)
    assert comparison["grid_only_cost_sek"] == pytest.approx(2.0)
