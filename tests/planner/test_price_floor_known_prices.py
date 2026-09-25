"""Known-price precedence in planner price-floor inputs (ev-quota-known-prices)."""

import sqlite3
from datetime import datetime, timedelta

import pytest
import pytz

from planner.pipeline import _fetch_price_floor_inputs_sync
from planner.strategy.s_index import calculate_price_floor_addon

TZ_NAME = "Europe/Stockholm"
TZ = pytz.timezone(TZ_NAME)
QUARTER = timedelta(minutes=15)


def _local(*args: int) -> datetime:
    return TZ.localize(datetime(*args))


def _quarters(start: datetime, end: datetime) -> list[datetime]:
    """Quarter-hour slot starts in [start, end), stepped in UTC to stay DST-safe."""
    out = []
    cur = start.astimezone(pytz.utc)
    end_utc = end.astimezone(pytz.utc)
    while cur < end_utc:
        out.append(cur.astimezone(TZ))
        cur += QUARTER
    return out


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "learning.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE price_forecasts (slot_start TEXT, issue_timestamp TEXT, spot_p50 REAL)"
    )
    conn.execute("CREATE TABLE slot_observations (slot_start TEXT, export_price_sek_kwh REAL)")
    conn.commit()
    conn.close()
    return str(path)


def _insert_forecasts(db_path: str, rows: list[tuple[datetime, float]], issue: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO price_forecasts (slot_start, issue_timestamp, spot_p50) VALUES (?, ?, ?)",
        [(dt.isoformat(), issue, spot) for dt, spot in rows],
    )
    conn.commit()
    conn.close()


def _day(y: int, m: int, d: int) -> tuple[datetime, datetime]:
    start = _local(y, m, d)
    return start, TZ.localize(datetime(y, m, d) + timedelta(days=1))


def test_regression_2026_09_24_published_prices_win_over_stale_forecast(db_path):
    """Thu 23:00: published ≈2.0 SEK spot wins over a stale 0.2 SEK forecast per slot."""
    now = _local(2026, 9, 24, 23, 0)
    thu_slots = _quarters(now, _day(2026, 9, 24)[1])
    stale = [0.24, 0.24, 0.18, 0.18]
    published = [2.07, 2.07, 2.00, 1.97]

    rows = list(zip(thu_slots, stale, strict=True))
    for (y, m, d), spot in [((2026, 9, 25), 1.2), ((2026, 9, 26), 0.6), ((2026, 9, 27), 0.8)]:
        rows += [(dt, spot) for dt in _quarters(*_day(y, m, d))]
    _insert_forecasts(db_path, rows, "2026-09-23T06:00:00+02:00")

    known = dict(zip(thu_slots, published, strict=True))
    known |= dict.fromkeys(_quarters(*_day(2026, 9, 25)), 1.5)

    old_spots, _, _ = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, None, now=now)
    assert old_spots[0] == pytest.approx(sum(stale) / 4)

    spots, _, sources = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, known, now=now)
    assert spots[0] == pytest.approx(sum(published) / 4)
    assert spots[1] == pytest.approx(1.5)
    assert sources[0] == (4, 0)
    assert sources[1] == (96, 0)
    assert sources[2] == (0, 96)


def test_published_d1_used_after_auction(db_path):
    now = _local(2026, 9, 24, 14, 0)
    d1 = _quarters(*_day(2026, 9, 25))
    _insert_forecasts(db_path, [(dt, 1.2) for dt in d1], "2026-09-24T06:00:00+02:00")

    spots, _, sources = _fetch_price_floor_inputs_sync(
        db_path, TZ_NAME, dict.fromkeys(d1, 2.0), now=now
    )

    assert spots[1] == pytest.approx(2.0)
    assert sources[1] == (96, 0)


def test_known_slots_without_forecast_rows_are_included(db_path):
    """Published slots count even when no forecast exists (today is never forecast D+0)."""
    now = _local(2026, 9, 24, 22, 0)
    today_slots = _quarters(now, _day(2026, 9, 24)[1])

    spots, _, sources = _fetch_price_floor_inputs_sync(
        db_path, TZ_NAME, dict.fromkeys(today_slots, 1.0), now=now
    )

    assert spots == {0: pytest.approx(1.0)}
    assert sources == {0: (8, 0)}


def test_past_known_slots_today_are_excluded(db_path):
    now = _local(2026, 9, 24, 12, 0)
    known = dict.fromkeys(_quarters(_local(2026, 9, 24), now), 0.1)
    known |= dict.fromkeys(_quarters(now, _day(2026, 9, 24)[1]), 2.0)

    spots, _, _ = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, known, now=now)

    assert spots[0] == pytest.approx(2.0)


def test_dst_boundary_keys_merge_without_duplicates(db_path):
    """2026-10-25 has 100 quarter-hours; both 02:xx hours must merge 1:1."""
    now = _local(2026, 10, 24, 12, 0)
    d1 = _quarters(*_day(2026, 10, 25))
    assert len(d1) == 100
    _insert_forecasts(db_path, [(dt, 0.5) for dt in d1], "2026-10-24T06:00:00+02:00")

    # Nordpool-side keys built independently, as pytz-normalized local datetimes.
    known = {TZ.normalize(dt.astimezone(pytz.utc).astimezone(TZ)): 1.0 for dt in d1}

    spots, _, sources = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, known, now=now)

    assert sources[1] == (100, 0)
    assert spots[1] == pytest.approx(1.0)


def test_forecast_only_when_known_map_empty(db_path):
    now = _local(2026, 9, 24, 14, 0)
    d1 = _quarters(*_day(2026, 9, 25))
    _insert_forecasts(db_path, [(dt, 0.7) for dt in d1], "2026-09-24T06:00:00+02:00")

    spots, _, sources = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, {}, now=now)

    assert spots[1] == pytest.approx(0.7)
    assert sources[1] == (0, 96)


def test_safety_floor_addon_uses_known_price_day(db_path):
    now = _local(2026, 9, 24, 14, 0)
    d1 = _quarters(*_day(2026, 9, 25))
    d2 = _quarters(*_day(2026, 9, 26))
    _insert_forecasts(db_path, [(dt, 0.5) for dt in d1 + d2], "2026-09-24T06:00:00+02:00")

    spots, _, _ = _fetch_price_floor_inputs_sync(db_path, TZ_NAME, dict.fromkeys(d1, 3.0), now=now)
    addon, debug = calculate_price_floor_addon(spots, 1.0, 10.0, 3)

    assert debug["driving_day_offset"] == 1
    assert debug["peak_upcoming_spot_sek"] == pytest.approx(3.0)
    assert addon > 0
