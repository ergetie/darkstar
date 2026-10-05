#!/usr/bin/env python3
"""Test comfort levels with extreme price scenarios."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta

from planner.solver.adapter import config_to_kepler_config
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerInput, KeplerInputSlot


def test_extreme_prices(comfort_level: int, scenario: str):
    """Test with extreme price scenarios."""
    config = {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 15,
            "max_soc_percent": 95,
            "nominal_voltage_v": 48.0,
            "max_charge_a": 185.0,
            "max_discharge_a": 185.0,
            "control_unit": "A",
        },
        "water_heating": {
            "enabled": True,
            "power_kw": 3.0,
            "min_kwh_per_day": 8.0,
            "comfort_level": comfort_level,
            "enable_top_ups": True,
        },
    }

    kepler_config = config_to_kepler_config(config)

    # Create price scenarios
    if scenario == "flat":
        prices = [1.5] * 192  # Flat prices
    elif scenario == "extreme_spike":
        prices = [0.5] * 192
        prices[80:88] = [10.0] * 8  # Extreme spike at hour 20-22
    elif scenario == "extreme_cheap":
        prices = [5.0] * 192
        prices[8:16] = [0.01] * 8  # Almost free at hour 2-4
    else:
        prices = [1.5] * 192

    slots: list[KeplerInputSlot] = []
    start_time = datetime.now()
    for i, price in enumerate(prices):
        s = start_time + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)
        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=1.0,
                pv_kwh=0.0,
                import_price_sek_kwh=price,
                export_price_sek_kwh=0.0,
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)

    # Solve
    solver = KeplerSolver()
    solve_start = time.time()
    result = solver.solve(input_data, kepler_config)
    solve_elapsed = time.time() - solve_start

    if not result.is_optimal:
        print(f"  ⚠️  Non-optimal: {result.status_msg}")
        return None

    # Analyze heating pattern
    water_slots = [i for i, slot in enumerate(result.slots) if slot.water_heat_kw > 0]
    if not water_slots:
        print("  ❌ No water heating scheduled")
        return None

    # Find heating blocks
    blocks = []
    current_block = [water_slots[0]]

    for slot in water_slots[1:]:
        if slot == current_block[-1] + 1:
            current_block.append(slot)
        else:
            blocks.append(current_block)
            current_block = [slot]
    blocks.append(current_block)

    print(f"  ✅ {len(blocks)} blocks, solve: {solve_elapsed:.3f}s")
    return len(blocks)


def main():
    """Test extreme price scenarios."""
    print("🔍 Testing Comfort Levels with Extreme Prices")
    print("=" * 60)

    scenarios = ["flat", "extreme_spike", "extreme_cheap"]
    levels = [1, 3, 5]

    for scenario in scenarios:
        print(f"\n=== Scenario: {scenario.upper()} ===")
        results = {}
        for level in levels:
            print(f"Level {level}:", end=" ")
            blocks = test_extreme_prices(level, scenario)
            results[level] = blocks

        # Check differentiation
        if all(results.values()):
            if len(set(results.values())) > 1:
                print(f"  ✅ Differentiation maintained: {results}")
            else:
                print(f"  ⚠️  Same behavior: {results}")


if __name__ == "__main__":
    main()
