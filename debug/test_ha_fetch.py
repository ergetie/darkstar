import asyncio
import sys
import os
from datetime import datetime, timedelta
import pytz

# Add project root to path
sys.path.append(os.getcwd())

from ml.simulation.ha_client import HomeAssistantHistoryClient

async def test_fetch():
    print("Testing HA History Fetch...")
    client = HomeAssistantHistoryClient()
    
    if not client.enabled:
        print("HA Client is DISABLED (missing URL/Token in env or config?)")
        return

    # Test period (Nov 26 gap)
    tz = pytz.timezone("Europe/Stockholm")
    start = tz.localize(datetime(2025, 11, 26, 6, 0, 0))
    end = tz.localize(datetime(2025, 11, 26, 7, 30, 0))
    
    # Entity ID from config
    entity_id = "sensor.inverter_total_load_consumption" 
    
    print(f"Fetching {entity_id} from {start} to {end}...")
    
    try:
        history = await client.fetch_statistics(entity_id, start, end)
        print(f"Received {len(history)} data points.")
        if history:
            print("Sample:", history[0])
        else:
            print("No data returned.")
            
    except Exception as e:
        print(f"Fetch FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_fetch())
