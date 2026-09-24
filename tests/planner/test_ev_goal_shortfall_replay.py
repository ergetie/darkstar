"""Replay of the 2026-09-24 incident (ev-goal-shortfall-recovery 6.2).

Goal 53% -> 55% by 10:30 (1.2 kWh on a 60 kWh car). The go-e went
``unavailable`` 10:14:50-10:21:45; charging resumed 10:22 at 6 A and the car
was still at 53% at 10:30. With this change:

1. The charger being unreachable keeps its last known plug state (plugged in).
2. The 10:22 replan bounds slot-0 EV energy by the 8 minutes left, reports a
   higher kW, and the executor rounds amps up.
3. At 10:31 the missed goal stays active in a 4 h grace window and the
   remaining energy lands in the cheapest slots before 14:30.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from backend.core import ev_plug
from backend.core.ev_plug import resolve_plug_state
from executor.load_balancer import planned_kw_to_amps
from planner.pipeline import resolve_ev_effective_deadline
from planner.solver.kepler import KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
CAPACITY_KWH = 60.0
MAX_KW = 11.0
MIN_KW = 6 * 230 * 3 / 1000  # 4.14 kW
GOAL = {
    "id": "goe",
    "target_soc_percent": 55,
    "ready_by": "10:30",
    "repeat": "none",
    "ready_by_date": "2026-09-24",
    "missed_goal_grace_hours": 4,
}


def _at(hh: int, mm: int, ss: int = 0) -> datetime:
    return TZ.localize(datetime(2026, 9, 24, hh, mm, ss))


def _slots(start: datetime, prices: list[float]) -> list[KeplerInputSlot]:
    return [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=p,
            export_price_sek_kwh=0.0,
        )
        for i, p in enumerate(prices)
    ]


def _solve(slots, soc: float, deadline: datetime, remaining_h: float | None):
    ev = EVChargerInput(
        id="goe",
        max_power_kw=MAX_KW,
        min_power_kw=MIN_KW,
        battery_capacity_kwh=CAPACITY_KWH,
        current_soc_percent=soc,
        plugged_in=True,
        deadline=deadline,
        required_kwh=(55 - soc) / 100 * CAPACITY_KWH,
        control_type="current",
    )
    cfg = KeplerConfig(
        capacity_kwh=0.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        max_charge_power_kw=0.0,
        max_discharge_power_kw=0.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        wear_cost_sek_per_kwh=0.0,
        ev_chargers=[ev],
    )
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0, first_slot_remaining_h=remaining_h)
    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal
    return result


@pytest.fixture(autouse=True)
def _clear_plug_state():
    ev_plug._last_known_plugged.clear()
    yield
    ev_plug._last_known_plugged.clear()


def test_unreachable_window_keeps_car_plugged_in():
    assert resolve_plug_state("goe", "Charging", "WaitCar,Charging") == (True, False)
    # 10:14:50 go-e drops off HA.
    assert resolve_plug_state("goe", "unavailable", "WaitCar,Charging") == (True, True)


def test_replan_at_1022_uses_remaining_eight_minutes():
    slot = _slots(_at(10, 15), [1.0])
    remaining_h = (slot[0].end_time - _at(10, 22)).total_seconds() / 3600
    result = _solve(slot, 53.0, _at(10, 30), remaining_h)

    kw = result.slots[0].ev_charger_results["goe"]
    # 1.2 kWh in 8 min -> 9 kW (not the 4.8 kW of a full slot).
    assert kw == pytest.approx(1.2 / remaining_h, abs=1e-3)
    # Rounded up: 9000 / 690 = 13.04 -> 14 A, never below plan.
    amps = planned_kw_to_amps(kw, 3, min_current_a=6, max_current_a=16)
    assert amps == 14
    assert amps * 690 / 1000 >= kw


def test_missed_goal_recovers_in_cheapest_grace_slots():
    now = _at(10, 31)
    plugged_in, unreachable = True, False
    deadline, in_grace = resolve_ev_effective_deadline(
        GOAL, {"soc_percent": 53.0, "plugged_in": plugged_in, "unreachable": unreachable}, now, TZ
    )
    assert in_grace is True
    assert deadline == _at(14, 30)

    # 10:30 .. 15:30 (20 slots). Cheapest pair at 12:00-12:30; after 14:30 even
    # cheaper, but outside the grace window.
    prices = [2.0] * 20
    prices[6] = prices[7] = 0.5  # 12:00, 12:15
    for i in range(16, 20):  # 14:30 .. 15:30
        prices[i] = 0.1
    slots = _slots(_at(10, 30), prices)
    result = _solve(slots, 53.0, deadline, remaining_h=None)

    energy = {
        s.start_time: s.ev_charger_results.get("goe", 0.0) * 0.25 for s in result.slots
    }
    assert sum(energy.values()) == pytest.approx(1.2, abs=1e-3)
    assert energy[_at(12, 0)] + energy[_at(12, 15)] == pytest.approx(1.2, abs=1e-3)
    assert all(e == 0.0 for t, e in energy.items() if t >= _at(14, 30))
    assert result.slots[0].ev_shortfall_kwh["goe"] == pytest.approx(0.0, abs=1e-3)
