import json
import os
import sys
import yaml

# Add project root to path
sys.path.append(os.getcwd())


def test_analyst():
    print("🧪 Testing The Analyst (Rev 25)...")

    try:
        from backend.strategy.analyst import EnergyAnalyst

        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)

        if "appliances" not in config:
            print("   ❌ FAILURE: 'appliances' section missing in config.yaml")
            return

        with open("schedule.json", "r") as f:
            schedule = json.load(f)

        analyst = EnergyAnalyst(schedule, config)
        result = analyst.analyze()

        print(json.dumps(result, indent=2))

        if "recommendations" in result and "dishwasher" in result["recommendations"]:
            print("   ✅ SUCCESS: Recommendations generated for Dishwasher.")
        else:
            print("   ❌ FAILURE: No recommendations found.")
    except Exception as e:
        print(f"   ❌ FAILURE: {e}")


if __name__ == "__main__":
    test_analyst()
