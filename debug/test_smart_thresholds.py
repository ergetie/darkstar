import json
import os
import sys
import yaml

# Add project root to path
sys.path.append(os.getcwd())

from planner import HeliosPlanner
from inputs import get_all_input_data


def test_smart_expansion():
    print("🧪 Testing Smart Thresholds (Rev 20)...")

    input_data = get_all_input_data("config.yaml")

    overrides = {
        "battery": {
            "capacity_kwh": 100.0,
            "max_charge_power_kw": 10.0,
            "max_soc_percent": 100.0,
        },
        "strategic_charging": {"target_soc_percent": 100.0},
        "charging_strategy": {"charge_threshold_percentile": 5},
    }

    input_data["initial_state"]["battery_soc_percent"] = 0.0
    input_data["initial_state"]["battery_kwh"] = 0.0

    print("   📊 Scenario: Huge Battery (100kWh), Empty (0%), Strict Threshold (5%).")
    print("      Normal 5% window would be tiny (~10 slots = 25kWh).")
    print("      We expect Smart Thresholds to expand this to ~40 slots (100kWh).")

    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data, overrides=overrides)

    cheap_slots = df["is_cheap"].sum()
    charge_slots = (df["charge_kw"] > 0).sum()

    print(f"   🔍 Cheap Slots Found: {cheap_slots}")
    print(f"   ⚡ Charged Slots: {charge_slots}")

    if cheap_slots >= 35:
        print(f"   ✅ SUCCESS: Window expanded to {cheap_slots} slots!")
    else:
        print(f"   ❌ FAILURE: Window stayed small ({cheap_slots} slots). Target not met.")


if __name__ == "__main__":
    test_smart_expansion()
