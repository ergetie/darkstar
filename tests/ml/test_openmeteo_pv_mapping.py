"""Live Open-Meteo PV slot mapping: direct lookup and minimal fetched history."""

import time
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core.forecasts import _get_forecast_data_async

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


@pytest.mark.asyncio
async def test_slot_without_matching_key_gets_zero():
    slots = _local_slots(2)
    series = {slots[0]["start_time"].astimezone(FIXED_OFFSET): 2000.0}
    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast") as mock_cls,
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
    ):
        _mock_forecast_class(mock_cls, [series])
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))

    assert [s["pv_forecast_kwh"] for s in result["slots"]] == [0.5, 0.0]


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
