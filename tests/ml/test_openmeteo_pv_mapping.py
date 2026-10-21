"""Live Open-Meteo PV slot mapping: direct lookup and minimal fetched history."""

import time
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core.forecasts import _get_forecast_data_async
from backend.exceptions import PVForecastError

TZ_NAME = "Europe/Stockholm"
LOCAL_TZ = pytz.timezone(TZ_NAME)
# The library returns fixed-offset aware keys; slots are pytz-aware local timestamps.
FIXED_OFFSET = timezone(timedelta(hours=2))


def _config(arrays: list[dict[str, float]]) -> dict:
    return {
        "timezone": TZ_NAME,
        "system": {
            "location": {"latitude": 59.3, "longitude": 18.1},
            "solar_arrays": arrays,
        },
    }


def _local_slots(count: int) -> list[dict]:
    start = LOCAL_TZ.localize(datetime(2026, 6, 21, 0, 0))
    return [{"start_time": LOCAL_TZ.normalize(start + timedelta(minutes=15 * i))} for i in range(count)]


def _prod_shaped_series() -> dict[datetime, float]:
    """~7,830 15-min entries starting ~66 days before the first slot, fixed-offset keys."""
    first = datetime(2026, 6, 21, 0, 0, tzinfo=FIXED_OFFSET) - timedelta(days=66)
    return {first + timedelta(minutes=15 * i): float(i % 97) * 10.0 for i in range(7830)}


def _mock_forecast_class(mock_cls: MagicMock, series_per_array: list[dict]) -> None:
    instances = []
    for series in series_per_array:
        estimate = MagicMock()
        estimate.watts = series
        inst = AsyncMock()
        inst.estimate.return_value = estimate
        inst.__aenter__.return_value = inst
        inst.__aexit__.return_value = None
        instances.append(inst)
    mock_cls.side_effect = instances


def _reference(series: dict[datetime, float], slots: list[dict]) -> list[float]:
    by_utc = {k.astimezone(UTC): v for k, v in series.items()}
    out = []
    for slot in slots:
        t = slot["start_time"]
        rounded = t.replace(minute=(t.minute // 15) * 15, second=0, microsecond=0)
        out.append(by_utc.get(rounded.astimezone(UTC), 0.0) * 0.25 / 1000.0)
    return out


@pytest.mark.asyncio
async def test_prod_shaped_series_matches_utc_instant_reference():
    series = _prod_shaped_series()
    slots = _local_slots(672)
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
    ):
        _mock_forecast_class(mock_cls, [series])
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))

    expected = _reference(series, slots)
    assert any(v > 0 for v in expected)
    assert [s["pv_forecast_kwh"] for s in result["slots"]] == expected
    assert [s["openmeteo_pv_forecast_kwh"] for s in result["slots"]] == expected


@pytest.fixture(autouse=True)
def forecast_db(tmp_path):
    """Point stored-baseline lookups at an empty per-test DB, never data/ in the cwd."""
    db_path = tmp_path / "planner_learning.db"
    with patch("backend.core.forecasts.get_forecast_db_path", return_value=str(db_path)):
        yield db_path


async def _seed_openmeteo_baselines(db_path, rows: list[dict]) -> None:
    from sqlalchemy import create_engine

    from backend.learning.models import Base
    from backend.learning.store import LearningStore

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    store = LearningStore(str(db_path), LOCAL_TZ)
    try:
        await store.store_forecasts(rows, "aurora")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_slot_without_matching_key_uses_stored_estimate(forecast_db):
    slots = _local_slots(2)
    series = {slots[0]["start_time"].astimezone(FIXED_OFFSET): 2000.0}
    previous_day = slots[1]["start_time"] - timedelta(days=1)
    await _seed_openmeteo_baselines(
        forecast_db,
        [{"slot_start": previous_day, "pv_forecast_kwh": 0.3, "openmeteo_pv_forecast_kwh": 0.3}],
    )
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
    ):
        _mock_forecast_class(mock_cls, [series])
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))

    assert [s["pv_forecast_kwh"] for s in result["slots"]] == [0.5, 0.3]


@pytest.mark.asyncio
async def test_slot_without_matching_key_and_no_stored_db_raises_pv_error(forecast_db):
    """Fresh install: no slot_forecasts table yet must surface PVForecastError, not SQL errors."""
    assert not forecast_db.exists()
    slots = _local_slots(2)
    series = {slots[0]["start_time"].astimezone(FIXED_OFFSET): 2000.0}
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
        pytest.raises(PVForecastError),
    ):
        _mock_forecast_class(mock_cls, [series])
        await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))


