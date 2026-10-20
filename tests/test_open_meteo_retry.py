"""Bounded retry helper and transient-error classification for Open-Meteo fetches."""

from unittest.mock import MagicMock, patch

import aiohttp
import pytest
import requests
from open_meteo_solar_forecast.exceptions import (
    OpenMeteoSolarForecastAuthenticationError,
    OpenMeteoSolarForecastConfigError,
    OpenMeteoSolarForecastConnectionError,
    OpenMeteoSolarForecastError,
    OpenMeteoSolarForecastInvalidModel,
    OpenMeteoSolarForecastRatelimitError,
    OpenMeteoSolarForecastRequestError,
)

from backend.core import open_meteo_retry
from backend.core.open_meteo_retry import (
    BACKOFF_S,
    MAX_ATTEMPTS,
    is_transient_http_error,
    is_transient_pv_error,
    retry_async,
    retry_sync,
)


def _response_error(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(MagicMock(), (), status=status)


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def test_policy_bounds():
    assert MAX_ATTEMPTS == 3
    assert BACKOFF_S == (2.0, 4.0)
    assert sum(BACKOFF_S) <= 10.0


@pytest.mark.parametrize(
    "exc",
    [
        OpenMeteoSolarForecastConnectionError("503"),
        OpenMeteoSolarForecastRatelimitError("429"),
        _response_error(500),
        _response_error(504),
        _response_error(429),
        aiohttp.ClientConnectionError("reset"),
        TimeoutError(),
    ],
)
def test_pv_transient(exc):
    assert is_transient_pv_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        OpenMeteoSolarForecastRequestError("400"),
        OpenMeteoSolarForecastAuthenticationError("401"),
        OpenMeteoSolarForecastAuthenticationError("403"),
        OpenMeteoSolarForecastConfigError("422"),
        OpenMeteoSolarForecastInvalidModel("model"),
        OpenMeteoSolarForecastError("not json"),
        _response_error(400),
        _response_error(404),
        ValueError("bad"),
    ],
)
def test_pv_permanent(exc):
    assert not is_transient_pv_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        requests.ConnectionError("down"),
        requests.Timeout("slow"),
        _http_error(500),
        _http_error(503),
        _http_error(429),
    ],
)
def test_http_transient(exc):
    assert is_transient_http_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        _http_error(400),
        _http_error(401),
        _http_error(403),
        _http_error(422),
        requests.HTTPError("no response"),
        ValueError("bad json"),
    ],
)
def test_http_permanent(exc):
    assert not is_transient_http_error(exc)


class _Sleeps:
    def __init__(self):
        self.calls: list[float] = []

    def sync(self, delay: float) -> None:
        self.calls.append(delay)

    async def async_(self, delay: float) -> None:
        self.calls.append(delay)


def _always_transient(_exc: BaseException) -> bool:
    return True


def _never_transient(_exc: BaseException) -> bool:
    return False


def _warning_messages(mock_logger: MagicMock) -> list[str]:
    return [call.args[0] % call.args[1:] for call in mock_logger.warning.call_args_list]


def test_sync_transient_then_success():
    sleeps = _Sleeps()
    fn = MagicMock(side_effect=[requests.ConnectionError("blip"), "ok"])
    with patch.object(open_meteo_retry, "logger") as mock_logger:
        result = retry_sync(fn, label="weather", is_transient=_always_transient, sleep=sleeps.sync)
    assert result == "ok"
    assert fn.call_count == 2
    assert sleeps.calls == [2.0]
    warnings = _warning_messages(mock_logger)
    assert len(warnings) == 1
    msg = warnings[0]
    assert "weather" in msg and "attempt 1/3" in msg and "blip" in msg and "2s" in msg


def test_sync_persistent_transient_stops_after_three():
    sleeps = _Sleeps()
    errors = [requests.ConnectionError(f"e{i}") for i in range(5)]
    fn = MagicMock(side_effect=errors)
    with pytest.raises(requests.ConnectionError) as info:
        retry_sync(fn, label="weather", is_transient=_always_transient, sleep=sleeps.sync)
    assert info.value is errors[2]
    assert fn.call_count == 3
    assert sleeps.calls == [2.0, 4.0]


def test_sync_permanent_single_call():
    sleeps = _Sleeps()
    fn = MagicMock(side_effect=ValueError("nope"))
    with pytest.raises(ValueError):
        retry_sync(fn, label="weather", is_transient=_never_transient, sleep=sleeps.sync)
    assert fn.call_count == 1
    assert sleeps.calls == []


@pytest.mark.asyncio
async def test_async_transient_then_success():
    sleeps = _Sleeps()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OpenMeteoSolarForecastConnectionError("503")
        return "ok"

    with patch.object(open_meteo_retry, "logger") as mock_logger:
        result = await retry_async(
            fn, label="PV array 1", is_transient=is_transient_pv_error, sleep=sleeps.async_
        )
    assert result == "ok"
    assert calls == 2
    assert sleeps.calls == [2.0]
    assert any("PV array 1" in m and "attempt 1/3" in m for m in _warning_messages(mock_logger))


@pytest.mark.asyncio
async def test_async_persistent_transient_stops_after_three():
    sleeps = _Sleeps()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise OpenMeteoSolarForecastConnectionError(f"503 #{calls}")

    with pytest.raises(OpenMeteoSolarForecastConnectionError, match="#3"):
        await retry_async(
            fn, label="PV array 1", is_transient=is_transient_pv_error, sleep=sleeps.async_
        )
    assert calls == 3
    assert sleeps.calls == [2.0, 4.0]


@pytest.mark.asyncio
async def test_async_permanent_single_call():
    sleeps = _Sleeps()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        raise OpenMeteoSolarForecastConfigError("422")

    with pytest.raises(OpenMeteoSolarForecastConfigError):
        await retry_async(
            fn, label="PV array 1", is_transient=is_transient_pv_error, sleep=sleeps.async_
        )
    assert calls == 1
    assert sleeps.calls == []
