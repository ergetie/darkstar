import asyncio
import yaml
import json
import ssl
from datetime import datetime

try:
    import websockets
except ImportError:
    print("Please run: pip install websockets")
    exit(1)


async def check_sum():
    with open("secrets.yaml", "r") as f:
        secrets = yaml.safe_load(f)
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    ha = secrets.get("home_assistant", {})
    base_url = ha.get("url", "").rstrip("/")
    token = ha.get("token")
    # The sensor we are currently using
    entity_id = config.get("input_sensors", {}).get("total_load_consumption")

    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
        use_ssl = True
    else:
        ws_url = base_url.replace("http://", "ws://") + "/api/websocket"
        use_ssl = False

    ssl_context = None
    if use_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    print(f"--- Auditing {entity_id} ---")
    print(f"Target Date: 2025-11-08")

    async with websockets.connect(ws_url, ssl=ssl_context) as ws:
        # Auth
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        # Fetch 24h of data
        msg = {
            "id": 1,
            "type": "recorder/statistics_during_period",
            "start_time": "2025-11-08T00:00:00Z",
            "end_time": "2025-11-09T00:00:00Z",
            "statistic_ids": [entity_id],
            "period": "hour",
        }
        await ws.send(json.dumps(msg))
        resp = json.loads(await ws.recv())

        result = resp.get("result", {}).get(entity_id, [])

        total_change = 0.0
        print(f"\n{'Hour (UTC)':<20} | {'Change (kWh)':<10} | {'Sum (Cumulative)':<15}")
        print("-" * 55)

        for p in result:
            ts = p["start"] / 1000
            dt = datetime.fromtimestamp(ts)
            change = p.get("change")
            if change is None:
                change = 0.0
            total_change += change
            print(f"{dt} | {change:<10.3f} | {p.get('sum', 0):<15.1f}")

        print("-" * 55)
        print(f"TOTAL DAILY LOAD (Calculated): {total_change:.3f} kWh")
        print(f"EXPECTED (User):              ~23.600 kWh")


if __name__ == "__main__":
    asyncio.run(check_sum())
