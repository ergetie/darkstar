import asyncio
import json
from datetime import datetime, timedelta

import pytz
import yaml


def load_config() -> dict:
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_secrets() -> dict:
    with open("secrets.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def probe_statistics() -> None:
    """Probe HA statistics_during_period for key inverter sensors."""
    try:
        import websockets
    except ImportError:
        print("Please install websockets: pip install websockets")
        return

    config = load_config()
    secrets = load_secrets()

    ha = secrets.get("home_assistant", {}) or {}
    base_url = (ha.get("url") or "").rstrip("/")
    token = ha.get("token")

    if not base_url or not token:
        print("Error: home_assistant url/token missing in secrets.yaml")
        return

    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    # Use the same mapping as input_sensors so we probe real entities
    sensors = config.get("input_sensors", {}) or {}
    candidates = {
        "total_load_consumption": sensors.get("total_load_consumption"),
        "total_pv_production": sensors.get("total_pv_production"),
        "total_grid_import": sensors.get("total_grid_import"),
        "total_grid_export": sensors.get("total_grid_export"),
        "total_battery_charge": sensors.get("total_battery_charge"),
        "total_battery_discharge": sensors.get("total_battery_discharge"),
        "water_heater_consumption": sensors.get("water_heater_consumption"),
    }

    # Probe a fixed historical day (can be adjusted as needed)
    # We choose a mid-summer day with known data.
    target_day = datetime(2025, 8, 1, tzinfo=tz)
    start_utc = target_day.astimezone(pytz.UTC) - timedelta(hours=1)
    end_utc = start_utc + timedelta(days=2)

    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
    else:
        ws_url = base_url.replace("http://", "ws://") + "/api/websocket"

    print(f"Connecting to {ws_url} to probe HA statistics_during_period...")

    async with websockets.connect(ws_url) as ws:
        # Handshake + auth
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        statistic_ids = [e for e in candidates.values() if e]
        if not statistic_ids:
            print("No candidate entities found in input_sensors; nothing to probe.")
            return

        msg = {
            "id": int(start_utc.timestamp()),
            "type": "recorder/statistics_during_period",
            "start_time": start_utc.isoformat().replace("+00:00", "Z"),
            "end_time": end_utc.isoformat().replace("+00:00", "Z"),
            "statistic_ids": statistic_ids,
            "period": "hour",
        }
        await ws.send(json.dumps(msg))
        raw = await ws.recv()
        resp = json.loads(raw)

        result = resp.get("result", {}) or {}
        print(f"\nProbed window (UTC): {start_utc} -> {end_utc}")
        print(f"Received statistics for {len(result.keys())} entities.")

        for canonical, entity_id in candidates.items():
            if not entity_id:
                continue
            points = result.get(entity_id)
            if not points:
                print(f"- {canonical} ({entity_id}): NO LTS points returned")
                continue

            print(f"- {canonical} ({entity_id}): {len(points)} LTS points")
            sample = points[0]
            print("  sample:", json.dumps(sample, indent=2))


if __name__ == "__main__":
    asyncio.run(probe_statistics())

