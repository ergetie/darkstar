"""In-progress slot uses remaining time for EV energy (ev-goal-shortfall-recovery 2.4).

Spec: ``ev-target-charging`` — "In-progress slot uses remaining time for EV
energy". A replan 7 minutes into a 15-minute slot must bound slot-0 EV energy
by the 8 minutes left and report slot-0 kW over those 8 minutes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.kepler import KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
SLOT_START = TZ.localize(datetime(2026, 9, 24, 10, 15))
MAX_KW = 11.0


def _slots(n: int, prices: list[float]) -> list[KeplerInputSlot]:
    out: list[KeplerInputSlot] = []
    for i in range(n):
        s = SLOT_START + timedelta(minutes=15 * i)
        out.append(
            KeplerInputSlot(
                start_time=s,
                end_time=s + timedelta(minutes=15),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=prices[i],
                export_price_sek_kwh=0.0,
            )
        )
    return out


def _config(required_kwh: float, deadline: datetime, control_type: str = "current"):
    ev = EVChargerInput(
        id="goe",
        max_power_kw=MAX_KW,
        min_power_kw=4.14,
        battery_capacity_kwh=60.0,
        current_soc_percent=53.0,
        plugged_in=True,
        deadline=deadline,
        required_kwh=required_kwh,
        control_type=control_type,
    )
    return KeplerConfig(
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


def _solve(slots, cfg, remaining_h):
    inp = KeplerInput(slots=slots, initial_soc_kwh=0.0, first_slot_remaining_h=remaining_h)
    result = KeplerSolver().solve(inp, cfg)
    assert result.is_optimal
    return result


def test_replan_7_min_into_slot_caps_ev_energy():
    """10:22 replan for the 10:15-10:30 slot: at most max_kw x 8/60 kWh."""
    slots = _slots(1, [1.0])
    remaining_h = 8 / 60
    # Ask for more than fits in the remaining 8 minutes at full power.
    result = _solve(slots, _config(3.0, slots[0].end_time), remaining_h)

    kw = result.slots[0].ev_charger_results["goe"]
    energy_kwh = kw * remaining_h
    assert energy_kwh <= MAX_KW * remaining_h + 1e-6
    # Reported kW is energy / remaining time, so it cannot exceed the charger max.
    assert kw == pytest.approx(MAX_KW, abs=1e-4)
    assert result.ev_shortfall_kwh["goe"] == pytest.approx(
        3.0 - MAX_KW * remaining_h, abs=1e-3
    )


def test_partial_slot_reports_higher_kw_for_same_energy():
    """1.2 kWh needed in the 8 min left -> 9 kW, not the 4.8 kW of a full slot."""
    slots = _slots(1, [1.0])
    remaining_h = 8 / 60
    result = _solve(slots, _config(1.2, slots[0].end_time), remaining_h)

    kw = result.slots[0].ev_charger_results["goe"]
    assert kw == pytest.approx(1.2 / remaining_h, abs=1e-3)


def test_binary_charger_partial_slot_uses_remaining_time():
    slots = _slots(1, [1.0])
    remaining_h = 8 / 60
    result = _solve(slots, _config(3.0, slots[0].end_time, "binary"), remaining_h)

    kw = result.slots[0].ev_charger_results["goe"]
    assert kw == pytest.approx(MAX_KW, abs=1e-4)


def test_energy_moves_to_later_slot_when_first_slot_is_short():
    """Energy that no longer fits in slot 0 lands in slot 1."""
    slots = _slots(2, [1.0, 1.0])
    remaining_h = 5 / 60
    result = _solve(slots, _config(2.0, slots[1].end_time), remaining_h)

    e0 = result.slots[0].ev_charger_results["goe"] * remaining_h
    e1 = result.slots[1].ev_charger_results["goe"] * 0.25
    assert e0 <= MAX_KW * remaining_h + 1e-6
    assert e0 + e1 == pytest.approx(2.0, abs=1e-3)


@pytest.mark.parametrize("remaining_h", [None, 0.25])
def test_boundary_replan_unchanged(remaining_h):
    """Replan at a slot boundary: full-slot bounds, identical to before."""
    slots = _slots(1, [1.0])
    result = _solve(slots, _config(3.0, slots[0].end_time), remaining_h)

    kw = result.slots[0].ev_charger_results["goe"]
    assert kw == pytest.approx(MAX_KW, abs=1e-4)
    assert result.ev_shortfall_kwh["goe"] == pytest.approx(3.0 - MAX_KW * 0.25, abs=1e-3)


def _surplus_solve(remaining_h: float | None) -> float:
    """One surplus-eligible slot with 1.2 kWh net excess PV, no battery."""
    from planner.solver.types import ExcessPVSinkEntry

    start = SLOT_START
    slots = [
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=1.2,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=0.0,
        )
    ]
    ev = EVChargerInput(
        id="goe",
        max_power_kw=7.4,
        min_power_kw=4.14,
        battery_capacity_kwh=60.0,
        current_soc_percent=50.0,
        plugged_in=True,
        deadline=None,
        required_kwh=None,
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
        enable_export=True,
        max_export_power_kw=10.0,
        excess_pv_slots=[True],
        excess_pv_priority=[
            ExcessPVSinkEntry(type="ev", effective_reward_sek_per_kwh=2.0, charger_id="goe")
        ],
        ev_chargers=[ev],
    )
    result = _solve(slots, cfg, remaining_h)
    return result.slots[0].ev_surplus_kw.get("goe", 0.0)


def test_surplus_in_partial_first_slot_uses_remaining_time():
    """7 min into the slot: surplus kWh = kW x 8/60, so the 1.2 kWh excess allows full 7.4 kW."""
    remaining_h = 8 / 60
    kw = _surplus_solve(remaining_h)
    assert kw == pytest.approx(7.4, abs=1e-3)
    assert kw * remaining_h <= 1.2 + 1e-6


def test_surplus_at_slot_boundary_unchanged():
    """Full slot: the 1.2 kWh excess caps surplus at 1.2 / 0.25 = 4.8 kW."""
    assert _surplus_solve(None) == pytest.approx(4.8, abs=1e-3)
