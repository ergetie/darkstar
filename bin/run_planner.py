import os
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent.resolve()))

import yaml

from inputs import get_all_input_data
from planner.pipeline import generate_schedule


def load_yaml(path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def get_version_string():
    # Try git describe, fallback to env or static string
    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always"], stderr=subprocess.DEVNULL
        )
        return out.decode("utf-8").strip()
    except Exception:
        return os.environ.get("DARKSTAR_VERSION", "dev")


def main():
    config = load_yaml("config.yaml")
    automation = config.get("automation", {})
    if not automation.get("enable_scheduler", False):
        print("[planner] Scheduler disabled by config. Exiting.")
        return 0

    # Build inputs and run planner
    input_data = get_all_input_data("config.yaml")

    # Persist inputs to Learning DB (Prices & Forecasts)
    try:
        from backend.learning import LearningEngine

        engine = LearningEngine("config.yaml")

        if "price_data" in input_data:
            engine.store_slot_prices(input_data["price_data"])
            print(f"[planner] Stored {len(input_data['price_data'])} price slots to DB")

        if "forecast_data" in input_data:
            # Forecasts need a version, default to 'aurora' or 'baseline'
            # We can get it from config or default
            f_ver = config.get("forecasting", {}).get("active_forecast_version", "aurora")
            engine.store_forecasts(input_data["forecast_data"], forecast_version=f_ver)
            print(f"[planner] Stored {len(input_data['forecast_data'])} forecast slots to DB")

    except Exception as e:
        print(f"[planner] Warning: Failed to persist inputs to DB: {e}")

    # Run Planner Pipeline
    # This will generate and save schedule.json
    generate_schedule(input_data, config=config, mode="full", save_to_file=True)

    schedule_path = "schedule.json"
    print(f"[planner] Wrote schedule to {schedule_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
