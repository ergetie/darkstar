#!/usr/bin/env python3
"""Test bulk mode override (enable_top_ups=false)."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta

from planner.solver.adapter import config_to_kepler_config
from planner.solver.kepler import KeplerSolver
from planner.solver.types import KeplerInput, KeplerInputSlot


def test_bulk_mode(comfort_level: int, enable_top_ups: bool):
    """Test water heating with bulk mode override."""
    # Create test config
    config = {
        "battery": {
            "capacity_kwh": 10.0,
            "min_soc_percent": 15,
            "max_soc_percent": 95,
            "max_charge_power_kw": 5.0,
            "max_discharge_power_kw": 5.0,
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
            "enable_top_ups": enable_top_ups,
        },
    }

    kepler_config = config_to_kepler_config(config)

    print(f"Comfort Level {comfort_level}, enable_top_ups={enable_top_ups}")
    print(f"  max_block_hours: {kepler_config.max_block_hours:.2f}h")
    print(f"  water_block_penalty_sek: {kepler_config.water_block_penalty_sek:.2f}")
    print(f"  water_reliability_penalty_sek: {kepler_config.water_reliability_penalty_sek:.2f}")

    # Create 48h of slots with varying prices
    prices = [1.5] * 192  # Flat prices to isolate bulk mode behavior
    prices[8:16] = [0.5] * 8  # Cheap period at hour 2-4
    prices[104:112] = [0.5] * 8  # Cheap period at hour 26-28

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
        print(f"  ❌ Solver failed: {result.status_msg}")
        return None

    # Analyze heating pattern
    water_slots = [i for i, slot in enumerate(result.slots) if slot.water_heat_kw > 0]
    if not water_slots:
        print("  ❌ No water heating scheduled")
        return None

    # Find heating blocks
    blocks: list[list[int]] = []
    current_block: list[int] = [water_slots[0]]

    for slot in water_slots[1:]:
        if slot == current_block[-1] + 1:
            current_block.append(slot)
        else:
            blocks.append(current_block)
            current_block = [slot]
    blocks.append(current_block)

    print(f"  ✅ Heating blocks: {len(blocks)} blocks (solve: {solve_elapsed:.2f}s)")
    for i, block in enumerate(blocks):
        start_hour = block[0] // 4
        end_hour = block[-1] // 4
        duration = len(block) * 0.25
        print(
            f"     Block {i + 1}: Hours {start_hour:02d}-{end_hour:02d} ({duration:.2f}h, {len(block)} slots)"
        )

    return len(blocks)


def main():
    """Test bulk mode override."""
    print("🔍 Testing Bulk Mode Override (enable_top_ups)")
    print("=" * 60)

    # Test Level 5 with and without bulk mode
    print("\n=== Level 5 (Maximum Comfort) with enable_top_ups=True ===")
    blocks_normal = test_bulk_mode(5, True)

    print("\n=== Level 5 (Maximum Comfort) with enable_top_ups=False (BULK) ===")
    blocks_bulk = test_bulk_mode(5, False)

    print("\n" + "=" * 60)
    print("📊 RESULTS")
    print("=" * 60)
    if blocks_normal and blocks_bulk:
        print(f"Level 5 + enable_top_ups=True:  {blocks_normal} blocks (frequent heating)")
        print(f"Level 5 + enable_top_ups=False: {blocks_bulk} blocks (bulk heating)")

        if blocks_bulk < blocks_normal:
            print("✅ Bulk mode override working correctly!")
        else:
            print("❌ Bulk mode override NOT working - same or more blocks!")
    else:
        print("❌ Test failed")


if __name__ == "__main__":
    main()
