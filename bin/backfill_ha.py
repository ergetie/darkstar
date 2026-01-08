import asyncio
import json
import sqlite3
import ssl
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.append(str(Path.cwd()))

import pytz
import yaml

try:
    import websockets
except ImportError:
    print("Please run: pip install websockets")
    exit(1)


def load_config():
    # Assuming config.yaml is in the current working directory or script directory
    # The instruction provided `Path(config_path)` but `config_path` was not defined.
    # Using Path("config.yaml") directly as it was `open("config.yaml")` previously.
    with Path("config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_secrets():
    # Assuming secrets.yaml is in the current working directory or script directory
    with Path("secrets.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def fetch_and_backfill(start_str, end_str):
    config = load_config()
    secrets = load_secrets()
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    ha = secrets.get("home_assistant", {})
    base_url = ha.get("url", "").rstrip("/")
    token = ha.get("token")

    input_sensors = config.get("input_sensors", {}) or {}

    load_id = input_sensors.get("total_load_consumption")
    pv_id = input_sensors.get("total_pv_production")
    import_id = input_sensors.get("total_grid_import")
    export_id = input_sensors.get("total_grid_export")
    batt_charge_id = input_sensors.get("total_battery_charge")
    batt_discharge_id = input_sensors.get("total_battery_discharge")

    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://") + "/api/websocket"
        use_ssl = True
    else:
        ws_url = base_url.replace("http://", "ws://") + "/api/websocket"
        use_ssl = False

    ssl_context = ssl.create_default_context() if use_ssl else None
    if ssl_context:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    print(f"--- UTC-Corrected Backfill ({start_str} to {end_str}) ---")

    async with websockets.connect(ws_url, ssl=ssl_context) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        await ws.recv()

        target_start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        target_end_dt = datetime.strptime(end_str, "%Y-%m-%d")

        # KEY FIX: Buffer start by -1 day to capture local midnight (UTC-2 or UTC-1)
        # We fetch in UTC, but map to Local
        fetch_current = target_start_dt - timedelta(days=1)

        total_slots = 0

        # Build list of entities we will request from HA statistics
        sensor_entities = [
            ("load", load_id),
            ("pv", pv_id),
            ("import", import_id),
            ("export", export_id),
            ("batt_charge", batt_charge_id),
            ("batt_discharge", batt_discharge_id),
        ]
        statistic_ids = [entity for _, entity in sensor_entities if entity]

        while fetch_current <= target_end_dt and statistic_ids:
            chunk_end = fetch_current + timedelta(days=2)

            msg = {
                "id": int(fetch_current.timestamp()),
                "type": "recorder/statistics_during_period",
                "start_time": fetch_current.isoformat() + "Z",
                "end_time": chunk_end.isoformat() + "Z",
                "statistic_ids": statistic_ids,
                "period": "hour",
            }
            await ws.send(json.dumps(msg))
            resp = json.loads(await ws.recv())
            result = resp.get("result", {})

            updates_map = {}

            # Index mapping for updates_map values
            # 0: load_kwh, 1: pv_kwh, 2: import_kwh, 3: export_kwh,
            # 4: batt_charge_kwh, 5: batt_discharge_kwh
            index_map = {
                "load": 0,
                "pv": 1,
                "import": 2,
                "export": 3,
                "batt_charge": 4,
                "batt_discharge": 5,
            }

            # Process Sensor Data for all requested entities
            for sensor_type, entity in sensor_entities:
                if not entity:
                    continue
                points = result.get(entity, [])
                for p in points:
                    ts_ms = p["start"]
                    change = p.get("change") or 0.0

                    # Correct Timezone Handling
                    dt_utc = datetime.fromtimestamp(ts_ms / 1000, pytz.UTC)
                    dt_local = dt_utc.astimezone(tz)

                    val_15m = change / 4.0

                    for i in range(4):
                        slot_time = dt_local + timedelta(minutes=15 * i)
                        t_str = slot_time.isoformat()

                        # STRICT FILTER: Only save if this specific slot falls within target local dates
                        # This prevents overwriting previous/next day boundaries if running partials
                        if target_start_dt.date() <= slot_time.date() <= target_end_dt.date():
                            if t_str not in updates_map:
                                updates_map[t_str] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

                            idx = index_map.get(sensor_type)
                            if idx is not None:
                                updates_map[t_str][idx] = val_15m

            db_rows = []
            for t_str, values in updates_map.items():
                db_rows.append(
                    (
                        values[0],  # load_kwh
                        values[1],  # pv_kwh
                        values[2],  # import_kwh
                        values[3],  # export_kwh
                        values[4],  # batt_charge_kwh
                        values[5],  # batt_discharge_kwh
                        t_str,
                    )
                )

            if db_rows:
                with sqlite3.connect(db_path) as conn:
                    conn.executemany(
                        """
                        UPDATE slot_observations
                        SET
                            load_kwh = ?,
                            pv_kwh = ?,
                            import_kwh = ?,
                            export_kwh = ?,
                            batt_charge_kwh = ?,
                            batt_discharge_kwh = ?
                        WHERE slot_start = ?
                    """,
                        db_rows,
                    )
                    conn.commit()
                total_slots += len(db_rows)

            fetch_current += timedelta(days=1)

    print(f"Done. Correctly backfilled {total_slots} slots.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m bin.backfill_ha YYYY-MM-DD YYYY-MM-DD")
        exit(1)
    asyncio.run(fetch_and_backfill(sys.argv[1], sys.argv[2]))
