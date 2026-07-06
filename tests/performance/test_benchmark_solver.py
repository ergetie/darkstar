import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(str(Path.cwd()))
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot, WaterHeaterInput

# Reduce logging noise from other modules
logging.getLogger("pulp").setLevel(logging.WARNING)


def test_benchmark_solver_48h():
    """
    Benchmark the solver with a 48h horizon (192 slots).
    This simulates a realistic generic production scenario.
    """
    start = datetime(2025, 1, 1, 0, 0)
    slots = []

    # Generate 192 slots (48 hours * 4 slots/hour)
    for i in range(192):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)

        # Simple cyclic price pattern
        hour = s.hour
        is_high_price = 7 <= hour <= 20
        import_price = 2.0 if is_high_price else 0.5
        export_price = import_price - 0.1

        # Cyclic load pattern (peak evening)
        is_peak_load = 17 <= hour <= 21
        load = 1.0 if is_peak_load else 0.2

        # Cyclic PV pattern (daytime)
        is_sunny = 10 <= hour <= 15
        pv = 2.0 if is_sunny else 0.0

        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=load / 4,  # kW -> kWh
                pv_kwh=pv / 4,  # kW -> kWh
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=export_price,
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    config = KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        wear_cost_sek_per_kwh=0.05,
        # Enable water heating to stress tests (per-device config)
        water_heaters=[
            WaterHeaterInput(
                id="wh1",
                power_kw=3.0,
                min_kwh_per_day=5.0,
                max_hours_between_heating=12.0,
                min_spacing_hours=4.0,
            )
        ],
        water_heating_max_gap_hours=12.0,
    )

    print("\n--- BENCHMARK START (192 slots) ---")
    solver = KeplerSolver()
    result = solver.solve(input_data, config)
    print("--- BENCHMARK END ---")

    assert result.is_optimal
    assert len(result.slots) == 192
