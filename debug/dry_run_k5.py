import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from planner_legacy import HeliosPlanner
from backend.strategy.engine import StrategyEngine

# Mock Config
config_path = "config.yaml" # Assume exists
if not os.path.exists(config_path):
    # Fallback to default
    config_path = "config.default.yaml"

print(f"Using config: {config_path}")

planner = HeliosPlanner(config_path)

# Enable Kepler Primary for this test
planner.config["kepler"] = {"primary_planner": True}

# Mock Input Data
# High Volatility: 0.1 to 2.0 SEK
prices = []
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
for i in range(48): # 12 hours
    t = now + datetime.timedelta(minutes=15*i)
    # Alternating high/low to force volatility spread
    price = 0.1 if i % 2 == 0 else 2.0
    prices.append({
        "start_time": t.isoformat(),
        "end_time": (t + datetime.timedelta(minutes=15)).isoformat(),
        "import_price_sek_kwh": price,
        "export_price_sek_kwh": price
    })

input_data = {
    "price_data": prices,
    "forecast_data": [], # Empty forecast
    "initial_state": {"battery_kwh": 5.0},
    "context": {"weather_volatility": {"cloud": 0.0}}
}

# Run Strategy Engine manually to get overrides
# (In real app, main.py or api.py does this)
strategy = StrategyEngine(planner.config)
overrides = strategy.decide({"prices": prices, "context": input_data["context"]})

print("\n--- Strategy Decision ---")
print(overrides)

# Run Planner
print("\n--- Running Planner ---")
df = planner.generate_schedule(input_data, overrides=overrides, save_to_file=False)

print("\n--- Result ---")
if not df.empty:
    print(df[["kepler_charge_kwh", "kepler_discharge_kwh", "kepler_cost_sek"]].head())
else:
    print("Empty DataFrame returned.")
