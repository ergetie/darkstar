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
CONFIG = {"timezone": "Europe/Stockholm", "system": {"has_battery": False}}
BATTERY_CONFIG = {
    "timezone": "Europe/Stockholm",
    "system": {"has_battery": True},
    "battery": {
        "capacity_kwh": 10.0,
        "min_soc_percent": 10,
        "max_soc_percent": 100,
        "max_charge_w": 4000.0,
        "max_discharge_w": 4000.0,
        "charge_efficiency": 1.0,
        "discharge_efficiency": 1.0,
    },
    "battery_economics": {"battery_cycle_cost_kwh": 0.2},
}


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


def _slot(**kwargs) -> dict:
    return {
        "import_kwh": 0.0,
        "export_kwh": 0.0,
        "import_price_sek_kwh": 2.0,
        "export_price_sek_kwh": 0.5,
        "pv_kwh": 0.0,
        "load_kwh": 0.0,
        "batt_charge_kwh": 0.0,
        "batt_discharge_kwh": 0.0,
        **kwargs,
    }


async def _baseline_rows(store: LearningStore) -> None:
    # Slot 0: 1.0 kWh PV, 0.4 load -> baseline charges 0.6; real exports it all.
    # Slot 4 (hour 1): 1.5 kWh load -> baseline discharges 1.0 and imports 0.5; real imports 1.5.
    rows = [_slot(soc_end_percent=50.0) for _ in range(5)]
    rows[0] = _slot(pv_kwh=1.0, load_kwh=0.4, export_kwh=0.6, soc_end_percent=50.0)
    rows[4] = _slot(load_kwh=1.5, import_kwh=1.5, soc_end_percent=50.0)
    await _add(store, rows)


@pytest.mark.asyncio
async def test_baseline_fields_present_with_battery(store):
    await _baseline_rows(store)
    with patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
        total = await get_energy_range(period="yesterday", store=store)

    points = series["points"]
    assert all("baseline_cumulative_net_cost_sek" in p for p in points)
    baseline = series["baseline"]
    assert set(baseline) == {
        "net_cost_sek",
        "battery_wear_cost_sek",
        "net_cost_incl_wear_sek",
        "saving_incl_wear_sek",
        "stored_energy_difference_kwh",
        "stored_energy_value_sek",
    }
    # Starts at 50 % of 10 kWh: slot 0 charges 0.6 and exports nothing; the later deficit
    # of 1.5 kWh is covered with 1.0 kWh from the battery and 0.5 kWh imported at 2.0.
    assert baseline["net_cost_sek"] == pytest.approx(1.0)
    assert points[0]["baseline_cumulative_net_cost_sek"] == pytest.approx(0.0)
    assert points[-1]["baseline_cumulative_net_cost_sek"] == pytest.approx(baseline["net_cost_sek"])
    # (0.6 + 1.0) kWh * 0.2 * 0.5 wear for the baseline, none recorded for the real side.
    assert baseline["battery_wear_cost_sek"] == pytest.approx(0.16)
    real_incl_wear = total["net_cost_incl_wear_sek"]
    # Real battery ends at 50 %, the simulated one at 46 % (5.0 + 0.6 - 1.0 kWh): 0.4 kWh more
    # stored, valued at the 2.0 average import price with discharge efficiency 1.0.
    assert baseline["stored_energy_difference_kwh"] == pytest.approx(0.4)
    assert baseline["stored_energy_value_sek"] == pytest.approx(0.8)
    assert baseline["saving_incl_wear_sek"] == pytest.approx(
        baseline["net_cost_incl_wear_sek"] - real_incl_wear + baseline["stored_energy_value_sek"],
        abs=0.01,
    )
    assert series["battery_comparison"]["status"] == "incomplete_period"
    assert series["battery_comparison"]["reason"] in {"missing_completed_slot", "missing_start_soc"}


