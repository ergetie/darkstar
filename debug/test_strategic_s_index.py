
import sys
import os
import pandas as pd
import pytz
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from planner_legacy import HeliosPlanner
from backend.kepler.types import KeplerConfig

def test_strategic_s_index():
    print("🧪 Testing Strategic S-Index & Terminal Value...")
    
    # Mock Config
    config_path = "config.yaml"
    planner = HeliosPlanner(config_path)
    
    # Override S-Index config for testing
    planner.config["s_index"] = {
        "base_factor": 1.1,
        "max_factor": 1.5,
        "mode": "dynamic",
        "s_index_horizon_days": 4, # New Config
        "temp_weight": 0.5,
        "temp_baseline_c": 10.0,
        "temp_cold_c": 0.0
    }
    
    # Mock Data
    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz)
    
    # Mock DataFrame (D0+D1)
    dates = pd.date_range(start=now, periods=48, freq="15min")
    df = pd.DataFrame(index=dates)
    df["import_price_sek_kwh"] = 1.0 # Constant price for easy math
    df["load_forecast_kwh"] = 1.0
    df["pv_forecast_kwh"] = 0.0
    
    # Mock D2 Temperature Forecast (Cold -> High Risk)
    # We mock _fetch_temperature_forecast to return 0.0C (Cold limit)
    # With baseline 10.0 and cold 0.0, 0.0C should give adjustment = 1.0
    # Risk Factor = Base(1.1) + Weight(0.5)*1.0 = 1.6 -> Capped at Max(1.5)
    def mock_fetch_temp(days, tz):
        return {2: 0.0}
    planner._fetch_temperature_forecast = mock_fetch_temp
    
    # Run _pass_0 (where logic resides)
    print("\n--- Running _pass_0 ---")
    df = planner._pass_0_apply_safety_margins(df)
    
    # Verify Debug Data
    debug = getattr(planner, "s_index_debug", {})
    print(f"S-Index Debug: {debug}")
    
    # Check Future Risk
    risk_debug = debug.get("future_risk", {})
    risk_factor = risk_debug.get("risk_factor")
    print(f"Risk Factor (Expected 1.5): {risk_factor}")
    
    if risk_factor != 1.5:
        print("❌ Risk Factor Calculation Failed!")
    else:
        print("✅ Risk Factor Calculation Correct (Capped at Max)")
        
    # Check Terminal Value
    # Avg Price = 1.0. Terminal Value = 1.0 * 1.5 = 1.5
    term_debug = debug.get("terminal_value", {})
    term_val = term_debug.get("terminal_value_sek_kwh")
    print(f"Terminal Value (Expected 1.5): {term_val}")
    
    if term_val != 1.5:
        print("❌ Terminal Value Calculation Failed!")
    else:
        print("✅ Terminal Value Calculation Correct")
        
    # Check Injection into KeplerConfig
    # We simulate what run_kepler_primary does
    from backend.kepler.adapter import config_to_kepler_config
    k_config = config_to_kepler_config(planner.config)
    k_config.terminal_value_sek_kwh = getattr(planner, "terminal_value_sek_kwh", 0.0)
    
    print(f"KeplerConfig Terminal Value: {k_config.terminal_value_sek_kwh}")
    
    if k_config.terminal_value_sek_kwh == 1.5:
        print("✅ Kepler Config Injection Correct")
    else:
        print("❌ Kepler Config Injection Failed!")

if __name__ == "__main__":
    test_strategic_s_index()
