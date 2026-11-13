"""Regression test: max_soc infeasibility incident (capacity=19.2, initial_soc=18.989)."""

from datetime import datetime, timedelta

import pytest

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def _make_slots(
    n: int, import_price: float = 1.0, export_price: float = 0.4
) -> list[KeplerInputSlot]:
    start = datetime(2025, 6, 1, 10, 0)
    slots = []
    for i in range(n):
        s = start + timedelta(hours=i)
        e = s + timedelta(hours=1)
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=0.8,
                pv_kwh=0.3,
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )
    return slots


def test_production_incident_max_soc_infeasibility():
    """Reproduce the reported incident: capacity=19.2, max_soc_percent=95, initial_soc=18.989.

    Before fix: LP infeasible (initial_soc=18.989 > max_soc_kwh=18.24).
    After fix: Optimal, plan discharges in first slots.
    """
    config = KeplerConfig(
        capacity_kwh=19.2,
        min_soc_percent=15,
        max_soc_percent=95,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.01,
        target_soc_kwh=None,
    )

    max_soc_kwh = 19.2 * 0.95  # 18.24
    initial_soc = 18.989  # > max_soc_kwh → old code: infeasible

    input_data = KeplerInput(slots=_make_slots(8), initial_soc_kwh=initial_soc)

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal, f"Expected Optimal, got {result.status_msg}"

    # First slot should discharge or export to bring SoC down
    slot0 = result.slots[0]
    assert slot0.discharge_kwh > 0 or slot0.grid_export_kwh > 0, (
        "Expected discharge or export in first slot to reduce overshoot"
    )

    # SoC should drop below max_soc_kwh within the first 2 hours (2 slots)
    soc_dropped = False
    for slot in result.slots[:2]:
        if slot.soc_kwh is not None and slot.soc_kwh < max_soc_kwh:
            soc_dropped = True
            break
    assert soc_dropped, (
        f"SoC should drop below {max_soc_kwh} kWh within first 2 hours, "
        f"but SoC values: {[s.soc_kwh for s in result.slots[:2]]}"
    )
