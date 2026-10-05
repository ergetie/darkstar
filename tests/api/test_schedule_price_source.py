"""Schedule slots are tagged "nordpool" only when their price is published."""

from datetime import datetime

import pytz

from backend.api.routers.schedule import _tag_price_source

TZ = pytz.timezone("Europe/Stockholm")


def _p(hour: int, source: str) -> dict:
    return {"start_time": TZ.localize(datetime(2026, 10, 6, hour)), "price_source": source}


def test_published_forecast_and_missing_prices():
    slots = [
        {"start_time": "2026-10-06T10:00:00+02:00"},
        {"start_time": "2026-10-06T11:00:00+02:00"},
        {"start_time": "2026-10-06T12:00:00+02:00"},
        {"start_time": None},
    ]
    _tag_price_source(slots, [_p(10, "nordpool"), _p(11, "forecast")], TZ)
    assert [s.get("price_source") for s in slots] == ["nordpool", "forecast", "forecast", None]


def test_entries_without_source_count_as_published():
    slots = [{"start_time": "2026-10-06T10:00:00+02:00"}]
    _tag_price_source(slots, [{"start_time": TZ.localize(datetime(2026, 10, 6, 10))}], TZ)
    assert slots[0]["price_source"] == "nordpool"
