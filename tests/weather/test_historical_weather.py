"""Historical weather for training: sources, per-day cache, DST and failure handling."""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz
import requests

from ml import weather
from ml.weather import get_historical_weather_series

UTC = pytz.UTC
STOCKHOLM = pytz.timezone("Europe/Stockholm")
# Pinned "now" (2026-07-01 12:00 UTC) so every requested day counts as completed.
NOW_EPOCH = datetime(2026, 7, 1, 12, 0, tzinfo=UTC).timestamp()
CONFIG = {"timezone": "UTC", "system": {"location": {"latitude": 59.3, "longitude": 18.1}}}
HISTORICAL = "historical-forecast-api.open-meteo.com"
ARCHIVE = "archive-api.open-meteo.com"
ARCHIVE_TEMP = 99.0


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _hourly(first: date, last: date, *, temp: float, blank: set[date] = frozenset()) -> dict:
    hours = pd.date_range(first, pd.Timestamp(last) + pd.Timedelta(hours=23), freq="h")
    return {
        "hourly": {
            "time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
            "temperature_2m": [None if h.date() in blank else temp for h in hours],
            "cloud_cover": [None if h.date() in blank else 50.0 for h in hours],
            "shortwave_radiation": [None if h.date() in blank else 300.0 for h in hours],
        }
    }


class _Api:
    """Fake requests.get serving both endpoints; records the calls."""

    def __init__(self, historical_blank: set[date] = frozenset()):
        self.calls: list[tuple[str, dict]] = []
        self.historical_blank = historical_blank

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        first = date.fromisoformat(params["start_date"])
        last = date.fromisoformat(params["end_date"])
        if ARCHIVE in url:
            return _response(_hourly(first, last, temp=ARCHIVE_TEMP))
        return _response(_hourly(first, last, temp=10.0, blank=self.historical_blank))


@pytest.fixture(autouse=True)
def _env():
    weather._historical_day_cache.clear()
    with (
        patch("backend.core.open_meteo_retry.BACKOFF_S", (0.0, 0.0)),
        patch("ml.weather.time.time", return_value=NOW_EPOCH),
    ):
        yield
    weather._historical_day_cache.clear()


def _window(first: datetime, last: datetime, tz=UTC):
    return tz.localize(first), tz.localize(last)


def test_three_days_give_288_quarter_hour_slots_with_all_columns():
    api = _Api()
    start, end = _window(datetime(2026, 6, 14), datetime(2026, 6, 17))
    with patch("ml.weather.requests.get", side_effect=api):
        df = get_historical_weather_series(start, end, config=CONFIG)

    assert len(df) == 288
    assert set(df.columns) == {"temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"}
    assert (df.index.to_series().diff().dropna() == pd.Timedelta(minutes=15)).all()
    assert not df.isna().any().any()
    assert len(api.calls) == 1
    assert HISTORICAL in api.calls[0][0]
    assert api.calls[0][1]["start_date"] == "2026-06-14"
    assert api.calls[0][1]["end_date"] == "2026-06-16"


def test_window_across_clock_change_has_no_duplicate_or_missing_instants():
    start, end = _window(datetime(2026, 10, 24), datetime(2026, 10, 27), STOCKHOLM)
    with patch("ml.weather.requests.get", side_effect=_Api()):
        df = get_historical_weather_series(
            start, end, config={**CONFIG, "timezone": "Europe/Stockholm"}
        )

    # 25-hour day on 2026-10-25: 72 + 1 hours of 15-minute slots.
    assert len(df) == 73 * 4
    assert df.index.is_unique
    instants = df.index.tz_convert("UTC").to_series()
    assert (instants.diff().dropna() == pd.Timedelta(minutes=15)).all()
    assert instants.iloc[0] == pd.Timestamp(start).tz_convert("UTC")


def test_second_call_makes_no_request():
    api = _Api()
    start, end = _window(datetime(2026, 6, 14), datetime(2026, 6, 17))
    with patch("ml.weather.requests.get", side_effect=api):
        first = get_historical_weather_series(start, end, config=CONFIG)
        second = get_historical_weather_series(start, end, config=CONFIG)

    assert len(api.calls) == 1
    pd.testing.assert_frame_equal(first, second)


def test_archive_fills_dates_the_historical_forecast_lacks():
    api = _Api(historical_blank={date(2026, 6, 15)})
    start, end = _window(datetime(2026, 6, 14), datetime(2026, 6, 17))
    with patch("ml.weather.requests.get", side_effect=api):
        df = get_historical_weather_series(start, end, config=CONFIG)

    assert [HISTORICAL in url for url, _ in api.calls] == [True, False]
    archive_params = api.calls[1][1]
    assert archive_params["start_date"] == archive_params["end_date"] == "2026-06-15"
    assert df.loc[UTC.localize(datetime(2026, 6, 15, 12)), "temp_c"] == ARCHIVE_TEMP
    assert df.loc[UTC.localize(datetime(2026, 6, 14, 12)), "temp_c"] == 10.0
    assert len(df) == 288


def test_request_failure_returns_empty_frame_and_warns():
    start, end = _window(datetime(2026, 6, 14), datetime(2026, 6, 17))
    with (
        patch("ml.weather.requests.get", side_effect=requests.ConnectionError("down")),
        patch.object(weather.logger, "warning") as warning,
    ):
        df = get_historical_weather_series(start, end, config=CONFIG)

    assert df.empty
    messages = [call.args[0] for call in warning.call_args_list]
    assert any("Failed to fetch" in m for m in messages)
    assert any("No historical weather" in m for m in messages)
