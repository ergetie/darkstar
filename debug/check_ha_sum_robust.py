import asyncio
import yaml
import json
import ssl
from datetime import datetime, timedelta
import pytz

try:
    import websockets
except ImportError:
    print("Please run: pip install websockets")
    exit(1)

async def check_sum_robust():
    with open("secrets.yaml", "r") as f:
        secrets = yaml.safe_load(f)
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    ha = secrets.get("home_assistant", {})
    base_url = ha.get("url", "").rstrip("/")
    token = ha.get("token")
    entity_id = config.get("input_sensors", {}).get("total_load_consumption")
    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

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

    target_date_str = "2025-11-01"
    print(f"--- Robust Audit for {entity_id} on {target_date_str} ---")

    async with websockets.connect(ws_url, ssl=ssl_context) as ws:
        # Auth
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        # Fetch buffer around the date (UTC)
        # We want Nov 1st Local. That is roughly Oct 31 22:00 UTC to Nov 1 23:00 UTC.
        # Let's grab 48 hours to be safe.
        start_fetch = "2025-10-31T12:00:00Z"
        end_fetch = "2025-11-02T12:00:00Z"

        msg = {
            "id": 1,
            "type": "recorder/statistics_during_period",
            "start_time": start_fetch,
            "end_time": end_fetch,
            "statistic_ids": [entity_id],
            "period": "hour"
        }
        await ws.send(json.dumps(msg))
        resp = json.loads(await ws.recv())
        result = resp.get("result", {}).get(entity_id, [])

        # Find Start/End Cumulative Values for the Local Day
        target_day = datetime.strptime(target_date_str, "%Y-%m-%d").date()

        start_sum = None
        end_sum = None

        print(f"{'Local Time':<25} | {'Sum':<15}")
        print("-" * 45)

        for p in result:
            ts = p['start'] / 1000
            dt_utc = datetime.fromtimestamp(ts, pytz.UTC)
            dt_local = dt_utc.astimezone(tz)

            cumulative = p.get('sum')

            # Print entries around midnight
            if dt_local.date() == target_day or dt_local.date() == target_day + timedelta(days=1):
                 # Show hours 23, 00, 01 to spot the transition
                 if dt_local.hour in [0, 1, 23]:
                     print(f"{str(dt_local):<25} | {cumulative:<15}")

            # Capture Midnight Start
            if dt_local.date() == target_day and dt_local.hour == 0:
                start_sum = cumulative

            # Capture Midnight End (Start of next day)
            if dt_local.date() == target_day + timedelta(days=1) and dt_local.hour == 0:
                end_sum = cumulative

        print("-" * 45)
        if start_sum is not None and end_sum is not None:
            diff = end_sum - start_sum
            print(f"Start Sum (00:00): {start_sum}")
            print(f"End Sum   (00:00): {end_sum}")
            print(f"ROBUST DAILY LOAD: {diff:.3f} kWh")
            print(f"EXPECTED (User):   ~34.700 kWh")
        else:
            print("Could not find exact midnight alignment.")

if __name__ == "__main__":
    asyncio.run(check_sum_robust())
