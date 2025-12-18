import asyncio
import yaml
import json
import ssl

try:
    import websockets
except ImportError:
    print("Please run: pip install websockets")
    exit(1)

# Load Config
with open("secrets.yaml", "r") as f:
    secrets = yaml.safe_load(f)
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

ha = secrets.get("home_assistant", {})
base_url = ha.get("url", "").rstrip("/")
token = ha.get("token")
# Explicitly using the sensor you confirmed
entity_id = "sensor.inverter_total_load_consumption"

# Convert HTTP to WS
if base_url.startswith("https://"):
    ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
    use_ssl = True
else:
    ws_url = base_url.replace("http://", "ws://") + "/api/websocket"
    use_ssl = False

print(f"Connecting to {ws_url}...")


async def fetch_stats():
    # Only create SSL context if needed
    ssl_context = None
    if use_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    async with websockets.connect(ws_url, ssl=ssl_context) as websocket:
        # 1. Auth Phase
        auth_req = await websocket.recv()
        await websocket.send(json.dumps({"type": "auth", "access_token": token}))
        auth_resp = await websocket.recv()
        auth_data = json.loads(auth_resp)

        if auth_data.get("type") != "auth_ok":
            print(f"Auth Failed: {auth_data}")
            return

        print("Auth Success.")

        # 2. Request Statistics (LTS)
        # We ask for 'sum' (cumulative kWh) or 'mean' (power W)
        # Since this is 'consumption', we likely want 'sum' to calculate deltas later
        req_id = 2
        msg = {
            "id": req_id,
            "type": "recorder/statistics_during_period",
            "start_time": "2025-08-01T00:00:00Z",
            "end_time": "2025-08-02T00:00:00Z",
            "statistic_ids": [entity_id],
            "period": "hour",
        }
        await websocket.send(json.dumps(msg))

        # 3. Receive Data
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            if data.get("id") == req_id:
                result = data.get("result", {})
                points = result.get(entity_id, [])
                print(f"--- Result for {entity_id} ---")
                print(f"Found {len(points)} data points (Hourly).")
                if points:
                    print("First point sample:")
                    print(json.dumps(points[0], indent=2))
                else:
                    print("No data found. Check if this sensor has 'state_class' defined in HA.")
                break


if __name__ == "__main__":
    asyncio.run(fetch_stats())
