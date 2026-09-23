"""fix-ev-current-charger-control 5.1/5.4: per-charger EV goal shortfall diagnostics."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz

from planner.pipeline import _warn_on_zero_scheduled_active_goals, compute_ev_goal_diagnostics
from planner.solver.types import KeplerInputSlot, KeplerResultSlot

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 9, 23, 17, 45))
DEADLINE = TZ.localize(datetime(2026, 9, 23, 18, 30))
SLOT = timedelta(minutes=15)

GOE_CFG = {
    "id": "goe",
    "type": "current",
    "max_power_kw": 11.0,
    "min_current_a": 6,
    "phases": [1, 2, 3],
}


def _slots(
    n: int,
    *,
    load_kw: float = 1.4,
    water_kw: float = 3.0,
    ev_kw: float = 0.0,
    shortfall_kwh: float = 0.6,
) -> tuple[list[KeplerInputSlot], list[KeplerResultSlot]]:
    inputs, results = [], []
    for i in range(n):
        start = NOW + i * SLOT
        inputs.append(
            KeplerInputSlot(
                start_time=start,
                end_time=start + SLOT,
                load_kwh=load_kw * 0.25,
                pv_kwh=0.0,
                import_price_sek_kwh=1.0,
                export_price_sek_kwh=0.5,
            )
        )
        results.append(
            KeplerResultSlot(
                start_time=start,
                end_time=start + SLOT,
                charge_kwh=0.0,
                discharge_kwh=0.0,
                grid_import_kwh=0.0,
                grid_export_kwh=0.0,
                soc_kwh=5.0,
                cost_sek=0.0,
                water_heat_kw=water_kw,
                ev_charger_results={"goe": ev_kw},
                ev_shortfall_kwh={"goe": shortfall_kwh},
            )
        )
    return inputs, results


class _Result:
    def __init__(self, slots):
        self.slots = slots


def _state(**overrides) -> dict:
    state = {"id": "goe", "plugged_in": True, "deadline": DEADLINE, "required_kwh": 0.6}
    state.update(overrides)
    return state


def test_grid_limit_reproduces_2026_09_23_case():
    """8 kW cap, 3 kW water heater forced on, 1.4 kW house load, ~4.14 kW EV minimum."""
    inputs, results = _slots(3)
    diag = compute_ev_goal_diagnostics(_Result(results), inputs, [_state()], [GOE_CFG], 8.0, NOW)

    assert diag["goe"]["scheduled_kwh"] == 0.0
    assert diag["goe"]["shortfall_kwh"] == 0.6
    assert diag["goe"]["reason"] == "grid_limit"
    assert diag["goe"]["deadline"] == DEADLINE.isoformat()
    assert diag["goe"]["max_import_kw"] == 8.0


def test_cost_tradeoff_when_grid_has_room():
    inputs, results = _slots(3, water_kw=0.0)
    diag = compute_ev_goal_diagnostics(_Result(results), inputs, [_state()], [GOE_CFG], 8.0, NOW)
    assert diag["goe"]["reason"] == "cost_tradeoff"


def test_cost_tradeoff_when_no_import_cap():
    inputs, results = _slots(3)
    diag = compute_ev_goal_diagnostics(_Result(results), inputs, [_state()], [GOE_CFG], None, NOW)
    assert diag["goe"]["reason"] == "cost_tradeoff"


def test_deadline_too_close_without_eligible_slots():
    inputs, results = _slots(3)
    state = _state(deadline=NOW + timedelta(minutes=10))
    diag = compute_ev_goal_diagnostics(_Result(results), inputs, [state], [GOE_CFG], 8.0, NOW)
    assert diag["goe"]["reason"] == "deadline_too_close"


def test_fully_scheduled_goal_has_no_shortfall():
    inputs, results = _slots(3, water_kw=0.0, ev_kw=4.2, shortfall_kwh=0.0)
    diag = compute_ev_goal_diagnostics(_Result(results), inputs, [_state()], [GOE_CFG], 8.0, NOW)
    assert diag["goe"]["shortfall_kwh"] == 0.0
    assert diag["goe"]["reason"] is None
    assert diag["goe"]["scheduled_kwh"] == 3.15


def test_unplugged_or_goalless_chargers_are_skipped():
    inputs, results = _slots(3)
    states = [_state(plugged_in=False), _state(id="other", required_kwh=None)]
    assert compute_ev_goal_diagnostics(_Result(results), inputs, states, [GOE_CFG], 8.0, NOW) == {}


def test_zero_warning_includes_reason(caplog):
    inputs, results = _slots(3)
    result = _Result(results)
    diag = compute_ev_goal_diagnostics(result, inputs, [_state()], [GOE_CFG], 8.0, NOW)
    with caplog.at_level(logging.WARNING, logger="darkstar.planner"):
        _warn_on_zero_scheduled_active_goals(result, [_state()], [GOE_CFG], diag)
    assert any("ZERO" in m and "reason=grid_limit" in m for m in caplog.messages)
