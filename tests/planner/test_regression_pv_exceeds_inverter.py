"""Regression test: PV forecast exceeds inverter AC capacity causing infeasibility."""
from datetime import datetime, timedelta

from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot


def test_pv_exceeds_inverter_ac_capacity_returns_optimal():
    """dc_coupled: when pv_kwh > inverter_ac_kwh, surplus routes to battery — solver stays Optimal.

    Before fix: LP infeasible (discharge + pv <= inverter_ac becomes discharge <= negative).
    After fix (dc_coupled): surplus PV can bypass the AC stage via pv_to_battery; always feasible.
    """
    start = datetime(2025, 6, 1, 12, 0)
    slots = []

    for i in range(4):
        slots.append(
            KeplerInputSlot(
                start_time=start + timedelta(minutes=15 * i),
                end_time=start + timedelta(minutes=15 * (i + 1)),
                load_kwh=0.5,
                pv_kwh=2.1177,  # > 2.0 kWh inverter limit (8.47 kW average)
                import_price_sek_kwh=1.0,
                export_price_sek_kwh=0.4,
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_percent=10,
        max_soc_percent=100,
        wear_cost_sek_per_kwh=0.01,
        max_inverter_ac_kw=8.0,  # 8kW * 0.25h = 2.0 kWh per slot
        inverter_topology="dc_coupled",
        curtailment_penalty_sek=0.5,  # incentivise routing surplus to battery over curtailment
        enable_export=True,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal, f"Expected Optimal, got {result.status_msg}"

    # Surplus PV (0.1177 kWh/slot) should route to battery, not be lost
    total_charge = sum(s.charge_kwh for s in result.slots)
    assert total_charge > 0.3, (
        f"Expected surplus PV to charge battery (>=0.3 kWh total), got {total_charge}"
    )
