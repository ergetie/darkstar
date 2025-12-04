import sys
import os
import json
import yaml

# Add project root to path
sys.path.append(os.getcwd())

from planner_legacy import HeliosPlanner
from inputs import get_all_input_data


def test_overrides():
    print("🧪 Testing Planner Strategy Injection (Rev 18)...")

    # 1. Load Real Data
    print("   Fetching inputs...")
    input_data = get_all_input_data("config.yaml")

    # 2. Define a Drastic Override
    # We override 'strategic_charging.target_soc_percent' to 99%.
    # This forces Pass 4 (Responsibility) to allocate charging to reach 99%.
    overrides = {
        "strategic_charging": {
            "target_soc_percent": 99.0,
            "price_threshold_sek": 99.0,  # Force it to be considered 'cheap' enough
        },
        # Also override battery capacity to something tiny to ensure we can fill it fast
        # just in case the window is short (though 99% target usually works).
        "forecasting": {"pv_confidence_percent": 0.0},  # Force strategic mode (Low PV)
    }
    print(f"   💉 Injecting Override: {json.dumps(overrides)}")

    # 3. Run Planner
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data, overrides=overrides)

    # 4. Verify
    # Look for the max projected SoC. It should aim for ~99%.
    # We allow a small margin (e.g. 98%) due to efficiency losses or time constraints.
    max_target_observed = df["soc_target_percent"].max()
    print(f"   🔍 Max SoC Target in Schedule: {max_target_observed}%")

    if max_target_observed >= 98.0:
        print("   ✅ SUCCESS: Planner respected the override!")
    else:
        print(
            f"   ❌ FAILURE: Planner ignored override (Expected >= 98.0, Got {max_target_observed})"
        )


if __name__ == "__main__":
    test_overrides()
