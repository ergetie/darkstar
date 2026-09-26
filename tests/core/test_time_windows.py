"""Tests for the reusable local-time window matcher and Swedish holidays."""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
import pytz

from backend.core.time_windows import matches, parse_window, swedish_public_holidays

VECTORS = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "time_window_vectors.json").read_text()
)


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_shared_vectors(vector):
    window = parse_window(vector["window"])
    local_dt = datetime.fromisoformat(vector["local_datetime"])
    assert matches(window, local_dt, vector["holidays_as_weekend"]) is vector["expected"]


@pytest.mark.parametrize(
    "raw",
    [
        {"hours": {"start": 8, "end": 8}},
        {"hours": {"start": 24, "end": 6}},
        {"hours": {"start": 6, "end": 0}},
        {"hours": {"start": 6, "end": 25}},
        {"hours": {"start": 6}},
        {"hours": {"start": "6", "end": 22}},
        {"hours": [6, 22]},
        {"months": [0]},
        {"months": [13]},
        {"months": 11},
        {"weekdays": [7]},
        {"weekdays": [-1]},
        {"weekdays": [True]},
        "not-a-dict",
    ],
)
def test_parse_window_rejects_invalid(raw):
    with pytest.raises(ValueError):
        parse_window(raw)


def test_wrap_around_range():
    window = parse_window({"hours": {"start": 22, "end": 6}})
    assert matches(window, datetime(2026, 1, 1, 22, 0))
    assert matches(window, datetime(2026, 1, 2, 5, 45))
    assert not matches(window, datetime(2026, 1, 2, 6, 0))


def test_omitted_fields_match_every_hour():
    window = parse_window({})
    for hour in range(24):
        assert matches(window, datetime(2026, 5, 17, hour, 30))


def test_holidays_2027_spec_dates():
    holidays = swedish_public_holidays(2027)
    assert date(2027, 3, 26) in holidays  # Långfredagen
    assert date(2027, 3, 29) in holidays  # Annandag påsk
    assert date(2027, 6, 26) in holidays  # Midsommardagen
    assert date(2027, 6, 25) in holidays  # Midsommarafton


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (
            2025,
            {
                date(2025, 4, 18),  # Långfredagen
                date(2025, 4, 20),  # Påskdagen
                date(2025, 4, 21),  # Annandag påsk
                date(2025, 5, 29),  # Kristi himmelsfärd
                date(2025, 6, 8),  # Pingstdagen
                date(2025, 6, 20),  # Midsommarafton
                date(2025, 6, 21),  # Midsommardagen
                date(2025, 11, 1),  # Alla helgons dag
            },
        ),
        (
            2026,
            {
                date(2026, 4, 3),
                date(2026, 4, 5),
                date(2026, 4, 6),
                date(2026, 5, 14),
                date(2026, 5, 24),
                date(2026, 6, 19),
                date(2026, 6, 20),
                date(2026, 10, 31),
            },
        ),
    ],
)
def test_moving_holidays(year, expected):
    holidays = swedish_public_holidays(year)
    assert expected <= holidays
    fixed = {(1, 1), (1, 6), (5, 1), (6, 6), (12, 24), (12, 25), (12, 26), (12, 31)}
    assert {date(year, m, d) for m, d in fixed} <= holidays
    assert len(holidays) == 16


def test_dst_days_use_wall_clock_hour():
    tz = pytz.timezone("Europe/Stockholm")
    window = parse_window({"hours": {"start": 3, "end": 4}})
    # Spring forward: 02:00 -> 03:00; slot at 03:00 local exists and matches.
    spring = tz.localize(datetime(2026, 3, 29, 3, 0))
    assert matches(window, spring)
    # Fall back: 02:xx occurs twice; both occurrences match a 2-3 window.
    fall_window = parse_window({"hours": {"start": 2, "end": 3}})
    first = tz.localize(datetime(2026, 10, 25, 2, 30), is_dst=True)
    second = tz.localize(datetime(2026, 10, 25, 2, 30), is_dst=False)
    assert matches(fall_window, first)
    assert matches(fall_window, second)
