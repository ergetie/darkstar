"""Resilience of the Nordpool price feed: partial results and the last-good store."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
import yaml

from backend.core import prices
from backend.core.cache import cache_sync

TZ = pytz.timezone("Europe/Stockholm")
TODAY = date(2026, 11, 20)
TOMORROW = TODAY + timedelta(days=1)
AFTER_PUBLISH = TZ.localize(datetime(2026, 11, 20, 14, 0))
BEFORE_PUBLISH = TZ.localize(datetime(2026, 11, 20, 10, 0))
REAL_DATA_FILE = Path("data/nordpool_last_good.json")


def _frozen_datetime(frozen: datetime) -> type[datetime]:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen

    return FrozenDatetime


def _day_values(day: date, value: float = 1000.0) -> list[dict]:
    midnight = TZ.localize(datetime(day.year, day.month, day.day))
    return [
        {
            "start": midnight + timedelta(hours=h),
            "end": midnight + timedelta(hours=h + 1),
            "value": value + h,
        }
        for h in range(24)
    ]


class _Feed:
    """Controllable Nordpool client: per-day values or an exception."""

    def __init__(self) -> None:
        self.days: dict[date, list[dict] | Exception] = {}
        self.calls: list[date] = []

    def fetch(self, end_date, areas, resolution):
        self.calls.append(end_date)
        result = self.days.get(end_date, [])
        if isinstance(result, Exception):
            raise result
        return {"areas": {areas[0]: {"values": result}}}


@pytest.fixture
def feed():
    return _Feed()


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.dump(
            {
                "timezone": "Europe/Stockholm",
                "nordpool": {"price_area": "SE3", "currency": "SEK", "resolution_minutes": 60},
            }
        )
    )
    return str(path)


@pytest.fixture(autouse=True)
def clean_price_cache():
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    yield
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)


async def _get(feed: _Feed, config_path: str, now: datetime) -> list[dict]:
    client = MagicMock()
    client.fetch.side_effect = feed.fetch
    with (
        patch("backend.core.prices.Prices", return_value=client),
        patch("backend.core.prices.datetime", _frozen_datetime(now)),
    ):
        return await prices.get_nordpool_data(config_path)


def _stored() -> dict:
    return json.loads(prices._LAST_GOOD_PATH.read_text(encoding="utf-8"))


# --- test isolation -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_keeps_real_data_dir_untouched(feed, config_path):
    existed_before = REAL_DATA_FILE.exists()
    feed.days[TODAY] = _day_values(TODAY)

    result = await _get(feed, config_path, BEFORE_PUBLISH)

    assert len(result) == 24
    assert prices._LAST_GOOD_PATH != REAL_DATA_FILE
    assert prices._LAST_GOOD_PATH.exists()
    assert REAL_DATA_FILE.exists() == existed_before


# --- partial results ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tomorrow_raises_after_13_keeps_today(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = TimeoutError("simulated")

    result = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == [TODAY, TOMORROW]
    assert len(result) == 24
    assert all(s["start_time"].date() == TODAY for s in result)


@pytest.mark.asyncio
async def test_tomorrow_empty_after_13_keeps_today(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = []

    result = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == [TODAY, TOMORROW]
    assert len(result) == 24
    assert all(s["start_time"].date() == TODAY for s in result)


@pytest.mark.asyncio
async def test_complete_fetch_returns_both_days(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = _day_values(TOMORROW)

    result = await _get(feed, config_path, AFTER_PUBLISH)

    assert len(result) == 48


@pytest.mark.asyncio
async def test_today_failure_skips_tomorrow_fetch(feed, config_path):
    feed.days[TODAY] = TimeoutError("simulated")
    feed.days[TOMORROW] = _day_values(TOMORROW)

    result = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == [TODAY]
    assert result == []


# --- last-good store: writing -------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_fetch_after_13_writes_store(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = _day_values(TOMORROW)

    await _get(feed, config_path, AFTER_PUBLISH)

    payload = _stored()
    assert payload["price_area"] == "SE3"
    assert payload["currency"] == "SEK"
    assert payload["resolution_minutes"] == 60
    assert payload["saved_at"] == AFTER_PUBLISH.isoformat()
    assert len(payload["entries"]) == 48
    first = payload["entries"][0]
    assert datetime.fromisoformat(first["start"]) == _day_values(TODAY)[0]["start"]
    assert first["value"] == 1000.0


@pytest.mark.asyncio
async def test_complete_fetch_before_13_writes_store(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)

    await _get(feed, config_path, BEFORE_PUBLISH)

    assert len(_stored()["entries"]) == 24


@pytest.mark.asyncio
async def test_tomorrow_empty_does_not_overwrite_store(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = _day_values(TOMORROW)
    await _get(feed, config_path, AFTER_PUBLISH)
    before = prices._LAST_GOOD_PATH.read_bytes()
    memory_before = prices._last_good

    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    feed.days[TODAY] = _day_values(TODAY, value=5000.0)
    feed.days[TOMORROW] = []
    await _get(feed, config_path, AFTER_PUBLISH)

    assert prices._LAST_GOOD_PATH.read_bytes() == before
    assert prices._last_good is memory_before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("simulated"), RuntimeError("boom"), []])
async def test_total_failure_does_not_overwrite_store(feed, config_path, failure):
    feed.days[TODAY] = _day_values(TODAY)
    await _get(feed, config_path, BEFORE_PUBLISH)
    before = prices._LAST_GOOD_PATH.read_bytes()

    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    feed.days[TODAY] = failure
    await _get(feed, config_path, BEFORE_PUBLISH)

    assert prices._LAST_GOOD_PATH.read_bytes() == before


@pytest.mark.asyncio
async def test_total_failure_without_store_creates_no_file(feed, config_path):
    feed.days[TODAY] = RuntimeError("boom")

    await _get(feed, config_path, AFTER_PUBLISH)

    assert not prices._LAST_GOOD_PATH.exists()


@pytest.mark.asyncio
async def test_forecast_fallback_entries_are_not_stored(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    forecast = [
        {"slot_start": TZ.localize(datetime(2026, 11, 21, h)), "spot_p50": 1.0} for h in range(24)
    ]
    with patch(
        "ml.price_forecast.get_d1_price_forecast_fallback", AsyncMock(return_value=forecast)
    ):
        result = await _get(feed, config_path, BEFORE_PUBLISH)

    assert len(result) == 48
    assert {s["price_source"] for s in result} == {"nordpool", "forecast"}
    stored_days = {datetime.fromisoformat(e["start"]).date() for e in _stored()["entries"]}
    assert stored_days == {TODAY}


@pytest.mark.asyncio
async def test_save_drops_entries_ended_over_a_day_ago():
    old = _day_values(TODAY - timedelta(days=3))
    recent = _day_values(TODAY - timedelta(days=1))[-1:]
    current = _day_values(TODAY)

    await prices._save_last_good(old + recent + current, "SE3", "SEK", 60, AFTER_PUBLISH)

    starts = [datetime.fromisoformat(e["start"]) for e in _stored()["entries"]]
    assert starts == [recent[0]["start"]] + [e["start"] for e in current]


@pytest.mark.asyncio
async def test_save_failure_is_logged_and_memory_still_updated(caplog):
    with patch("backend.core.prices.write_json_atomic", side_effect=OSError("disk full")):
        await prices._save_last_good(_day_values(TODAY), "SE3", "SEK", 60, AFTER_PUBLISH)

    assert "Could not store Nordpool prices" in caplog.text
    stored = prices._load_last_good("SE3", "SEK", 60)
    assert stored is not None
    assert len(stored["entries"]) == 24


# --- last-good store: loading -------------------------------------------------------------


def _write_store(**overrides) -> None:
    payload = {
        "price_area": "SE3",
        "currency": "SEK",
        "resolution_minutes": 60,
        "saved_at": AFTER_PUBLISH.isoformat(),
        "entries": [
            {"start": e["start"].isoformat(), "end": e["end"].isoformat(), "value": e["value"]}
            for e in _day_values(TODAY)
        ],
    }
    payload.update(overrides)
    prices._LAST_GOOD_PATH.write_text(json.dumps(payload), encoding="utf-8")


def test_load_reads_file_after_restart():
    _write_store()

    stored = prices._load_last_good("SE3", "SEK", 60)

    assert stored is not None
    assert len(stored["entries"]) == 24
    assert stored["entries"][0]["start"] == _day_values(TODAY)[0]["start"]
    assert stored["entries"][0]["end"].tzinfo is not None


def test_load_is_lazy_and_cached():
    _write_store()
    assert prices._last_good is None

    first = prices._load_last_good("SE3", "SEK", 60)
    prices._LAST_GOOD_PATH.unlink()

    assert prices._load_last_good("SE3", "SEK", 60) is first


def test_load_missing_file_returns_none_without_warning(caplog):
    assert prices._load_last_good("SE3", "SEK", 60) is None
    assert caplog.text == ""


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"price_area": "SE3"}),
        json.dumps(
            {
                "price_area": "SE3",
                "currency": "SEK",
                "resolution_minutes": 60,
                "saved_at": "x",
                "entries": [
                    {"start": "2026-11-20T00:00:00", "end": "2026-11-20T01:00:00", "value": 1}
                ],
            }
        ),
    ],
)
def test_load_corrupt_file_is_ignored_and_warned_once(content, caplog):
    prices._LAST_GOOD_PATH.write_text(content, encoding="utf-8")

    assert prices._load_last_good("SE3", "SEK", 60) is None
    assert prices._load_last_good("SE3", "SEK", 60) is None

    warnings = [r for r in caplog.records if "Ignoring stored Nordpool prices" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"price_area": "SE4"}, {"currency": "EUR"}, {"resolution_minutes": 15}],
)
def test_load_mismatched_settings_is_ignored(overrides):
    _write_store(**overrides)

    assert prices._load_last_good("SE3", "SEK", 60) is None


# --- last-good fallback -------------------------------------------------------------------

LATE = TZ.localize(datetime(2026, 11, 20, 18, 30))


async def _seed_store(feed: _Feed, config_path: str) -> None:
    """Complete fetch after publication: stores today and tomorrow, then clears the cache."""
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = _day_values(TOMORROW)
    await _get(feed, config_path, AFTER_PUBLISH)
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    feed.calls.clear()


@pytest.mark.asyncio
async def test_total_failure_returns_stored_future_slots_only(feed, config_path):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = TimeoutError("simulated")

    result = await _get(feed, config_path, LATE)

    # Slot 18:00-19:00 is running; everything before it has ended.
    assert result[0]["start_time"] == TZ.localize(datetime(2026, 11, 20, 18))
    assert len(result) == 6 + 24
    assert all(s["end_time"] > LATE for s in result)
    assert {s["price_source"] for s in result} == {"nordpool"}


@pytest.mark.asyncio
async def test_tomorrow_failure_fills_tomorrow_from_store(feed, config_path):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = _day_values(TODAY, value=2000.0)
    feed.days[TOMORROW] = TimeoutError("simulated")

    result = await _get(feed, config_path, AFTER_PUBLISH)

    assert len(result) == 48
    # Fresh today wins over stored today; tomorrow comes from the store.
    assert result[0]["export_price_sek_kwh"] == pytest.approx(2.0)
    assert result[24]["export_price_sek_kwh"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_restart_during_outage_reads_store_from_file(feed, config_path):
    await _seed_store(feed, config_path)
    prices.reset_price_fetch_state()
    feed.days[TODAY] = RuntimeError("boom")

    result = await _get(feed, config_path, LATE)

    assert len(result) == 30


@pytest.mark.asyncio
async def test_total_failure_nothing_stored_returns_empty(feed, config_path):
    feed.days[TODAY] = RuntimeError("boom")

    assert await _get(feed, config_path, AFTER_PUBLISH) == []


@pytest.mark.asyncio
async def test_total_failure_all_stored_slots_ended_returns_empty(feed, config_path):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = RuntimeError("boom")
    after_everything = TZ.localize(datetime(2026, 11, 22, 8, 0))

    assert await _get(feed, config_path, after_everything) == []


@pytest.mark.asyncio
async def test_pricing_change_applies_to_fallback(feed, config_path):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = RuntimeError("boom")
    base = await _get(feed, config_path, LATE)
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    prices.reset_price_fetch_state()
    cfg = yaml.safe_load(Path(config_path).read_text())
    cfg["pricing"] = {"supplier_markup_sek_kwh": 1.0, "vat_percent": 0.0}
    Path(config_path).write_text(yaml.dump(cfg))

    changed = await _get(feed, config_path, LATE)

    assert changed[0]["export_price_sek_kwh"] == base[0]["export_price_sek_kwh"]
    assert changed[0]["import_price_sek_kwh"] != base[0]["import_price_sek_kwh"]
    expected, _ = prices.calculate_import_export_prices(
        1018.0, {"timezone": "Europe/Stockholm", **{"pricing": cfg["pricing"]}}
    )
    assert changed[0]["import_price_sek_kwh"] == pytest.approx(expected)


@pytest.mark.asyncio
async def test_mismatched_store_not_used_on_failure(feed, config_path):
    await _seed_store(feed, config_path)
    cfg = yaml.safe_load(Path(config_path).read_text())
    cfg["nordpool"]["price_area"] = "SE4"
    Path(config_path).write_text(yaml.dump(cfg))
    feed.days[TODAY] = RuntimeError("boom")

    assert await _get(feed, config_path, LATE) == []


@pytest.mark.asyncio
async def test_fallback_logs_warning_first_then_info_and_resets(feed, config_path, caplog):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = RuntimeError("boom")
    caplog.set_level("INFO", logger="darkstar.core.prices")

    await _get(feed, config_path, LATE)
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    await _get(feed, config_path, LATE)

    records = [r for r in caplog.records if "using stored prices" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING", "INFO"]
    assert "30 slots" in records[0].getMessage()

    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = _day_values(TOMORROW)
    await _get(feed, config_path, AFTER_PUBLISH)
    cache_sync.invalidate(prices.NORDPOOL_CACHE_KEY)
    feed.days[TODAY] = RuntimeError("boom")
    caplog.clear()
    await _get(feed, config_path, LATE)

    again = [r for r in caplog.records if "using stored prices" in r.getMessage()]
    assert [r.levelname for r in again] == ["WARNING"]


# --- negative cache -----------------------------------------------------------------------


class _Clock:
    """Controls time.monotonic (retry window) and time.time (cache TTL) as seen by the code."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __enter__(self):
        self._patches = [
            patch("backend.core.prices.time.monotonic", side_effect=lambda: self.now),
            patch("backend.core.cache.time.time", side_effect=lambda: self.now),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


@pytest.mark.asyncio
async def test_tomorrow_failure_not_refetched_within_window(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)
    feed.days[TOMORROW] = TimeoutError("simulated")

    with _Clock() as clock:
        first = await _get(feed, config_path, AFTER_PUBLISH)
        feed.calls.clear()
        clock.advance(prices.FETCH_RETRY_SECONDS - 1)
        second = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == []
    assert second == first
    assert len(second) == 24


@pytest.mark.asyncio
async def test_tomorrow_empty_not_refetched_within_window(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)

    with _Clock() as clock:
        await _get(feed, config_path, AFTER_PUBLISH)
        feed.calls.clear()
        clock.advance(60)
        result = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == []
    assert len(result) == 24


@pytest.mark.asyncio
async def test_total_failure_with_stored_slots_not_refetched_and_filters_ended(feed, config_path):
    await _seed_store(feed, config_path)
    feed.days[TODAY] = TimeoutError("simulated")

    with _Clock() as clock:
        first = await _get(feed, config_path, LATE)
        feed.calls.clear()
        clock.advance(120)
        later = LATE + timedelta(hours=1)
        second = await _get(feed, config_path, later)

    assert feed.calls == []
    assert len(first) == 30
    # Slot 18:00-19:00 ended at 19:00; frozen clock for the repeat call is 19:30.
    assert len(second) == 29
    assert second == first[1:]
    assert all(s["end_time"] > later for s in second)


@pytest.mark.asyncio
async def test_total_failure_without_store_not_refetched(feed, config_path):
    feed.days[TODAY] = RuntimeError("boom")

    with _Clock() as clock:
        first = await _get(feed, config_path, AFTER_PUBLISH)
        feed.calls.clear()
        clock.advance(299)
        second = await _get(feed, config_path, AFTER_PUBLISH)

    assert first == []
    assert second == []
    assert feed.calls == []


@pytest.mark.asyncio
async def test_retry_after_window_fetches_again_and_recovers(feed, config_path):
    feed.days[TODAY] = RuntimeError("boom")

    with _Clock() as clock:
        assert await _get(feed, config_path, AFTER_PUBLISH) == []
        feed.calls.clear()
        feed.days[TODAY] = _day_values(TODAY)
        feed.days[TOMORROW] = _day_values(TOMORROW)
        clock.advance(prices.FETCH_RETRY_SECONDS + 1)

        recovered = await _get(feed, config_path, AFTER_PUBLISH)
        assert feed.calls == [TODAY, TOMORROW]
        assert len(recovered) == 48

        # Cached normally again (long TTL, no retry window).
        feed.calls.clear()
        clock.advance(1800)
        assert await _get(feed, config_path, AFTER_PUBLISH) == recovered
        assert feed.calls == []


@pytest.mark.asyncio
async def test_tomorrow_published_after_window_is_picked_up(feed, config_path):
    feed.days[TODAY] = _day_values(TODAY)

    with _Clock() as clock:
        assert len(await _get(feed, config_path, AFTER_PUBLISH)) == 24
        feed.days[TOMORROW] = _day_values(TOMORROW)
        clock.advance(prices.FETCH_RETRY_SECONDS + 1)
        feed.calls.clear()

        result = await _get(feed, config_path, AFTER_PUBLISH)

    assert feed.calls == [TODAY, TOMORROW]
    assert len(result) == 48
