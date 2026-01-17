from datetime import datetime, timedelta

import pytest

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def test_kepler_solver_export_disabled():
    # 2 slots: High export prices
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Create slots with massive export incentive
    for i in range(2):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.0,
                pv_kwh=0.0,
                import_price_sek_kwh=2.0,
                export_price_sek_kwh=10.0,  # Massive incentive
            )
        )

    # Full battery to start
    input_data = KeplerInput(slots=slots, initial_soc_kwh=10.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=10.0,
        max_discharge_power_kw=10.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.0,
        enable_export=False,  # KEY: Disable export
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    for _, s in enumerate(result.slots):
        # Should be exactly 0
        assert s.grid_export_kwh == pytest.approx(0.0, abs=0.01)
        # Should NOT discharge since there is no load and we can't export
        assert s.discharge_kwh == pytest.approx(0.0, abs=0.01)
