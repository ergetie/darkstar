
import sys
import os
import pandas as pd
import pytz
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from archive.legacy_mpc import HeliosPlanner

def debug_planner_full():
    print("🧪 Debugging Planner Full Run...")
    
    config_path = "config.yaml"
    planner = HeliosPlanner(config_path)
    
    # Mock Data
    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0)
    
    # Mock DataFrame (48 hours)
    dates = pd.date_range(start=now, periods=48*4, freq="15min")
    df = pd.DataFrame(index=dates)
    df["import_price_sek_kwh"] = 1.0 # Flat price
    # Add a price spike tomorrow (D1)
    # Spike to 3.0 SEK (well above Terminal Value 1.5)
    spike_start = now + timedelta(days=1, hours=17) # 17:00 tomorrow
    spike_end = now + timedelta(days=1, hours=20)   # 20:00 tomorrow
    df.loc[spike_start:spike_end, "import_price_sek_kwh"] = 3.0
    df["export_price_sek_kwh"] = df["import_price_sek_kwh"]
    df["load_forecast_kwh"] = 0.5
    df["pv_forecast_kwh"] = 0.0
    
    # Mock Input Data
    input_data = {
        "price_data": [], # Not used if we mock prepare_df or pass_0
        "forecast_data": [],
        "initial_state": {"battery_kwh": 10.0, "soc_percent": 100.0}, # Start full
        "daily_pv_forecast": {},
        "daily_load_forecast": {},
        "weather_forecast": []
    }
    
    # Mock _fetch_temperature_forecast to return Cold D2 (High Risk)
    def mock_fetch_temp(days, tz):
        return {2: 0.0} # 0.0C -> Risk Factor 1.5
    planner._fetch_temperature_forecast = mock_fetch_temp
    
    # We need to run the full pipeline or at least enough to get to Kepler
    # Let's use run_kepler_primary but we need to mock _prepare_data_frame to return our df
    planner._prepare_data_frame = lambda x: df
    
    # Run Planner
    try:
        result_df = planner.run_kepler_primary(input_data)
        
        # Check Terminal Value
        print(f"Terminal Value: {planner.terminal_value_sek_kwh}")
        
        # Check SoC Target Schedule
        print("\n--- SoC Target Schedule (Next 10 slots) ---")
        print(result_df[["soc_target_percent", "action", "import_price_sek_kwh"]].head(10))
        
        # Check End of Horizon
        print("\n--- End of Horizon ---")
        print(result_df[["soc_target_percent", "action"]].tail(5))
        
        # Check if stuck at 100%
        soc_targets = result_df["soc_target_percent"].dropna()
        if (soc_targets == 100.0).all():
            print("\n❌ CRITICAL: SoC Target is stuck at 100%!")
        else:
            print("\n✅ SoC Target varies.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_planner_full()
