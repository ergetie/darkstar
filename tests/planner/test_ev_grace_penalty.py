"""Price-derived soft penalty of the missed-goal grace target (D3).

Spec: ``ev-missed-goal-recovery`` - "Grace is cost-aware", "Grace penalty is
price-relative", "Price spike", "Flat prices", "Expensive now, cheap overnight",
"Price unknown".
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pytz import timezone as pytz_timezone

from planner.solver.adapter import (
    EV_GRACE_MIN_MARGIN_SEK,
    EV_GRACE_PENALTY_FALLBACK_SEK,
    EV_GRACE_SPREAD_FRACTION,
    build_ev_charger_inputs,
    grace_shortfall_penalty,
)
from planner.solver.kepler import EV_SHORTFALL_PENALTY_DEFAULT, KeplerSolver
from planner.solver.types import EVChargerInput, KeplerConfig, KeplerInput, KeplerInputSlot

TZ = pytz_timezone("Europe/Stockholm")
START = TZ.localize(datetime(2026, 11, 10, 7, 30))
CAPACITY_KWH = 60.0
CHARGER_CFG = {
    "id": "ev1",
    "type": "current",
    "max_current_a": 16,
    "min_current_a": 6,
    "phases": [1, 2, 3],
    "battery_capacity_kwh": CAPACITY_KWH,
    "charge_efficiency": 1.0,
    "charge_overhead_kw": 0.0,
    "start_loss_kwh": 0.0,
}


def _slots(prices: list[float | None]) -> list[KeplerInputSlot]:
    return [
        KeplerInputSlot(
            start_time=START + timedelta(minutes=15 * i),
            end_time=START + timedelta(minutes=15 * (i + 1)),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=p,  # type: ignore[arg-type]
            export_price_sek_kwh=0.0,
        )
        for i, p in enumerate(prices)
    ]


def _solve_grace(
    prices: list[float],
    grace_slots: int,
    next_slots: int,
    required_kwh: float = 2.0,
    charge_efficiency: float = 1.0,
) -> tuple[list[float], float]:
    """Solve a grace charger; returns (kWh per slot, shortfall kWh)."""
    slots = _slots(prices)
    grace_deadline = slots[grace_slots - 1].end_time
    next_deadline = slots[next_slots - 1].end_time
    state = {
        "id": "ev1",
        "soc_percent": 50.0,
        "plugged_in": True,
        "deadline": grace_deadline,
        "required_kwh": required_kwh,
        "missed_goal_grace": True,
        "next_deadline": next_deadline,
    }
    [ev] = build_ev_charger_inputs(
        [{**CHARGER_CFG, "charge_efficiency": charge_efficiency}], [state], slots=slots
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
        max_import_power_kw=11.0,  # bounds import so negative prices stay solvable
        ev_chargers=[ev],
    )
    result = KeplerSolver().solve(KeplerInput(slots=slots, initial_soc_kwh=0.0), cfg)
    assert result.is_optimal
    energy = [s.ev_charger_results.get("ev1", 0.0) * 0.25 for s in result.slots]
    return energy, result.ev_shortfall_kwh["ev1"]


# ---- penalty derivation -------------------------------------------------------
def test_penalty_formula_torleif_like():
    prices = [5.8] * 10 + [4.0] * 20 + [2.4] * 20
    penalty = grace_shortfall_penalty(_slots(prices), _slots(prices)[-1].end_time)
    assert penalty == pytest.approx(2.4 + EV_GRACE_SPREAD_FRACTION * (5.8 - 2.4))
    assert 3.2 <= penalty <= 3.3


def test_penalty_ignores_slots_after_next_deadline():
    slots = _slots([2.0, 2.0, 0.1, 0.1])
    penalty = grace_shortfall_penalty(slots, slots[1].end_time)
    assert penalty == pytest.approx(2.0 + EV_GRACE_MIN_MARGIN_SEK)


def test_flat_prices_penalty_exceeds_price_by_margin():
    assert grace_shortfall_penalty(_slots([1.5] * 8), None) == pytest.approx(
        1.5 + EV_GRACE_MIN_MARGIN_SEK
    )


def test_negative_minimum_floored_at_zero_stays_positive():
    penalty = grace_shortfall_penalty(_slots([-0.5, 1.0, 1.0]), None)
    assert penalty == pytest.approx(EV_GRACE_SPREAD_FRACTION * 1.5)
    assert penalty > 0


@pytest.mark.parametrize("slots", [None, [], _slots([None, None])])
def test_unknown_prices_use_fallback(slots):
    assert grace_shortfall_penalty(slots, None) == EV_GRACE_PENALTY_FALLBACK_SEK


def test_regular_goal_keeps_global_penalty():
    state = {"id": "ev1", "plugged_in": True, "missed_goal_grace": False}
    [ev] = build_ev_charger_inputs([CHARGER_CFG], [state], slots=_slots([1.0]))
    assert ev.shortfall_penalty_sek_per_kwh is None
    assert EV_SHORTFALL_PENALTY_DEFAULT == 50.0


# ---- solver behaviour ---------------------------------------------------------
def _shape(scale: float) -> list[float]:
    """Grace window = slots 0-7, next deadline at slot 16; one clear cheap slot (3)."""
    window = [1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 1.0]
    later = [0.5] * 8
    return [p * scale for p in window + later]


@pytest.mark.parametrize("scale", [0.1, 1.0, 10.0])
def test_price_relative_cheap_and_expensive_day_same_pattern(scale):
    energy, shortfall = _solve_grace(_shape(scale), grace_slots=8, next_slots=16)
    assert shortfall == pytest.approx(0.0, abs=1e-3)
    assert energy[3] == pytest.approx(2.0, abs=1e-3)
    assert sum(energy) == pytest.approx(2.0, abs=1e-3)


def test_price_spike_slots_get_no_grace_energy():
    prices = [1.0, 1.0, 10.0, 10.0, 1.0, 1.0, 1.0, 1.0] + [1.0] * 8
    energy, _ = _solve_grace(prices, grace_slots=8, next_slots=16)
    assert energy[2] == energy[3] == 0.0
    assert sum(energy) == pytest.approx(2.0, abs=1e-3)


def test_flat_prices_still_charge():
    energy, shortfall = _solve_grace([1.0] * 16, grace_slots=8, next_slots=16)
    assert sum(energy) == pytest.approx(2.0, abs=1e-3)
    assert shortfall == pytest.approx(0.0, abs=1e-3)


def test_negative_minimum_price_charges_in_negative_slot():
    prices = [1.0, -0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0] + [1.0] * 8
    energy, shortfall = _solve_grace(prices, grace_slots=8, next_slots=16)
    # Paid to charge: the negative slot is used (at least the requirement), nothing else.
    assert energy[1] >= 2.0 - 1e-3
    assert sum(energy) == pytest.approx(energy[1], abs=1e-3)
    assert shortfall == pytest.approx(0.0, abs=1e-3)


def test_expensive_now_cheap_overnight_schedules_no_grace_energy():
    """Torleif-like: 5.8 SEK now, 2.4 SEK overnight before the next goal."""
    prices = [5.8] * 10 + [4.0] * 22 + [2.4] * 20  # 07:30 ... next morning
    energy, shortfall = _solve_grace(
        prices, grace_slots=10, next_slots=len(prices), required_kwh=11.4
    )
    assert sum(energy) == 0.0
    assert shortfall == pytest.approx(11.4, abs=1e-3)


def test_unknown_prices_grace_still_soft_and_does_not_raise():
    slots = _slots([1.0] * 4)
    state = {
        "id": "ev1",
        "plugged_in": True,
        "deadline": slots[-1].end_time,
        "required_kwh": 1.0,
        "missed_goal_grace": True,
    }
    [ev] = build_ev_charger_inputs([CHARGER_CFG], [state], slots=None)
    assert isinstance(ev, EVChargerInput)
    assert ev.shortfall_penalty_sek_per_kwh == EV_GRACE_PENALTY_FALLBACK_SEK


def test_penalty_scaled_by_charge_efficiency():
    slots = _slots([2.0] * 8)
    base = grace_shortfall_penalty(slots, None)
    assert grace_shortfall_penalty(slots, None, 0.8) == pytest.approx(base / 0.8)
    # Out-of-range efficiency never inflates or breaks the penalty.
    assert grace_shortfall_penalty(slots, None, 0.0) == pytest.approx(base)
    assert grace_shortfall_penalty(slots, None, 1.5) == pytest.approx(base)


def test_flat_expensive_prices_still_charge_despite_losses():
    """Margin must survive charge losses (cost per delivered kWh is price / efficiency)."""
    energy, shortfall = _solve_grace(
        [5.0] * 16, grace_slots=8, next_slots=16, charge_efficiency=0.9
    )
    assert shortfall == pytest.approx(0.0, abs=1e-2)
    assert sum(energy) > 2.0
