import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytz

from backend.core import prices as prices_mod
from backend.core.prices import _process_nordpool_data

local_tz = pytz.timezone("Europe/Stockholm")


def _make_entry(hour: int, value: float, base_date: datetime | None = None) -> dict:
    if base_date is None:
        base_date = datetime(2026, 4, 28)
    start = local_tz.localize(base_date.replace(hour=hour, minute=0, second=0, microsecond=0))
    end = start + timedelta(hours=1)
    return {"start": start, "end": end, "value": value}


def test_dedup_keeps_nordpool_over_fallback():
    """Duplicate start_time values: first occurrence (Nordpool) wins."""
    nordpool_entry = _make_entry(10, 500.0)
    fallback_entry = _make_entry(10, 300.0)

    all_entries = [nordpool_entry, fallback_entry, _make_entry(11, 600.0)]

    result = _process_nordpool_data(all_entries, {"timezone": "Europe/Stockholm"})

    assert len(result) == 2

    slot_10 = [s for s in result if s["start_time"].hour == 10]
    assert len(slot_10) == 1
    assert slot_10[0]["export_price_sek_kwh"] == pytest.approx(500.0 / 1000.0)


def test_process_tags_price_source():
    """Real entries default to "nordpool"; fallback entries keep "forecast"."""
    fallback = {**_make_entry(11, 300.0), "price_source": "forecast"}
    result = _process_nordpool_data(
        [_make_entry(10, 500.0), fallback], {"timezone": "Europe/Stockholm"}
    )
    sources = {s["start_time"].hour: s["price_source"] for s in result}
    assert sources == {10: "nordpool", 11: "forecast"}


@pytest.mark.asyncio
async def test_known_spot_excludes_forecast_fallback(monkeypatch):
    processed = _process_nordpool_data(
        [_make_entry(10, 2070.0), {**_make_entry(11, 240.0), "price_source": "forecast"}],
        {"timezone": "Europe/Stockholm"},
    )

    async def fake_fetch(_path="config.yaml"):
        return processed

    monkeypatch.setattr(prices_mod, "get_nordpool_data", fake_fetch)
    known = await prices_mod.get_known_spot_by_slot()

    # Hourly entry expands to four quarter-hour keys; the fallback hour is absent.
    base = local_tz.localize(datetime(2026, 4, 28, 10))
    assert known == {base + timedelta(minutes=15 * i): pytest.approx(2.07) for i in range(4)}


@pytest.mark.asyncio
async def test_known_spot_fetch_failure_returns_empty(monkeypatch, caplog):
    async def failing_fetch(_path="config.yaml"):
        raise RuntimeError("boom")

    monkeypatch.setattr(prices_mod, "get_nordpool_data", failing_fetch)
    with caplog.at_level(logging.WARNING, logger="darkstar.core.prices"):
        known = await prices_mod.get_known_spot_by_slot()

    assert known == {}
    assert "using forecasts only" in caplog.text


@pytest.mark.asyncio
async def test_known_spot_empty_data_warns(monkeypatch, caplog):
    async def empty_fetch(_path="config.yaml"):
        return []

    monkeypatch.setattr(prices_mod, "get_nordpool_data", empty_fetch)
    with caplog.at_level(logging.WARNING, logger="darkstar.core.prices"):
        known = await prices_mod.get_known_spot_by_slot()

    assert known == {}
    assert "using forecasts only" in caplog.text


def test_process_carries_forecast_days_ahead_only_when_present():
    forecast = {**_make_entry(11, 300.0), "price_source": "forecast", "forecast_days_ahead": 2}
    result = _process_nordpool_data([_make_entry(10, 500.0), forecast], {"timezone": "Europe/Stockholm"})
    by_hour = {s["start_time"].hour: s for s in result}
    assert "forecast_days_ahead" not in by_hour[10]
    assert by_hour[11]["forecast_days_ahead"] == 2
    assert by_hour[11]["price_source"] == "forecast"


@pytest.mark.asyncio
async def test_nordpool_data_with_forecast_fallback_is_continuous_across_midnight(
    monkeypatch, tmp_path
):
    """Published today + D+1 forecast fallback: no gap at midnight, horizon carried."""
    day = datetime(2026, 4, 28)
    today_start = local_tz.localize(day)
    tomorrow_start = today_start + timedelta(days=1)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return local_tz.localize(datetime(2026, 4, 28, 5, 0)).astimezone(tz)

    async def fake_fetch_day(client, d, area, resolution, tz):
        return [
            {
                "start": today_start + timedelta(minutes=15 * i),
                "end": today_start + timedelta(minutes=15 * (i + 1)),
                "value": 500.0,
            }
            for i in range(96)
        ]

    fallback = [
        {
            "slot_start": (tomorrow_start + timedelta(minutes=15 * i)).isoformat(),
            "spot_p50": 0.4,
            "forecast_days_ahead": 2,
        }
        for i in range(96)
    ]
    cache = MagicMock()
    cache.get.return_value = None
    monkeypatch.setattr(prices_mod, "datetime", FrozenDateTime)
    monkeypatch.setattr(prices_mod, "cache_sync", cache)
    monkeypatch.setattr(prices_mod, "_fetch_day", fake_fetch_day)
    monkeypatch.setattr(prices_mod, "_save_last_good", AsyncMock())
    monkeypatch.setattr(prices_mod, "Prices", MagicMock())
    monkeypatch.setattr(
        "ml.price_forecast.get_d1_price_forecast_fallback", AsyncMock(return_value=fallback)
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "timezone: Europe/Stockholm\nnordpool:\n  price_area: SE3\n  resolution_minutes: 15\n"
    )

    result = await prices_mod.get_nordpool_data(str(config_path))

    assert len(result) == 192
    starts = [r["start_time"] for r in result]
    assert all(b - a == timedelta(minutes=15) for a, b in zip(starts, starts[1:], strict=False))
    published = [r for r in result if r["start_time"] < tomorrow_start]
    forecast_slots = [r for r in result if r["start_time"] >= tomorrow_start]
    assert all(r["price_source"] == "nordpool" for r in published)
    assert all("forecast_days_ahead" not in r for r in published)
    assert all(
        r["price_source"] == "forecast" and r["forecast_days_ahead"] == 2 for r in forecast_slots
    )
