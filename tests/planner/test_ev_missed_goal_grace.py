"""Missed-goal grace window (ev-goal-shortfall-recovery 3.2 / 3.5).

Spec: ``ev-missed-goal-recovery`` — "Missed goal stays active during a grace
window".
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from backend.core.ev_goal import resolve_previous_ready_by
from planner.pipeline import resolve_ev_effective_deadline

TZ = pytz_timezone("Europe/Stockholm")


def _at(y, m, d, hh, mm):
    return TZ.localize(datetime(y, m, d, hh, mm))


# 2026-09-24 is a Thursday.
NOW = _at(2026, 9, 24, 10, 31)


def _goal(**overrides):
    goal = {
        "id": "goe",
        "target_soc_percent": 55,
        "ready_by": "10:30",
        "repeat": "daily",
        "missed_goal_grace_hours": 4,
    }
    goal.update(overrides)
    return goal


# ---------------------------------------------------------------------------
# resolve_previous_ready_by
# ---------------------------------------------------------------------------
class TestResolvePreviousReadyBy:
    def test_daily_today(self):
        assert resolve_previous_ready_by(_goal(), NOW, TZ) == _at(2026, 9, 24, 10, 30)

    def test_daily_before_todays_deadline_is_yesterday(self):
        now = _at(2026, 9, 24, 9, 0)
        assert resolve_previous_ready_by(_goal(), now, TZ) == _at(2026, 9, 23, 10, 30)

    def test_exactly_at_deadline_counts_as_passed(self):
        now = _at(2026, 9, 24, 10, 30)
        assert resolve_previous_ready_by(_goal(), now, TZ) == now

    def test_weekdays_on_monday_morning_is_friday(self):
        now = _at(2026, 9, 28, 9, 0)  # Monday
        got = resolve_previous_ready_by(_goal(repeat="weekdays"), now, TZ)
        assert got == _at(2026, 9, 25, 10, 30)  # Friday

    def test_weekends_on_thursday_is_last_sunday(self):
        got = resolve_previous_ready_by(_goal(repeat="weekends"), NOW, TZ)
        assert got == _at(2026, 9, 20, 10, 30)

    def test_every_n_days(self):
        goal = _goal(repeat="every_n_days", n_days=3, last_updated="2026-09-18T08:00:00+02:00")
        # Occurrences: 09-21, 09-24, 09-27 ...
        assert resolve_previous_ready_by(goal, NOW, TZ) == _at(2026, 9, 24, 10, 30)
        assert resolve_previous_ready_by(goal, _at(2026, 9, 23, 12, 0), TZ) == _at(
            2026, 9, 21, 10, 30
        )

    def test_every_n_days_anchor_day_is_not_an_occurrence(self):
        goal = _goal(repeat="every_n_days", n_days=3, last_updated="2026-09-24T08:00:00+02:00")
        assert resolve_previous_ready_by(goal, NOW, TZ) is None

    def test_none_passed(self):
        goal = _goal(repeat="none", ready_by_date="2026-09-24")
        assert resolve_previous_ready_by(goal, NOW, TZ) == _at(2026, 9, 24, 10, 30)

    def test_none_in_future(self):
        goal = _goal(repeat="none", ready_by_date="2026-09-25")
        assert resolve_previous_ready_by(goal, NOW, TZ) is None

    def test_missing_ready_by(self):
        assert resolve_previous_ready_by(_goal(ready_by=None), NOW, TZ) is None


# ---------------------------------------------------------------------------
# resolve_ev_effective_deadline
# ---------------------------------------------------------------------------
LIVE_BELOW = {"soc_percent": 53.0, "plugged_in": True}


def test_goal_missed_plugged_in_gets_grace_deadline():
    deadline, in_grace = resolve_ev_effective_deadline(_goal(), LIVE_BELOW, NOW, TZ)
    assert in_grace is True
    assert deadline == _at(2026, 9, 24, 14, 30)


def test_one_off_goal_missed_gets_grace_deadline():
    goal = _goal(repeat="none", ready_by_date="2026-09-24")
    deadline, in_grace = resolve_ev_effective_deadline(goal, LIVE_BELOW, NOW, TZ)
    assert in_grace is True
    assert deadline == _at(2026, 9, 24, 14, 30)


def test_grace_window_expired_resolves_next_ready_by():
    now = _at(2026, 9, 24, 14, 30)
    deadline, in_grace = resolve_ev_effective_deadline(_goal(), LIVE_BELOW, now, TZ)
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)


def test_grace_expired_one_off_resolves_none():
    goal = _goal(repeat="none", ready_by_date="2026-09-24")
    now = _at(2026, 9, 24, 15, 0)
    assert resolve_ev_effective_deadline(goal, LIVE_BELOW, now, TZ) == (None, False)


def test_unplugged_after_missed_deadline_no_grace():
    state = {"soc_percent": 53.0, "plugged_in": False}
    deadline, in_grace = resolve_ev_effective_deadline(_goal(), state, NOW, TZ)
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)


def test_target_reached_no_grace():
    state = {"soc_percent": 55.0, "plugged_in": True}
    deadline, in_grace = resolve_ev_effective_deadline(_goal(), state, NOW, TZ)
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)


def test_no_live_soc_no_grace():
    state = {"soc_percent": None, "plugged_in": True}
    _, in_grace = resolve_ev_effective_deadline(_goal(), state, NOW, TZ)
    assert in_grace is False


@pytest.mark.parametrize("grace", [0, 0.0])
def test_grace_zero_is_previous_behaviour(grace):
    deadline, in_grace = resolve_ev_effective_deadline(
        _goal(missed_goal_grace_hours=grace), LIVE_BELOW, NOW, TZ
    )
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)


def test_grace_defaults_to_4_hours_when_unset():
    goal = _goal()
    del goal["missed_goal_grace_hours"]
    deadline, in_grace = resolve_ev_effective_deadline(goal, LIVE_BELOW, NOW, TZ)
    assert in_grace is True
    assert deadline == _at(2026, 9, 24, 14, 30)


def test_grace_capped_by_next_ready_by():
    """Twice-close goals: a 20 h grace would run past tomorrow's 10:30."""
    deadline, in_grace = resolve_ev_effective_deadline(
        _goal(missed_goal_grace_hours=30), LIVE_BELOW, NOW, TZ
    )
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)


def test_goal_set_after_its_deadline_is_not_missed():
    goal = _goal(last_updated=(NOW - timedelta(seconds=30)).isoformat())
    deadline, in_grace = resolve_ev_effective_deadline(goal, LIVE_BELOW, NOW, TZ)
    assert in_grace is False
    assert deadline == _at(2026, 9, 25, 10, 30)
