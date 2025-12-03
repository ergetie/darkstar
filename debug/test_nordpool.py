import sys
import yaml
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from inputs import get_nordpool_data

def main():
    print("🔍 Testing Nordpool Data Fetch...")
    
    try:
        # Fetch data
        data = get_nordpool_data("config.yaml")
        
        print(f"\n   Fetched {len(data)} slots.")
        print(f"   {'Start Time':<25} | {'End Time':<25} | {'Price (SEK/kWh)':<15}")
        print("-" * 75)
        
        # Print first 20 slots
        for i, slot in enumerate(data[:20]):
            print(f"   {slot['start_time']} | {slot['end_time']} | {slot['import_price_sek_kwh']:.4f}")
            
        # Check resolution
        if len(data) > 1:
            delta = data[1]['start_time'] - data[0]['start_time']
            print(f"\n   Detected Resolution: {delta}")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
