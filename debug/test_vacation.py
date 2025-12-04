import json
import os
import sys
import yaml

# Add project root to path
sys.path.append(os.getcwd())

from backend.strategy.engine import StrategyEngine
from inputs import get_all_input_data
from planner_legacy import HeliosPlanner


def test_vacation_strategy():
    print("🧪 Testing Aurora v2 Vacation Strategy...")

    # 1. Get Real Data
    print("   Fetching inputs...")
    input_data = get_all_input_data("config.yaml")

    # 2. Hack the Context to simulate Vacation
    print("   🕵️‍♀️ Simulating 'Vacation Mode = True'...")
    input_data["context"] = {
        "vacation_mode": True,
        "alarm_armed": False,
    }

    # 3. Run Strategy Engine
    with open("config.yaml", "r") as f:
        base_config = yaml.safe_load(f)

    engine = StrategyEngine(base_config)
    overrides = engine.decide(input_data)

    print(f"   🧠 Strategy Output: {json.dumps(overrides, indent=2)}")

    # 4. Verify Logic
    wh_override = overrides.get("water_heating", {})
    if wh_override.get("min_hours_per_day") == 0.0:
        print("   ✅ SUCCESS: Strategy correctly disabled water heating.")
    else:
        print("   ❌ FAILURE: Strategy did NOT disable water heating.")
        return

    # 5. Run Planner (Optional check)
    print("   🏃 Running Planner with Strategy...")
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data, overrides=overrides)

    total_water_kw = df["water_heating_kw"].sum()
    print(f"   🚿 Total Water Heating Scheduled: {total_water_kw} kW")

    if total_water_kw == 0.0:
        print("   ✅ SUCCESS: Planner scheduled ZERO water heating slots.")
    else:
        print(f"   ❌ FAILURE: Planner scheduled {total_water_kw} kW (Expected 0).")


if __name__ == "__main__":
    test_vacation_strategy()
