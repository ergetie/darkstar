"""Tests for the zero-scheduled active-goal WARNING (design D5).

An EV charger with an active goal (required_kwh > 0, resolved deadline)
should never silently convert entirely to shortfall — the pipeline logs a
WARNING naming the charger, required kWh, reason and min chunk kWh. A goal
the solver deferred to cheaper post-horizon slots is on plan (INFO only).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from planner.pipeline import _warn_on_zero_scheduled_active_goals
from planner.solver.types import KeplerResultSlot


def _slot(start, end, ev_charger_results=None):
    return KeplerResultSlot(
        start_time=start,
        end_time=end,
        charge_kwh=0.0,
        discharge_kwh=0.0,
        grid_import_kwh=0.0,
        grid_export_kwh=0.0,
        soc_kwh=0.0,
        cost_sek=0.0,
        ev_charger_results=dict(ev_charger_results) if ev_charger_results else {},
    )


def _result(slots, ev_deferred_kwh=None):
    class _Result:
        pass

    r = _Result()
    r.slots = slots
    r.ev_deferred_kwh = ev_deferred_kwh or {}
    return r


def test_infeasible_goal_produces_warning(caplog):
    now = datetime(2026, 7, 17, 0, 0)
    deadline = now + timedelta(days=1)
    slots = [_slot(now, now + timedelta(minutes=15), ev_charger_results={"ev1": 0.0})]
    result = _result(slots)
    ev_states = [
        {
            "id": "ev1",
            "required_kwh": 2.6,
            "deadline": deadline,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "type": "current", "max_current_a": 14, "min_current_a": 6, "phases": [1, 2, 3]}
    ]

    with caplog.at_level("WARNING"):
        _warn_on_zero_scheduled_active_goals(result, ev_states, ev_chargers_cfg)

    messages = [r.getMessage() for r in caplog.records]
    assert any("ev1" in m and "ZERO" in m for m in messages)
    assert any("2.6" in m for m in messages)
    assert any("min_chunk_kwh" in m for m in messages)


def test_scheduled_goal_logs_no_warning(caplog):
    now = datetime(2026, 7, 17, 0, 0)
    deadline = now + timedelta(days=1)
    slots = [_slot(now, now + timedelta(minutes=15), ev_charger_results={"ev1": 5.0})]
    result = _result(slots)
    ev_states = [
        {
            "id": "ev1",
            "required_kwh": 1.0,
            "deadline": deadline,
        }
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "type": "current", "max_current_a": 14, "min_current_a": 6, "phases": [1, 2, 3]}
    ]

    with caplog.at_level("WARNING"):
        _warn_on_zero_scheduled_active_goals(result, ev_states, ev_chargers_cfg)

    assert not any("ZERO" in r.getMessage() for r in caplog.records)


def test_no_active_goal_logs_no_warning(caplog):
    now = datetime(2026, 7, 17, 0, 0)
    slots = [_slot(now, now + timedelta(minutes=15), ev_charger_results={"ev1": 0.0})]
    result = _result(slots)
    ev_states = [
        {"id": "ev1", "required_kwh": None, "deadline": None},
        {"id": "ev2", "required_kwh": 0.0, "deadline": now + timedelta(days=1)},
    ]
    ev_chargers_cfg = [{"id": "ev1", "type": "current", "max_current_a": 14, "phases": [1, 2, 3]}]

    with caplog.at_level("WARNING"):
        _warn_on_zero_scheduled_active_goals(result, ev_states, ev_chargers_cfg)

    assert not any("ZERO" in r.getMessage() for r in caplog.records)


def test_fully_deferred_goal_is_not_a_zero_schedule_warning(caplog):
    now = datetime(2026, 7, 17, 0, 0)
    deadline = now + timedelta(days=3)
    slots = [_slot(now, now + timedelta(minutes=15), ev_charger_results={"ev1": 0.0})]
    result = _result(slots, ev_deferred_kwh={"ev1": [6.0, 4.0]})
    ev_states = [
        {"id": "ev1", "required_kwh": 10.0, "deadline": deadline, "deferral_price_source": "forecast"}
    ]
    ev_chargers_cfg = [
        {"id": "ev1", "type": "current", "max_current_a": 14, "min_current_a": 6, "phases": [1, 2, 3]}
    ]

    with caplog.at_level("INFO"):
        _warn_on_zero_scheduled_active_goals(result, ev_states, ev_chargers_cfg)

    assert not any(r.levelname == "WARNING" for r in caplog.records)
    assert any("deferred" in r.getMessage() for r in caplog.records)
