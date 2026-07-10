from __future__ import annotations

from datetime import datetime, timedelta

import pytz

from backend.core.ev_goal import resolve_next_ready_by

TZ = pytz.timezone("Europe/Stockholm")


def _now(y=2026, m=6, d=10, hh=12, mm=0):
    return TZ.localize(datetime(y, m, d, hh, mm))


def test_daily_before_ready_by_is_today():
    now = _now(hh=6)
    goal = {"ready_by": "07:00", "repeat": "daily"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline.date() == now.date()
    assert (deadline.hour, deadline.minute) == (7, 0)


def test_daily_after_ready_by_rolls_to_tomorrow():
    now = _now(hh=8)
    goal = {"ready_by": "07:00", "repeat": "daily"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline.date() == (now.date() + timedelta(days=1))


def test_null_repeat_treated_as_daily():
    now = _now(hh=6)
    goal = {"ready_by": "07:00", "repeat": None}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline.date() == now.date()
    assert (deadline.hour, deadline.minute) == (7, 0)


def test_missing_repeat_key_treated_as_daily():
    now = _now(hh=6)
    goal = {"ready_by": "07:00"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline is not None
    assert (deadline.hour, deadline.minute) == (7, 0)


def test_weekdays_skips_weekend():
    # 2026-06-13 is a Saturday.
    now = TZ.localize(datetime(2026, 6, 12, 8, 0))  # Friday, after 07:00
    goal = {"ready_by": "07:00", "repeat": "weekdays"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline.weekday() < 5
    assert deadline.date() == datetime(2026, 6, 15).date()  # next Monday


def test_weekends_skips_weekday():
    # 2026-06-10 is a Wednesday.
    now = _now(hh=8)
    goal = {"ready_by": "07:00", "repeat": "weekends"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline.weekday() >= 5


def test_none_repeat_with_future_date():
    now = _now()
    goal = {"ready_by": "09:00", "repeat": "none", "ready_by_date": "2026-06-12"}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline is not None
    assert deadline.date() == datetime(2026, 6, 12).date()


def test_none_repeat_with_past_date_returns_none():
    now = _now()
    goal = {"ready_by": "09:00", "repeat": "none", "ready_by_date": "2020-01-01"}
    assert resolve_next_ready_by(goal, now, TZ) is None


def test_none_repeat_missing_date_returns_none():
    now = _now()
    goal = {"ready_by": "09:00", "repeat": "none"}
    assert resolve_next_ready_by(goal, now, TZ) is None


def test_every_n_days_anchored_to_last_updated():
    now = _now(d=10)
    goal = {
        "ready_by": "07:00",
        "repeat": "every_n_days",
        "n_days": 3,
        "last_updated": TZ.localize(datetime(2026, 6, 10, 8, 0)).isoformat(),
    }
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline is not None
    assert deadline.date() == datetime(2026, 6, 13).date()


def test_every_n_days_defaults_n_to_1():
    now = _now(hh=6)
    goal = {
        "ready_by": "07:00",
        "repeat": "every_n_days",
        "last_updated": now.isoformat(),
    }
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline is not None
    assert deadline.date() == (now.date() + timedelta(days=1))


def test_every_n_days_no_anchor_falls_back_to_now():
    now = _now(hh=6)
    goal = {"ready_by": "07:00", "repeat": "every_n_days", "n_days": 2}
    deadline = resolve_next_ready_by(goal, now, TZ)
    assert deadline is not None
    assert deadline > now


def test_missing_ready_by_returns_none():
    now = _now()
    assert resolve_next_ready_by({"repeat": "daily"}, now, TZ) is None
    assert resolve_next_ready_by({"ready_by": "", "repeat": "daily"}, now, TZ) is None
