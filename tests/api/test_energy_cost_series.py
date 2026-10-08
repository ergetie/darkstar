"""Selected-period metered and grid-only cost-series API contract tests."""

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch

import pytest
import pytest_asyncio
import pytz

from backend.api.routers.energy import get_cost_series, get_energy_range
from backend.learning.models import Base, SlotObservation
from backend.learning.store import LearningStore

TZ = pytz.timezone("Europe/Stockholm")
CONFIG = {"timezone": "Europe/Stockholm", "system": {"has_battery": False}}


@pytest_asyncio.fixture
async def store(tmp_path):
    value = LearningStore(str(tmp_path / "test_learning.db"), TZ)
    async with value.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield value
    await value.close()


async def _add(store: LearningStore, rows: list[dict], *, day=None) -> list[datetime]:
    day = day or (datetime.now(TZ).date() - timedelta(days=1))
    first = TZ.localize(datetime.combine(day, datetime.min.time()))
    starts = []
    async with store.AsyncSession() as session:
        for index, row in enumerate(rows):
            start = (first.astimezone(pytz.UTC) + timedelta(minutes=15 * index)).astimezone(TZ)
            starts.append(start)
            fields = {
                "import_kwh": 0.0,
                "export_kwh": 0.0,
                "import_price_sek_kwh": 2.0,
                "export_price_sek_kwh": 0.5,
                "load_kwh": 0.0,
                "water_kwh": 0.0,
                "ev_charging_kwh": 0.0,
                "quality_flags": json.dumps({"source": "recorder"}),
            }
            session.add(
                SlotObservation(
                    slot_start=start.isoformat(),
                    slot_end=(start.astimezone(pytz.UTC) + timedelta(minutes=15)).astimezone(TZ).isoformat(),
                    **(fields | row),
                )
            )
        await session.commit()
    return starts


@pytest.mark.asyncio
async def test_metered_hourly_points_keep_actual_accounting_and_grid_comparison_is_separate(store):
    rows = [
        {"import_kwh": 1.0, "load_kwh": 1.0},
        {"import_kwh": 1.0, "load_kwh": 2.0},
        {"export_kwh": 2.0, "export_price_sek_kwh": 0.5, "load_kwh": 3.0},
        {"import_kwh": 0.5, "load_kwh": 0.5},
        {"import_kwh": 0.0, "export_kwh": 0.0, "load_kwh": 0.0},
    ]
    await _add(store, rows)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
        totals = await get_energy_range(period="yesterday", store=store)

    assert series["bucket"] == "hour"
    assert len(series["points"]) == 2
    assert series["points"][0]["import_cost_sek"] == pytest.approx(5.0)
    assert series["points"][0]["export_revenue_sek"] == pytest.approx(1.0)
    assert series["points"][-1]["cumulative_net_cost_sek"] == pytest.approx(totals["net_cost_sek"])
    comparison = series["grid_only_comparison"]
    assert comparison["status"] == "partial"
    assert comparison["coverage"] == {"covered_slots": 5, "total_slots": 96, "excluded_slots": 91}
    assert comparison["grid_only_cost_sek"] == pytest.approx(13.0)
    assert comparison["ds_cost_sek"] == pytest.approx(4.0)
    assert comparison["saving_sek"] == pytest.approx(9.0)
    assert "baseline" not in series
    assert "battery_comparison" not in series
    assert all("baseline_cumulative_net_cost_sek" not in point for point in series["points"])


@pytest.mark.asyncio
async def test_per_slot_prices_controlled_loads_gross_flows_and_unrelated_battery_data(store):
    await _add(
        store,
        [
            {
                "load_kwh": 0.4,
                "water_kwh": 0.5,
                "ev_charging_kwh": 2.0,
                "import_kwh": 1.0,
                "export_kwh": 0.5,
                "import_price_sek_kwh": 2.0,
                "export_price_sek_kwh": 1.0,
                "pv_kwh": None,
                "batt_charge_kwh": 20.0,
                "batt_discharge_kwh": 8.0,
                "soc_start_percent": None,
                "soc_end_percent": None,
            },
            {
                "load_kwh": 3.0,
                "water_kwh": 0.0,
                "ev_charging_kwh": 0.0,
                "import_kwh": 1.0,
                "import_price_sek_kwh": 3.0,
                "export_price_sek_kwh": 0.0,
            },
        ],
    )
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
    comparison = series["grid_only_comparison"]
    assert comparison["grid_only_cost_sek"] == pytest.approx(14.8)
    assert comparison["ds_cost_sek"] == pytest.approx(4.5)
    assert comparison["saving_sek"] == pytest.approx(10.3)
    assert comparison["coverage"]["covered_slots"] == 2


