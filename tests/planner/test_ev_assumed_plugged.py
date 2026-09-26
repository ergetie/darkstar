"""Assumed-plugged planning for unplugged chargers with a goal (ev-goal-lifecycle-feedback 5.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz

from planner.pipeline import _resolve_ev_charger_plan_state
from planner.solver.adapter import build_ev_charger_inputs
from planner.solver.kepler import KeplerSolver
from planner.solver.types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
)

TZ = pytz.timezone("Europe/Stockholm")
NOW = TZ.localize(datetime(2026, 9, 25, 22, 0))


def _cfg(**goal) -> dict:
    return {
        "id": "ev1",
        "enabled": True,
        "type": "current",
        "max_current_a": 16,
        "min_current_a": 6,
        "phases": ["L1", "L2", "L3"],
        "battery_capacity_kwh": 60.0,
        **goal,
    }


GOAL = {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}


def test_unplugged_with_goal_and_live_soc_is_assumed_plugged():
    state = _resolve_ev_charger_plan_state(
        _cfg(**GOAL), {"plugged_in": False, "soc_percent": 50.0}, {}, NOW, TZ, "", 1
    )
    assert state["assumed_plugged"] is True
    assert state["deadline"] == TZ.localize(datetime(2026, 9, 26, 7, 0))
    assert abs(state["required_kwh"] - 18.0) < 1e-6


def test_unplugged_uses_persisted_soc_when_live_missing():
    state = _resolve_ev_charger_plan_state(
        _cfg(**GOAL),
        {"plugged_in": False, "soc_percent": None},
        {"current_soc_percent": 70.0},
        NOW,
        TZ,
        "",
        1,
    )
    assert state["assumed_plugged"] is True
    assert abs(state["required_kwh"] - 6.0) < 1e-6
    assert state["soc_percent"] == 70.0


def test_unplugged_without_known_soc_is_not_planned():
    state = _resolve_ev_charger_plan_state(
        _cfg(**GOAL), {"plugged_in": False, "soc_percent": None}, {}, NOW, TZ, "", 1
    )
    assert state["assumed_plugged"] is False
    assert state["deadline"] is None
    assert state["required_kwh"] is None


def test_unplugged_without_goal_is_not_planned():
    state = _resolve_ev_charger_plan_state(
        _cfg(target_soc_percent=None), {"plugged_in": False, "soc_percent": 50.0}, {}, NOW, TZ, "", 1
    )
    assert state["assumed_plugged"] is False
    assert state["deadline"] is None


def test_plugged_charger_unchanged():
    state = _resolve_ev_charger_plan_state(
        _cfg(**GOAL), {"plugged_in": True, "soc_percent": 50.0}, {}, NOW, TZ, "", 1
    )
    assert state["assumed_plugged"] is False
    assert state["plugged_in"] is True
    assert state["deadline"] == TZ.localize(datetime(2026, 9, 26, 7, 0))


# --- Kepler ---


def _slots(n: int = 16, pv_kwh: float = 0.0) -> list[KeplerInputSlot]:
    start = datetime(2026, 9, 25, 22, 0)
    return [
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15 * i),
            end_time=start + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.2,
            pv_kwh=pv_kwh,
            import_price_sek_kwh=1.0 + (0.5 if i < 4 else 0.0),
            export_price_sek_kwh=0.0,
        )
        for i in range(n)
    ]


def _config(chargers: list[EVChargerInput], **kw) -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.1,
        max_import_power_kw=25.0,
        ev_chargers=chargers,
        **kw,
    )


def _charger(*, plugged: bool, assumed: bool) -> EVChargerInput:
    return EVChargerInput(
        id="ev1",
        max_power_kw=11.0,
        battery_capacity_kwh=60.0,
        current_soc_percent=50.0,
        plugged_in=plugged,
        assumed_plugged=assumed,
        deadline=datetime(2026, 9, 26, 2, 0),
        required_kwh=5.0,
        control_type="current",
        min_power_kw=4.2,
    )


def test_kepler_plans_assumed_plugged_charger_in_energy_balance():
    result = KeplerSolver().solve(
        KeplerInput(slots=_slots(), initial_soc_kwh=5.0),
        _config([_charger(plugged=False, assumed=True)]),
    )
    scheduled = sum(s.ev_charger_results.get("ev1", 0.0) * 0.25 for s in result.slots)
    assert abs(scheduled - 5.0) < 0.05
    # Its energy is imported (counts in the energy balance / import).
    charging = [s for s in result.slots if s.ev_charger_results.get("ev1", 0.0) > 0.1]
    assert all(s.grid_import_kwh > 0 for s in charging)


def _surplus_kwh(*, plugged: bool, assumed: bool) -> float:
    result = KeplerSolver().solve(
        KeplerInput(slots=_slots(pv_kwh=3.0), initial_soc_kwh=10.0),
        _config(
            [_charger(plugged=plugged, assumed=assumed)],
            excess_pv_slots=[True] * 16,
            excess_pv_priority=[
                ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=1.0, charger_id="ev1")
            ],
        ),
    )
    return sum(s.ev_surplus_kw.get("ev1", 0.0) for s in result.slots)


def test_kepler_gives_assumed_plugged_charger_no_surplus():
    # Same setup yields surplus for a really plugged charger...
    assert _surplus_kwh(plugged=True, assumed=False) > 0
    # ...but never for an assumed-plugged one.
    assert _surplus_kwh(plugged=False, assumed=True) == 0


def test_kepler_unplugged_not_assumed_gets_no_variables():
    result = KeplerSolver().solve(
        KeplerInput(slots=_slots(), initial_soc_kwh=5.0),
        _config([_charger(plugged=False, assumed=False)]),
    )
    assert all("ev1" not in s.ev_charger_results for s in result.slots)


def test_adapter_carries_assumed_flag_only_when_unplugged():
    cfg = [_cfg(**GOAL)]
    assumed = build_ev_charger_inputs(
        cfg, [{"id": "ev1", "plugged_in": False, "assumed_plugged": True, "soc_percent": 50.0}]
    )
    plugged = build_ev_charger_inputs(
        cfg, [{"id": "ev1", "plugged_in": True, "assumed_plugged": True, "soc_percent": 50.0}]
    )
    assert assumed[0].assumed_plugged is True
    assert plugged[0].assumed_plugged is False
