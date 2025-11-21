import os
import sys
import yaml
import json

sys.path.append(os.getcwd())


def test_voice():
    print("🧪 Testing The Voice (Rev 26)...")

    from backend.strategy.voice import get_advice

    mock_report = {
        "recommendations": {
            "dishwasher": {
                "best_grid_window": {"start": "02:00", "avg_price": 0.5},
                "best_solar_window": {"start": "11:00", "avg_pv_surplus": 2.0},
            }
        }
    }

    try:
        with open("secrets.yaml", "r") as f:
            secrets = yaml.safe_load(f)
    except Exception:
        secrets = {}

    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    print("   📞 Calling OpenRouter...")
    advice = get_advice(mock_report, config, secrets)

    print(f"\n   🤖 Advisor says:\n   '{advice}'\n")

    if "API Key missing" in advice:
        print("   ⚠️  NOTE: Test passed logic, but API Key is missing (Expected for first run).")
    elif "Advisor is disabled" in advice:
        print("   ⚠️  Advisor disabled in config.")
    else:
        print("   ✅ SUCCESS: Received AI response.")


if __name__ == "__main__":
    test_voice()
