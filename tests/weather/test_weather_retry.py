"""Open-Meteo weather fetch retries transient HTTP failures before giving up."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz
import requests

from ml import weather
from ml.weather import get_weather_series

START = datetime(2026, 2, 15, 12, 0, tzinfo=pytz.UTC)
END = datetime(2026, 2, 15, 14, 0, tzinfo=pytz.UTC)
CONFIG = {"timezone": "UTC", "system": {"location": {"latitude": 59.3, "longitude": 18.1}}}


def _response(status: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if status >= 400:
        err_resp = requests.Response()
        err_resp.status_code = status
        resp.raise_for_status.side_effect = requests.HTTPError(str(status), response=err_resp)
    resp.json.return_value = {
        "hourly": {
            "time": ["2026-02-15T12:00", "2026-02-15T13:00", "2026-02-15T14:00"],
            "temperature_2m": [10.0, 20.0, 30.0],
            "cloud_cover": [0.0, 50.0, 100.0],
            "shortwave_radiation": [0.0, 400.0, 800.0],
        }
    }
    return resp


@pytest.fixture(autouse=True)
def _env():
    weather._weather_cache.clear()
    with patch("backend.core.open_meteo_retry.BACKOFF_S", (0.0, 0.0)):
        yield
    weather._weather_cache.clear()


def test_503_then_200_returns_populated_frame():
    with patch("ml.weather.requests.get", side_effect=[_response(503), _response(200)]) as get:
        df = get_weather_series(START, END, config=CONFIG)
    assert get.call_count == 2
    assert not df.empty


def test_persistent_503_gives_up_after_three_attempts():
    with patch("ml.weather.requests.get", side_effect=lambda *a, **k: _response(503)) as get:
        df = get_weather_series(START, END, config=CONFIG)
    assert get.call_count == 3
    assert df.empty


def test_400_is_not_retried():
    with patch("ml.weather.requests.get", side_effect=lambda *a, **k: _response(400)) as get:
        df = get_weather_series(START, END, config=CONFIG)
    assert get.call_count == 1
    assert df.empty
