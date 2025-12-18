import pytest
from datetime import datetime, timedelta
from backend.kepler.types import KeplerConfig, KeplerInputSlot, KeplerInput
from backend.kepler.solver import KeplerSolver


def test_kepler_solver_basic():
    # Create a simple 2-slot scenario
    start = datetime(2025, 1, 1, 12, 0)
    slots = []
    for i in range(2):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=1.0,  # 1 kWh load
                pv_kwh=0.0,
                import_price_sek_kwh=1.0,  # Expensive import
                export_price_sek_kwh=0.0,  # Worthless export
            )
        )

    # Initial battery: 5 kWh (50% of 10kWh)
    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.01,  # Small wear cost to prevent free dumping
        target_soc_kwh=0.0,  # Allow depletion
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal
    assert len(result.slots) == 2

    # Check that it discharged to cover load (since import is expensive)
    # Total load = 2 kWh. Initial battery = 5 kWh.
    # Should discharge 2 kWh.
    total_discharge = sum(s.discharge_kwh for s in result.slots)
    total_import = sum(s.grid_import_kwh for s in result.slots)

    print(f"Total Discharge: {total_discharge}")
    print(f"Total Import: {total_import}")

    assert total_discharge == pytest.approx(2.0, abs=0.01)

    # Check that import is 0
    assert total_import == pytest.approx(0.0, abs=0.01)


def test_kepler_solver_arbitrage():
    # 2 slots: Cheap import, then Expensive export
    start = datetime(2025, 1, 1, 12, 0)
    slots = []

    # Slot 0: Cheap import (0.1 SEK), High export (0.05 SEK) - Charge
    slots.append(
        KeplerInputSlot(
            start_time=start,
            end_time=start + timedelta(minutes=15),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=0.1,
            export_price_sek_kwh=0.05,
        )
    )

    # Slot 1: Expensive import (2.0 SEK), High export (1.5 SEK) - Discharge/Export
    slots.append(
        KeplerInputSlot(
            start_time=start + timedelta(minutes=15),
            end_time=start + timedelta(minutes=30),
            load_kwh=0.0,
            pv_kwh=0.0,
            import_price_sek_kwh=2.0,
            export_price_sek_kwh=1.5,
        )
    )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=0.0)  # Empty battery

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=4.0,  # 1 kWh per 15 min
        max_discharge_power_kw=4.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        min_soc_percent=0.0,
        max_soc_percent=100.0,
        wear_cost_sek_per_kwh=0.0,
    )

    solver = KeplerSolver()
    result = solver.solve(input_data, config)

    assert result.is_optimal

    # Slot 0: Should charge max (1 kWh)
    assert result.slots[0].charge_kwh == pytest.approx(1.0, abs=0.01)

    # Slot 1: Should export max (1 kWh)
    assert result.slots[1].discharge_kwh == pytest.approx(1.0, abs=0.01)
    assert result.slots[1].grid_export_kwh == pytest.approx(1.0, abs=0.01)