@pytest.mark.asyncio
async def test_baseline_leaves_existing_fields_unchanged(store):
    await _baseline_rows(store)
    with patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG):
        with_baseline = await get_cost_series(period="yesterday", store=store)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        without = await get_cost_series(period="yesterday", store=store)

    existing = ("start", "import_cost_sek", "export_revenue_sek", "net_cost_sek")
    for a, b in zip(with_baseline["points"], without["points"], strict=True):
        assert {k: a[k] for k in existing} == {k: b[k] for k in existing}
        assert a["cumulative_net_cost_sek"] == b["cumulative_net_cost_sek"]


@pytest.mark.asyncio
async def test_no_baseline_without_battery(store):
    await _baseline_rows(store)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
    assert series["baseline"] is None
    assert all("baseline_cumulative_net_cost_sek" not in p for p in series["points"])
    assert series["battery_comparison"]["status"] == "no_battery"


@pytest.mark.asyncio
async def test_no_baseline_without_slots(store):
    with patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
    assert series["points"] == []
    assert series["baseline"] is None
    assert series["battery_comparison"]["status"] == "no_data"


@pytest.mark.asyncio
async def test_baseline_excludes_future_slots(store):
    tomorrow = TZ.localize(
        datetime.combine(datetime.now(TZ).date() + timedelta(days=1), datetime.min.time())
    )
    future = TZ.normalize(tomorrow - timedelta(minutes=15))
    async with store.AsyncSession() as session:
        session.add(
            SlotObservation(
                slot_start=future.isoformat(),
                slot_end=tomorrow.isoformat(),
                load_kwh=5.0,
                import_price_sek_kwh=1.0,
            )
        )
        await session.commit()
    with patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG):
        series = await get_cost_series(period="today", store=store)
    assert series["points"] == []
    assert series["baseline"] is None


@pytest.mark.asyncio
async def test_baseline_starts_from_slot_before_period(store):
    # Last slot of the day before the period records 60 % SoC; with 1 kWh load the
    # baseline can discharge, which it could not from the 10 % fallback.
    yesterday = TZ.localize(
        datetime.combine(datetime.now(TZ).date() - timedelta(days=1), datetime.min.time())
    )
    before = TZ.normalize(yesterday - timedelta(minutes=15))
    async with store.AsyncSession() as session:
        session.add(
            SlotObservation(
                slot_start=before.isoformat(),
                slot_end=yesterday.isoformat(),
                soc_end_percent=60.0,
            )
        )
        await session.commit()
    await _add(store, [_slot(load_kwh=1.0, import_kwh=1.0)])
    with patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
    assert series["baseline"]["net_cost_sek"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_baseline_orders_slots_across_dst_change(store):
    # 2026-10-25 has 25 hours: the 02:xx local hour occurs twice (+02:00 then +01:00).
    # Charging happens in the first 02:00 hour and the deficit in the second; a string
    # sort would put the +01:00 rows first and the baseline would import instead.
    first = TZ.localize(datetime(2026, 10, 25, 2, 0), is_dst=True)
    second = TZ.localize(datetime(2026, 10, 25, 2, 0), is_dst=False)
    async with store.AsyncSession() as session:
        for start, extra in (
            (first, {"pv_kwh": 1.0}),
            (second, {"load_kwh": 1.0, "import_kwh": 1.0}),
        ):
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=(start + timedelta(minutes=15)).isoformat(),
                    import_price_sek_kwh=2.0,
                    export_price_sek_kwh=0.5,
                    soc_end_percent=10.0,
                    **extra,
                )
            )
        await session.commit()
    fixed_now = TZ.localize(datetime(2026, 10, 26, 12, 0))

    class _Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now

    with (
        patch("backend.api.routers.energy.load_yaml", return_value=BATTERY_CONFIG),
        patch("backend.api.routers.energy.datetime", _Now),
    ):
        series = await get_cost_series(
            period="custom", start_date="2026-10-25", end_date="2026-10-25", store=store
        )
    # Charged 1.0 in the first slot, discharged 1.0 in the second: nothing imported.
    assert series["baseline"]["net_cost_sek"] == pytest.approx(0.0)