@pytest.mark.asyncio
async def test_every_array_requests_one_past_day():
    slots = _local_slots(1)
    series = {slots[0]["start_time"]: 100.0}
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
    ):
        _mock_forecast_class(mock_cls, [series, series])
        await _get_forecast_data_async(slots, _config([{"kwp": 10.0}, {"kwp": 5.0}]))

    assert mock_cls.call_count == 2
    for call in mock_cls.call_args_list:
        assert call.kwargs.get("past_days") == 1


@pytest.mark.asyncio
async def test_long_series_maps_fast_and_matches_trimmed_series():
    series = _prod_shaped_series()
    slots = _local_slots(672)
    first_slot = slots[0]["start_time"]
    trimmed = {k: v for k, v in series.items() if k >= first_slot}

    results = []
    elapsed = []
    for s in (series, trimmed):
        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
            patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
        ):
            _mock_forecast_class(mock_cls, [s])
            t0 = time.perf_counter()
            result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))
            elapsed.append(time.perf_counter() - t0)
        results.append([slot["pv_forecast_kwh"] for slot in result["slots"]])

    assert results[0] == results[1]
    assert elapsed[0] < 1.0


def _dst_slots(start_utc: datetime, end_utc: datetime) -> list[dict]:
    from utils.time_utils import dst_safe_date_range

    index = dst_safe_date_range(start_utc, end_utc, "15min", TZ_NAME, inclusive="left")
    return [{"start_time": ts} for ts in index]


async def _run_dst_case(slots: list[dict], offset: timezone) -> tuple[dict, MagicMock, MagicMock]:
    series = {
        slot["start_time"].to_pydatetime().astimezone(offset): 1000.0 + i
        for i, slot in enumerate(slots)
    }
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
        patch("backend.health.record_forecast_error") as record_error,
        patch("backend.health.clear_forecast_errors") as clear_errors,
    ):
        _mock_forecast_class(mock_cls, [series])
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))
    return result, record_error, clear_errors


@pytest.mark.asyncio
async def test_autumn_fold_hour_slots_all_match_fixed_offset_keys():
    start = datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    slots = _dst_slots(start, start + timedelta(days=2))
    assert any(getattr(s["start_time"], "fold", 0) == 1 for s in slots)

    result, record_error, clear_errors = await _run_dst_case(slots, FIXED_OFFSET)

    expected = [(1000.0 + i) * 0.25 / 1000.0 for i in range(len(slots))]
    assert [s["pv_forecast_kwh"] for s in result["slots"]] == expected
    assert not any(s.get("pv_estimated") for s in result["slots"])
    record_error.assert_not_called()
    clear_errors.assert_called_once()


@pytest.mark.asyncio
async def test_spring_forward_slots_all_match_fixed_offset_keys():
    start = datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    slots = _dst_slots(start, start + timedelta(days=2))

    result, record_error, clear_errors = await _run_dst_case(slots, timezone(timedelta(hours=1)))

    expected = [(1000.0 + i) * 0.25 / 1000.0 for i in range(len(slots))]
    assert [s["pv_forecast_kwh"] for s in result["slots"]] == expected
    assert not any(s.get("pv_estimated") for s in result["slots"])
    record_error.assert_not_called()
    clear_errors.assert_called_once()


@pytest.mark.asyncio
async def test_stored_baseline_in_fold_hour_matches_fold_timestamp_exactly(forecast_db):
    from backend.core.forecasts import _get_stored_openmeteo_pv_for_slots

    start = datetime(2026, 10, 25, 0, 0, tzinfo=UTC)  # 02:00+02:00, then 02:00+01:00 at 01:00Z
    slots = _dst_slots(start, start + timedelta(hours=2))
    fold_idx = next(i for i, s in enumerate(slots) if s["start_time"].fold == 1)
    await _seed_openmeteo_baselines(
        forecast_db,
        [
            {
                "slot_start": s["start_time"].to_pydatetime().astimezone(UTC),
                "pv_forecast_kwh": 0.1 * i,
                "openmeteo_pv_forecast_kwh": 0.1 * i,
            }
            for i, s in enumerate(slots)
        ],
    )

    filled = await _get_stored_openmeteo_pv_for_slots(slots, _config([{"kwp": 10.0}]))

    assert filled is not None
    values, _daily, estimated = filled
    assert estimated == []
    assert values[fold_idx] == pytest.approx(0.1 * fold_idx)
