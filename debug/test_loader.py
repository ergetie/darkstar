import sys
import os
from datetime import datetime
import pytz

# Add project root to path
sys.path.append(os.getcwd())

from ml.simulation.data_loader import SimulationDataLoader

def main():
    loader = SimulationDataLoader()
    tz = pytz.timezone("Europe/Stockholm")
    
    # Test Nov 10
    start = tz.localize(datetime(2025, 11, 10, 0, 0, 0))
    
    print(f"Testing loader for {start}...")
    inputs = loader.get_window_inputs(start, horizon_hours=24)
    
    forecasts = inputs.get("forecast_data", [])
    print(f"Got {len(forecasts)} forecast slots.")
    
    if forecasts:
        print("First 5 slots:")
        for f in forecasts[:5]:
            print(f"  {f['start_time']} -> Load: {f.get('load_forecast_kwh')} PV: {f.get('pv_forecast_kwh')}")
            
    # Check naive specifically
    print("\nChecking naive forecasts directly...")
    from datetime import timedelta
    end = start + timedelta(hours=24)
    naive = loader._build_naive_forecasts(start, end)
    print(f"Got {len(naive)} naive slots.")
    if naive:
        print("First 5 naive slots:")
        for f in naive[:5]:
            print(f"  {f['start_time']} -> Load: {f.get('load_forecast_kwh')} PV: {f.get('pv_forecast_kwh')}")

if __name__ == "__main__":
    main()