def _config_with(**battery_overrides) -> dict:
    return {**BATTERY_CONFIG, "battery": {**BATTERY_CONFIG["battery"], **battery_overrides}}


async def _series(store: LearningStore, config: dict) -> dict:
    with patch("backend.api.routers.energy.load_yaml", return_value=config):
        return await get_cost_series(period="yesterday", store=store)


@pytest.mark.asyncio
async def test_stored_energy_negative_when_real_battery_holds_less(store):
    # Real battery ends at 30 %; the baseline (no flows) stays at its 50 % start: -2.0 kWh.
    await _add(store, [_slot(soc_end_percent=50.0), _slot(soc_end_percent=30.0)])
    baseline = (await _series(store, BATTERY_CONFIG))["baseline"]
    assert baseline["stored_energy_difference_kwh"] == pytest.approx(-2.0)
    assert baseline["stored_energy_value_sek"] == pytest.approx(-4.0)
    # Same cash flow on both sides and no wear: the saving is only the stored-energy value.
    assert baseline["saving_incl_wear_sek"] == pytest.approx(-4.0)


@pytest.mark.asyncio
async def test_stored_energy_value_uses_discharge_efficiency_and_mean_price(store):
    await _add(
        store,
        [
            _slot(soc_end_percent=50.0, import_price_sek_kwh=1.0),
            _slot(soc_end_percent=70.0, import_price_sek_kwh=3.0),
            _slot(soc_end_percent=70.0, import_price_sek_kwh=None),
        ],
    )
    baseline = (await _series(store, _config_with(discharge_efficiency=0.5)))["baseline"]
    # +2.0 kWh at mean price 2.0 (slots with a price only) * 0.5 efficiency.
    assert baseline["stored_energy_difference_kwh"] == pytest.approx(2.0)
    assert baseline["stored_energy_value_sek"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_stored_energy_defaults_discharge_efficiency_to_planner_value(store):
    config = _config_with()
    del config["battery"]["discharge_efficiency"]
    await _add(store, [_slot(soc_end_percent=50.0), _slot(soc_end_percent=70.0)])
    baseline = (await _series(store, config))["baseline"]
    assert baseline["stored_energy_value_sek"] == pytest.approx(2.0 * 2.0 * 0.95)


@pytest.mark.asyncio
async def test_stored_energy_unknown_without_real_end_soc(store):
    await _add(store, [_slot(load_kwh=1.0, import_kwh=1.0, soc_end_percent=None)])
    baseline = (await _series(store, BATTERY_CONFIG))["baseline"]
    assert baseline["stored_energy_difference_kwh"] is None
    assert baseline["stored_energy_value_sek"] is None
    assert baseline["saving_incl_wear_sek"] == pytest.approx(
        baseline["net_cost_incl_wear_sek"] - 2.0
    )


@pytest.mark.asyncio
async def test_stored_energy_uses_last_non_null_soc(store):
    await _add(store, [_slot(soc_end_percent=50.0), _slot(soc_end_percent=60.0), _slot()])
    baseline = (await _series(store, BATTERY_CONFIG))["baseline"]
    assert baseline["stored_energy_difference_kwh"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_stored_energy_zero_when_no_prices(store):
    await _add(
        store,
        [
            _slot(soc_end_percent=50.0, import_price_sek_kwh=None),
            _slot(soc_end_percent=70.0, import_price_sek_kwh=None),
        ],
    )
    baseline = (await _series(store, BATTERY_CONFIG))["baseline"]
    assert baseline["stored_energy_difference_kwh"] == pytest.approx(2.0)
    assert baseline["stored_energy_value_sek"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_chart_lines_exclude_stored_energy_value(store):
    await _add(store, [_slot(soc_end_percent=50.0), _slot(soc_end_percent=70.0)])
    series = await _series(store, BATTERY_CONFIG)
    assert series["baseline"]["stored_energy_value_sek"] == pytest.approx(4.0)
    assert series["points"][-1]["baseline_cumulative_net_cost_sek"] == pytest.approx(0.0)
    assert series["baseline"]["net_cost_sek"] == pytest.approx(0.0)
