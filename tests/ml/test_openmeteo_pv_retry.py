"""Per-array retry of transient Open-Meteo PV failures before stored-estimate fallback."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from open_meteo_solar_forecast.exceptions import (
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastConnectionError,
)

from backend.core.forecasts import _get_forecast_data_async
from backend.exceptions import PVForecastError

LOCAL_TZ = pytz.timezone("Europe/Stockholm")


def _config(arrays: list[dict[str, float]]) -> dict:
    return {
        "timezone": "Europe/Stockholm",
        "system": {"location": {"latitude": 59.3, "longitude": 18.1}, "solar_arrays": arrays},
    }


def _slots(count: int) -> list[dict]:
    start = LOCAL_TZ.localize(datetime(2026, 6, 21, 12, 0))
    return [
        {"start_time": LOCAL_TZ.normalize(start + timedelta(minutes=15 * i))} for i in range(count)
    ]


def _instance(result: dict | Exception) -> AsyncMock:
    inst = AsyncMock()
    if isinstance(result, Exception):
        inst.estimate.side_effect = result
    else:
        estimate = MagicMock()
        estimate.watts = result
        inst.estimate.return_value = estimate
    inst.__aenter__.return_value = inst
    inst.__aexit__.return_value = None
    return inst


@pytest.fixture(autouse=True)
def _env(tmp_path):
    """Zero backoff, isolated stored-estimate DB and a fixed HA load profile."""
    with (
        patch("backend.core.open_meteo_retry.BACKOFF_S", (0.0, 0.0)),
        patch("backend.core.forecasts.get_forecast_db_path", return_value=str(tmp_path / "db.db")),
        patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
    ):
        yield


@pytest.mark.asyncio
async def test_second_array_transient_failure_retries_only_that_array():
    slots = _slots(1)
    t = slots[0]["start_time"]
    arr1 = [_instance({t: 1000.0})]
    arr2 = [_instance(OpenMeteoSolarForecastConnectionError("503")), _instance({t: 2000.0})]
    by_kwp = {10.0: arr1, 5.0: arr2}

    def factory(**kwargs):
        return by_kwp[kwargs["dc_kwp"]].pop(0)

    with (
        patch("backend.core.forecasts.OpenMeteoSolarForecast", side_effect=factory) as mock_cls,
        patch(
            "backend.core.forecasts._get_stored_openmeteo_pv_for_slots", new=AsyncMock()
        ) as stored,
        patch("backend.health.record_forecast_error") as record_error,
    ):
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}, {"kwp": 5.0}]))

    kwps = [c.kwargs["dc_kwp"] for c in mock_cls.call_args_list]
    assert kwps.count(10.0) == 1
    assert kwps.count(5.0) == 2
    assert result["slots"][0]["pv_forecast_kwh"] == pytest.approx(3000.0 * 0.25 / 1000.0)
    stored.assert_not_awaited()
    record_error.assert_not_called()


@pytest.mark.asyncio
async def test_persistent_transient_failure_uses_stored_estimate():
    slots = _slots(1)
    fallback = ([0.4], {slots[0]["start_time"].date().isoformat(): 0.4}, [0])
    with (
        patch(
            "backend.core.forecasts.OpenMeteoSolarForecast",
            side_effect=lambda **_: _instance(OpenMeteoSolarForecastConnectionError("503")),
        ) as mock_cls,
        patch(
            "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
            new=AsyncMock(return_value=fallback),
        ) as stored,
    ):
        result = await _get_forecast_data_async(slots, _config([{"kwp": 10.0}]))

    assert mock_cls.call_count == 3
    stored.assert_awaited_once()
    assert result["slots"][0]["pv_forecast_kwh"] == 0.4


@pytest.mark.asyncio
async def test_persistent_transient_failure_without_stored_data_raises():
    with (
        patch(
            "backend.core.forecasts.OpenMeteoSolarForecast",
            side_effect=lambda **_: _instance(OpenMeteoSolarForecastConnectionError("503")),
        ) as mock_cls,
        pytest.raises(PVForecastError),
    ):
        await _get_forecast_data_async(_slots(1), _config([{"kwp": 10.0}]))
    assert mock_cls.call_count == 3


@pytest.mark.asyncio
async def test_config_error_is_not_retried():
    with (
        patch(
            "backend.core.forecasts.OpenMeteoSolarForecast",
            side_effect=lambda **_: _instance(OpenMeteoSolarForecastConfigError("422")),
        ) as mock_cls,
        patch(
            "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
            new=AsyncMock(return_value=None),
        ) as stored,
        pytest.raises(PVForecastError),
    ):
        await _get_forecast_data_async(_slots(1), _config([{"kwp": 10.0}]))
    assert mock_cls.call_count == 1
    stored.assert_awaited_once()
