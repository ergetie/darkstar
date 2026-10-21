"""Tests for soft max-SoC constraint in Kepler solver."""
from datetime import datetime, timedelta

import pulp

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def _make_slots(n: int, import_price: float = 0.5, export_price: float = 0.4) -> list[KeplerInputSlot]:
    start = datetime(2025, 6, 1, 10, 0)
    slots = []
    for i in range(n):
        s = start + timedelta(hours=i)
        e = s + timedelta(hours=1)
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=0.5,
                pv_kwh=0.0,
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )
    return slots


def _base_config(**kwargs) -> KeplerConfig:
    defaults = dict(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        wear_cost_sek_per_kwh=0.01,
        target_soc_kwh=None,
    )
    defaults.update(kwargs)
    return KeplerConfig(**defaults)


def test_initial_soc_above_max_soc_yields_optimal_with_discharge():
    """Initial SoC above max_soc_kwh must still solve Optimally and discharge slot 0."""
    # capacity=10, max_soc_percent=90 → max_soc_kwh=9.0
    # initial_soc=9.5 > 9.0 → old code: infeasible; new code: optimal with overshoot
    config = _base_config(capacity_kwh=10.0, max_soc_percent=90.0)
    input_data = KeplerInput(slots=_make_slots(4), initial_soc_kwh=9.5)

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal, f"Expected Optimal, got {result.status_msg}"

    # Slot 0 should have discharge or export to bring SoC back down
    slot0 = result.slots[0]
    assert slot0.discharge_kwh > 0 or slot0.grid_export_kwh > 0, (
        "Expected discharge or export in slot 0 to bring SoC down from overshoot"
    )


def test_incident_case_capacity_19_2():
    """Reproduce the production incident: capacity=19.2, max_soc_percent=95, initial_soc=18.989."""
    config = _base_config(
        capacity_kwh=19.2,
        min_soc_percent=15,
        max_soc_percent=95,
    )
    # initial_soc=18.989 > 19.2*0.95=18.24 → old code: infeasible
    input_data = KeplerInput(slots=_make_slots(8), initial_soc_kwh=18.989)

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal, f"Expected Optimal for incident case, got {result.status_msg}"


def test_normal_soc_within_max_no_overshoot():
    """When initial_soc <= max_soc_kwh, all soc_overshoot values should be zero."""
    config = _base_config(capacity_kwh=10.0, max_soc_percent=90.0)
    # initial_soc=7.0 < max_soc_kwh=9.0
    input_data = KeplerInput(slots=_make_slots(4), initial_soc_kwh=7.0)

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal
    # All slots should stay within the max_soc ceiling (no overshoot needed)
    max_soc_kwh = 10.0 * 0.9
    for slot in result.slots:
        if slot.soc_kwh is not None:
            assert slot.soc_kwh <= max_soc_kwh + 0.01, (
                f"SoC {slot.soc_kwh} exceeds max_soc {max_soc_kwh} without overshoot"
            )


def test_min_soc_violation_behavior_unchanged():
    """Existing soc_violation (min-SoC soft constraint) still works when initial_soc < min_soc.

    The 30-point deficit is beyond the 5-point recovery window (min-soc-recovery), so
    this stays on the deep-deficit path: min_soc is the lower bound for every state.
    """
    config = _base_config(capacity_kwh=10.0, min_soc_percent=50.0, max_soc_percent=90.0)
    # initial_soc=2.0 < min_soc_kwh=5.0 → should still solve Optimally via soft constraint
    input_data = KeplerInput(slots=_make_slots(4), initial_soc_kwh=2.0)

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal, (
        f"Min-SoC violation should be soft (Optimal), got {result.status_msg}"
    )