@pytest.mark.asyncio
async def test_missing_hour_keeps_other_eligible_slots_and_exposes_exact_internal_gap(store):
    rows = [{"load_kwh": 1.0, "import_kwh": 0.5} for _ in range(8)]
    rows[3] = {
        "load_kwh": 1.0,
        "import_kwh": 0.5,
        "quality_flags": json.dumps({"source": "recorder", "exclude": True}),
    }
    await _add(store, rows)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(period="yesterday", store=store)
    comparison = series["grid_only_comparison"]
    assert comparison["coverage"] == {"covered_slots": 7, "total_slots": 96, "excluded_slots": 89}
    assert len(comparison["segments"]) == 2
    assert comparison["segments"][0]["end"] < comparison["segments"][1]["start"]
    assert len(comparison["points"]) == 2
    assert sum(point["grid_only_cost_sek"] for point in comparison["points"]) == pytest.approx(14.0)


@pytest.mark.asyncio
async def test_empty_and_unusable_periods_have_coverage_but_no_amounts(store):
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        empty = await get_cost_series(period="yesterday", store=store)
    comparison = empty["grid_only_comparison"]
    assert comparison["status"] == "no_data"
    assert comparison["coverage"] == {"covered_slots": 0, "total_slots": 96, "excluded_slots": 96}
    assert "saving_sek" not in comparison
    assert "points" not in comparison
    assert "segments" not in comparison
    await _add(store, [{"quality_flags": json.dumps({"source": "recorder", "exclude": True})}])
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        unusable = await get_cost_series(period="yesterday", store=store)
    comparison = unusable["grid_only_comparison"]
    assert comparison["status"] == "unavailable"
    assert comparison["reason"] == "no_usable_observations"
    assert "grid_only_cost_sek" not in comparison


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("day", "hours", "slots", "start_offset", "end_offset"),
    [
        (datetime(2026, 3, 29).date(), 23, 92, "+01:00", "+02:00"),
        (datetime(2026, 10, 25).date(), 25, 100, "+02:00", "+01:00"),
    ],
)
async def test_dst_axis_bounds_survive_unavailable_data(
    store, monkeypatch, day, hours, slots, start_offset, end_offset
):
    fixed_now = datetime(2026, 10, 26, 12, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz is not None else fixed_now.replace(tzinfo=None)

    from backend.api.routers import energy

    start = TZ.localize(datetime.combine(day, datetime.min.time()))
    end = TZ.localize(datetime.combine(day + timedelta(days=1), datetime.min.time()))
    monkeypatch.setattr(energy, "datetime", FrozenDateTime)
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(
            period="custom", start_date=day.isoformat(), end_date=day.isoformat(), store=store
        )
    comparison = series["grid_only_comparison"]
    assert comparison["status"] == "no_data"
    assert comparison["coverage"]["total_slots"] == slots
    assert comparison["time_axis"]["timezone"] == "Europe/Stockholm"
    assert comparison["time_axis"]["start"] == start.isoformat()
    assert comparison["time_axis"]["end"] == end.isoformat()
    assert end.astimezone(pytz.UTC) - start.astimezone(pytz.UTC) == timedelta(hours=hours)
    assert comparison["time_axis"]["start"].endswith(start_offset)
    assert comparison["time_axis"]["end"].endswith(end_offset)


@pytest.mark.asyncio
async def test_invalid_custom_range_keeps_existing_error_response(store):
    with patch("backend.api.routers.energy.load_yaml", return_value=CONFIG):
        series = await get_cost_series(
            period="custom", start_date="2026-10-05", end_date="2026-10-01", store=store
        )
    assert series["points"] == []
    assert "error" in series
    assert "grid_only_comparison" not in series
