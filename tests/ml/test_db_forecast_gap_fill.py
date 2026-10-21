"""PV gap filling in the planner's Aurora/DB forecast path (build_db_forecast_for_slots)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.forecasts import _get_forecast_data_aurora, build_db_forecast_for_slots
from backend.exceptions import PVForecastError

CONFIG = {
    "timezone": "UTC",
    "forecasting": {
        "active_forecast_version": "aurora",
        "aurora_load_enabled": True,
        "aurora_pv_enabled": True,
    },
}


def _pv_shape(ts: datetime) -> float:
    """Daytime-only PV curve: 0 at night, 1.0 kWh between 08:00 and 16:00."""
    return 1.0 if 8 <= ts.hour < 16 else 0.0


def _record(ts: datetime, pv: float, load: float = 0.5) -> dict:
    return {
        "slot_start": ts,
        "final": {"pv_kwh": pv, "load_kwh": load},
        "probabilistic": {"pv_p10": pv * 0.5, "pv_p90": pv * 1.5, "load_p10": 0.4, "load_p90": 0.6},
    }


def _day_records(first_day: datetime, days: int, *, until: datetime | None = None) -> list[dict]:
    records = []
    ts = first_day
    end = first_day + timedelta(days=days)
    while ts < end:
        if until is None or ts < until:
            records.append(_record(ts, _pv_shape(ts)))
        ts += timedelta(minutes=15)
    return records


def _slots(start: datetime, count: int) -> list[dict]:
    return [{"start_time": start + timedelta(minutes=15 * i)} for i in range(count)]


@pytest.mark.asyncio
async def test_long_outage_daytime_slots_get_daytime_values_not_zero():
    # Stored coverage ends at the end of day 3 (night-time zero); planning starts day 3
    # evening and spans the next 48 h, so day 4 and day 5 have no stored rows.
    first_day = datetime(2024, 6, 1, tzinfo=UTC)
    records = _day_records(first_day, 3)
    start = datetime(2024, 6, 3, 22, 0, tzinfo=UTC)
    price_slots = _slots(start, 48 * 4)

    with patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=records)):
        result = await build_db_forecast_for_slots(price_slots, CONFIG)

    assert len(result) == len(price_slots)
    for slot, out in zip(price_slots, result, strict=True):
        ts = slot["start_time"]
        assert out["pv_forecast_kwh"] == _pv_shape(ts), ts
    day4_noon = (datetime(2024, 6, 4, 12, 0, tzinfo=UTC) - start) // timedelta(minutes=15)
    assert result[day4_noon]["pv_forecast_kwh"] == 1.0
    assert result[day4_noon]["pv_estimated"] is True
    assert result[0]["pv_estimated"] is False
    # Probabilistic PV bounds are unknown for estimated slots
    assert result[day4_noon]["pv_p10"] is None


@pytest.mark.asyncio
async def test_slots_before_first_stored_row_use_later_day():
    # Only day 2 is stored; planning slots from day 1 take the earliest later day.
    records = _day_records(datetime(2024, 6, 2, tzinfo=UTC), 1)
    start = datetime(2024, 6, 1, 6, 0, tzinfo=UTC)
    price_slots = _slots(start, 24 * 4)

    with patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=records)):
        result = await build_db_forecast_for_slots(price_slots, CONFIG)

    for slot, out in zip(price_slots, result, strict=True):
        assert out["pv_forecast_kwh"] == _pv_shape(slot["start_time"])
        assert out["pv_estimated"] is (slot["start_time"].day == 1)


@pytest.mark.asyncio
async def test_small_interior_gap_is_interpolated():
    start = datetime(2024, 6, 3, 10, 0, tzinfo=UTC)
    price_slots = _slots(start, 6)
    records = [_record(start + timedelta(minutes=15 * i), v) for i, v in [(0, 1.0), (3, 4.0), (4, 4.0), (5, 4.0)]]

    with patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=records)):
        result = await build_db_forecast_for_slots(price_slots, CONFIG)

    assert [round(r["pv_forecast_kwh"], 6) for r in result] == [1.0, 2.0, 3.0, 4.0, 4.0, 4.0]
    assert [r["pv_estimated"] for r in result] == [False, True, True, False, False, False]


@pytest.mark.asyncio
async def test_no_stored_rows_returns_empty():
    with patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=[])):
        assert await build_db_forecast_for_slots(_slots(datetime(2024, 6, 3, tzinfo=UTC), 4), CONFIG) == []


async def _run_aurora(db_slots: list[dict], price_slots: list[dict]):
    with (
        patch("backend.core.forecasts.build_db_forecast_for_slots", new=AsyncMock(return_value=db_slots)),
        patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=[])),
        patch("backend.core.ha_client.get_load_profile_from_ha", new=AsyncMock(return_value=[0.4] * 96)),
        patch("backend.health.record_forecast_error") as record,
    ):
        result = await _get_forecast_data_aurora(price_slots, CONFIG)
    return result, record


@pytest.mark.asyncio
async def test_estimated_slots_are_counted_and_reported_degraded():
    price_slots = _slots(datetime(2024, 6, 4, 12, 0, tzinfo=UTC), 4)
    db_slots = [
        {"pv_forecast_kwh": 1.0, "load_forecast_kwh": 0.5, "pv_estimated": est}
        for est in (False, True, True, True)
    ]

    result, record = await _run_aurora(db_slots, price_slots)

    record.assert_called_once()
    error = record.call_args.args[0]
    assert not isinstance(error, PVForecastError)
    assert record.call_args.kwargs["context"]["estimated_slots"] == 3
    assert record.call_args.kwargs["context"]["total_slots"] == 4
    assert [s["pv_estimated"] for s in result["slots"]] == [False, True, True, True]


@pytest.mark.asyncio
async def test_no_stored_rows_is_learning_period_not_an_error():
    price_slots = _slots(datetime(2024, 6, 4, 12, 0, tzinfo=UTC), 4)

    result, record = await _run_aurora([], price_slots)

    assert result["slots"] == []
    record.assert_not_called()


@pytest.mark.asyncio
async def test_full_coverage_reports_nothing():
    price_slots = _slots(datetime(2024, 6, 4, 12, 0, tzinfo=UTC), 2)
    db_slots = [{"pv_forecast_kwh": 1.0, "load_forecast_kwh": 0.5, "pv_estimated": False}] * 2

    _, record = await _run_aurora(db_slots, price_slots)

    record.assert_not_called()


@pytest.mark.asyncio
async def test_fold_hour_pandas_slot_matches_stored_record_exactly():
    from utils.time_utils import dst_safe_date_range

    config = {**CONFIG, "timezone": "Europe/Stockholm"}
    start = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)
    index = dst_safe_date_range(start, start + timedelta(hours=2), "15min", "Europe/Stockholm", inclusive="left")
    price_slots = [{"start_time": ts} for ts in index]
    fold_idx = next(i for i, ts in enumerate(index) if ts.fold == 1)
    records = [_record(ts.to_pydatetime().astimezone(UTC), 0.1 * i) for i, ts in enumerate(index)]

    with patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=records)):
        result = await build_db_forecast_for_slots(price_slots, config)

    assert len(result) == len(price_slots)
    assert not any(out["pv_estimated"] for out in result)
    assert result[fold_idx]["pv_forecast_kwh"] == pytest.approx(0.1 * fold_idx)
