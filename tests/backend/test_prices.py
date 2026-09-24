import logging
from datetime import datetime, timedelta

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
