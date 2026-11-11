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
        "missed_goal_tolerance_percent": 0,
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


# ---------------------------------------------------------------------------
# Plug continuity, SoC-drop fallback, tolerance (fix-ev-missed-goal-grace-plug-continuity)
# ---------------------------------------------------------------------------
MISSED = _at(2026, 9, 24, 10, 30)
NEXT_DAY = _at(2026, 9, 25, 10, 30)


def _state(**overrides):
    state = {"soc_percent": 53.0, "plugged_in": True}
    state.update(overrides)
    return state


def _resolve(goal=None, now=NOW, **state):
    return resolve_ev_effective_deadline(goal or _goal(), _state(**state), now, TZ)


def test_session_started_before_deadline_gets_grace():
    deadline, in_grace = _resolve(plug_session_start=MISSED - timedelta(hours=3))
    assert in_grace is True
    assert deadline == _at(2026, 9, 24, 14, 30)


def test_session_started_exactly_at_deadline_counts_as_continuous():
    assert _resolve(plug_session_start=MISSED)[1] is True


def test_replug_after_deadline_gets_no_grace():
    deadline, in_grace = _resolve(plug_session_start=MISSED + timedelta(seconds=1))
    assert in_grace is False
    assert deadline == NEXT_DAY


def test_replug_with_soc_drop_gets_no_grace_even_if_deadline_soc_supplied():
    """A replug (start after the deadline) gets no grace whatever the deadline SoC."""
    assert _resolve(plug_session_start=NOW, soc_at_missed_deadline=53.0)[1] is False


def test_restored_session_with_soc_drop_gets_no_grace():
    """Car left and returned while Darkstar was down: restored session looks continuous."""
    assert _resolve(plug_session_start=MISSED - timedelta(hours=2), soc_at_missed_deadline=60.0)[
        1
    ] is False


def test_restored_session_without_soc_drop_gets_grace():
    assert _resolve(plug_session_start=MISSED - timedelta(hours=2), soc_at_missed_deadline=53.5)[
        1
    ] is True


def test_restored_session_without_deadline_soc_is_legacy():
    assert _resolve(plug_session_start=MISSED - timedelta(hours=2))[1] is True


def test_unknown_history_soc_dropped_gets_no_grace():
    """Deadline SoC 60%, now 53%: the car was driven."""
    assert _resolve(soc_at_missed_deadline=60.0)[1] is False


@pytest.mark.parametrize("at_deadline", [53.0, 52.0, 40.0, 54.0])
def test_unknown_history_no_drop_beyond_noise_gets_grace(at_deadline):
    assert _resolve(soc_at_missed_deadline=at_deadline)[1] is True


def test_unknown_history_drop_just_beyond_noise_gets_no_grace():
    assert _resolve(soc_at_missed_deadline=54.01)[1] is False


def test_unknown_history_without_deadline_soc_is_legacy():
    assert _resolve()[1] is True


def test_stale_soc_no_grace():
    assert _resolve(soc_status="stale")[1] is False


def test_unreachable_last_known_plugged_with_continuous_session_gets_grace():
    state = {"unreachable": True, "plug_session_start": MISSED - timedelta(hours=1)}
    assert _resolve(**state)[1] is True


def test_unreachable_last_known_unplugged_no_grace():
    assert _resolve(plugged_in=False, unreachable=True)[1] is False


def test_tolerance_default_blocks_grace_within_five_points():
    goal = _goal(target_soc_percent=85, missed_goal_tolerance_percent=None)
    del goal["missed_goal_tolerance_percent"]  # absent key resolves to the default 5
    assert _resolve(goal, soc_percent=82.0)[1] is False
    assert _resolve(goal, soc_percent=66.0)[1] is True


def test_tolerance_boundary_exactly_at_threshold_no_grace():
    goal = _goal(target_soc_percent=85, missed_goal_tolerance_percent=5)
    assert _resolve(goal, soc_percent=80.0)[1] is False
    assert _resolve(goal, soc_percent=79.9)[1] is True


