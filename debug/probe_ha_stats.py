import yaml
import requests
import json
from datetime import datetime

# Load secrets
try:
    with open("secrets.yaml", "r") as f:
        secrets = yaml.safe_load(f)
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"Error loading config/secrets: {e}")
    exit(1)

ha = secrets.get("home_assistant", {})
url = ha.get("url")
token = ha.get("token")

# Use sensors from config
sensors = config.get("input_sensors", {})
# Note: LTS usually requires the cumulative entity (kWh), not power (W)
# We will try the load entity defined in config
entity_id = sensors.get("total_load_consumption")
#entity_id = sensors.get("total_grid_import")
#entity_id = sensors.get("total_grid_export")
#entity_id = sensors.get("total_battery_charge")
#entity_id = sensors.get("total_battery_discharge")


print(f"--- Probing HA Statistics for {entity_id} ---")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}

# Target: Aug 1st 2025
start = "2025-08-01T00:00:00Z"
end = "2025-08-02T00:00:00Z"

# LTS Endpoint (period=hour is standard for long term)
api_url = f"{url}/api/history/statistics_during_period"
params = {
    "start_time": start,
    "end_time": end,
    "statistic_ids": [entity_id],
    "period": "hour"
}

try:
    res = requests.get(api_url, headers=headers, params=params, timeout=10)
    if res.status_code == 200:
        data = res.json()
        print(f"Status: {res.status_code}")
        if entity_id in data:
            points = data[entity_id]
            print(f"Found {len(points)} data points.")
            if points:
                print("First point structure:")
                print(json.dumps(points[0], indent=2))
        else:
            print("Response valid but entity not found in stats.")
            print("Keys found:", list(data.keys()))
    else:
        print(f"Failed: {res.status_code} - {res.text}")
except Exception as e:
    print(f"Request failed: {e}")
