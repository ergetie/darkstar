"""Missed-goal grace targets are soft: no goal-at-risk for their shortfall."""

from datetime import UTC, datetime, timedelta

from backend.api.routers import ev as ev_router
from executor.goal_risk import pause_puts_goal_at_risk

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(hours=1)


def _goal(**extra):
    return {
        "deadline": DEADLINE.isoformat(),
        "required_kwh": 10.0,
        "last_planned_at": NOW.isoformat(),
        **extra,
    }


def _diag(**extra):
    return {
        "shortfall_kwh": 5.0,
        "required_kwh": 10.0,
        "reason": "price",
        "deadline": DEADLINE.isoformat(),
        **extra,
    }


def test_regular_shortfall_is_at_risk():
    assert pause_puts_goal_at_risk(_goal(), _diag(), 0.0, NOW)[0] is True


def test_grace_shortfall_is_not_at_risk():
    at_risk, _ = pause_puts_goal_at_risk(_goal(), _diag(missed_goal_grace=True), 0.0, NOW)
    assert at_risk is False


def test_grace_goal_charging_near_deadline_is_not_at_risk():
    goal = _goal(missed_goal_grace=True)
    assert pause_puts_goal_at_risk(goal, None, 5.0, NOW)[0] is False


def test_regular_goal_charging_near_deadline_is_at_risk():
    assert pause_puts_goal_at_risk(_goal(), None, 5.0, NOW)[0] is True


def test_stale_grace_diagnostics_still_fail_open():
    diag = _diag(missed_goal_grace=True, deadline=(DEADLINE + timedelta(hours=1)).isoformat())
    assert pause_puts_goal_at_risk(_goal(), diag, 0.0, NOW)[0] is True


def test_router_ignores_grace_shortfall():
    persisted = _goal()
    assert ev_router._active_goal_shortfall(_diag(), persisted) is not None
    assert ev_router._active_goal_shortfall(_diag(missed_goal_grace=True), persisted) is None
