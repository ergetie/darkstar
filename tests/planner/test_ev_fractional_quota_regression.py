"""End-to-end regression test for the 2026-07-17 incident (proposal.md).

A real, active EV goal (2.6 kWh, deadline next day) produced zero scheduled
charging across a 32-hour horizon with ``status: Optimal`` and no warning.
Root cause: the solver only planned `type: current` chargers as binary
full-power-or-off (smallest unit = max_power_kw * 0.25h = 2.425 kWh for a
9.7kW charger), and the multi-day quota spreader split 2.6 kWh across two
days with no awareness of that minimum unit ({0.88, 1.72}), making both
days' quota caps infeasible.

This test reproduces the scenario end-to-end (adapter -> solver; the
multi-day quota split was removed by ev-planning-model) and asserts the fix:
nonzero scheduled charging, total energy meeting the requirement.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.adapter import build_ev_charger_inputs
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")


def test_2_6_kwh_goal_over_32_hour_horizon_is_not_silently_zeroed():
    now = TZ.localize(datetime(2026, 7, 17, 0, 0))
    deadline = now + timedelta(hours=32)  # "deadline next day", ~32h horizon
    required_kwh = 2.6

    charger_cfg = {
        "id": "ev1",
        "enabled": True,
        "battery_capacity_kwh": 10.0,
        "type": "current",
        "min_current_a": 6,
        "max_current_a": 16,
        "phases": [1, 2, 3],
    }
    ev_input = build_ev_charger_inputs(
        [charger_cfg],
        [
            {
                "id": "ev1",
                "soc_percent": 50.0,
                "plugged_in": True,
                "deadline": deadline,
                "required_kwh": required_kwh,
                "keep_on_after_target": False,
            }
        ],
    )
    assert len(ev_input) == 1
    assert ev_input[0].min_power_kw > 0.0

    n = 128  # 32 hours of 15-minute slots
    slots = [
        KeplerInputSlot(
            start_time=now + timedelta(minutes=15 * i),
            end_time=now + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.0,
        )
        for i in range(n)
    ]

    cfg = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=ev_input,
    )
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal

    total_scheduled_kwh = sum(s.ev_charger_results.get("ev1", 0.0) * 0.25 for s in result.slots)
    assert total_scheduled_kwh >= required_kwh - 0.01, (
        f"active goal silently zeroed out: scheduled={total_scheduled_kwh}, "
        f"required={required_kwh}"
    )
    assert any(s.ev_charger_results.get("ev1", 0.0) > 0.01 for s in result.slots)