def test_tolerance_zero_is_previous_behaviour():
    goal = _goal(target_soc_percent=85, missed_goal_tolerance_percent=0)
    assert _resolve(goal, soc_percent=84.0)[1] is True


@pytest.mark.parametrize("raw", ["abc", float("nan")])
def test_tolerance_invalid_falls_back_to_default(raw):
    goal = _goal(target_soc_percent=85, missed_goal_tolerance_percent=raw)
    assert _resolve(goal, soc_percent=82.0)[1] is False


def test_tolerance_negative_clamped_to_zero():
    goal = _goal(target_soc_percent=85, missed_goal_tolerance_percent=-3)
    assert _resolve(goal, soc_percent=84.0)[1] is True


@pytest.mark.parametrize(
    "goal_kwargs, now, expected_missed",
    [
        ({"repeat": "weekdays"}, _at(2026, 9, 28, 10, 31), _at(2026, 9, 28, 10, 30)),
        (
            {"repeat": "every_n_days", "n_days": 3, "last_updated": "2026-09-18T08:00:00+02:00"},
            NOW,
            MISSED,
        ),
    ],
)
def test_rollover_goals_use_resolved_missed_deadline_for_continuity(
    goal_kwargs, now, expected_missed
):
    goal = _goal(**goal_kwargs)
    before = expected_missed - timedelta(hours=1)
    after = expected_missed + timedelta(minutes=1)
    assert resolve_ev_effective_deadline(goal, _state(plug_session_start=before), now, TZ)[1]
    assert not resolve_ev_effective_deadline(goal, _state(plug_session_start=after), now, TZ)[1]


# ---- SoC-at-deadline history lookup is only made when needed -----------------
@pytest.mark.asyncio
async def test_history_lookup_only_when_session_unknown_and_grace_possible():
    from unittest.mock import AsyncMock, patch

    from planner.pipeline import _load_soc_at_missed_deadline

    goal = _goal(soc_sensor="sensor.soc")
    lookup = AsyncMock(return_value=58.0)
    with patch("backend.core.ha_client.get_sensor_value_at", lookup):
        out = await _load_soc_at_missed_deadline(goal, _state(), NOW, TZ)
        assert out["soc_at_missed_deadline"] == 58.0
        lookup.assert_awaited_once_with("sensor.soc", MISSED)

        lookup.reset_mock()
        # Replug after the deadline already denies grace: no call.
        await _load_soc_at_missed_deadline(
            goal, _state(plug_session_start=MISSED + timedelta(minutes=1)), NOW, TZ
        )
        # SoC within tolerance (target 55 -> tolerance 5), no sensor: no call.
        await _load_soc_at_missed_deadline(
            {**goal, "missed_goal_tolerance_percent": 5}, _state(soc_percent=52.0), NOW, TZ
        )
        await _load_soc_at_missed_deadline(_goal(), _state(), NOW, TZ)
        lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_lookup_for_known_continuous_session():
    from unittest.mock import AsyncMock, patch

    from planner.pipeline import _load_soc_at_missed_deadline

    lookup = AsyncMock(return_value=60.0)
    with patch("backend.core.ha_client.get_sensor_value_at", lookup):
        out = await _load_soc_at_missed_deadline(
            _goal(soc_sensor="sensor.soc"), _state(plug_session_start=MISSED), NOW, TZ
        )
    assert out["soc_at_missed_deadline"] == 60.0
    lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_lookup_failure_keeps_legacy_state():
    from unittest.mock import AsyncMock, patch

    from planner.pipeline import _load_soc_at_missed_deadline

    goal = _goal(soc_sensor="sensor.soc")
    for lookup in (AsyncMock(return_value=None), AsyncMock(side_effect=RuntimeError("down"))):
        with patch("backend.core.ha_client.get_sensor_value_at", lookup):
            out = await _load_soc_at_missed_deadline(goal, _state(), NOW, TZ)
        assert "soc_at_missed_deadline" not in out
