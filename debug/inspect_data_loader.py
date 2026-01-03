import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.getcwd())

from ml.simulation.data_loader import SimulationDataLoader


def inspect_day(date_str):
    print(f"--- Inspecting {date_str} ---")
    loader = SimulationDataLoader()
    target_day = datetime.fromisoformat(date_str).date()
    start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))

    print(f"Requesting window starting: {start_dt}")

    # 1. Check Prices directly via internal method
    end_dt = start_dt + timedelta(hours=48)
    prices = loader._load_price_data(start_dt, end_dt)
    print(f"Prices found: {len(prices)} slots")
    if prices:
        print(f"  First: {prices[0]}")
        print(f"  Last:  {prices[-1]}")
    else:
        print("  NO PRICES FOUND via _load_price_data")

    # 2. Check Forecasts (Naive)
    # Check if we have observations to build forecasts from
    obs = loader._build_forecasts_from_observations(start_dt, end_dt)
    print(f"Observations for Forecast: {len(obs)} slots")

    # 3. Check HA History (if enabled)
    # This is async, so we might skip unless we want to run async code.
    # But _build_naive_forecasts calls it.

    # 4. Full get_window_inputs
    try:
        inputs = loader.get_window_inputs(start_dt)
        p_len = len(inputs.get("price_data", []))
        f_len = len(inputs.get("forecast_data", []))
        print("get_window_inputs result:")
        print(f"  Price Data: {p_len} slots")
        print(f"  Forecast Data: {f_len} slots")

        if p_len == 0:
            print("  FAIL: Price data missing in final output.")
        if f_len == 0:
            print("  FAIL: Forecast data missing in final output.")

    except Exception as e:
        print(f"get_window_inputs FAILED: {e}")


if __name__ == "__main__":
    inspect_day("2025-11-19")
    inspect_day("2025-11-20")
