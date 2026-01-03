import time
import yaml
import logging
import os
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytz

# Local imports
from backend.learning.store import LearningStore
from inputs import get_home_assistant_sensor_float
from backend.learning.backfill import BackfillEngine

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger("recorder")

def _load_config():
    try:
        with open("config.yaml", "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

def record_observation_from_current_state():
    """Capture current system state and store as an observation."""
    config = _load_config()
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)
    
    store = LearningStore(db_path, tz)
    
    # Identify the just-finished slot (or current instant)
    now = datetime.now(tz)
    # Round down to nearest 15 min
    minute_block = (now.minute // 15) * 15
    slot_start = now.replace(minute=minute_block, second=0, microsecond=0)
    slot_end = slot_start + timedelta(minutes=15)
    
    # Gather Data
    input_sensors = config.get("input_sensors", {})
    
    # Helper to get sensor value and convert W to kW if needed
    def get_kw(key, default=0.0):
        entity = input_sensors.get(key)
        if not entity: return default
        val = get_home_assistant_sensor_float(entity)
        if val is None: return default
        # Assume sensors are in Watts if > 100? Or just assume Watts?
        # Usually HA power sensors are W.
        return val / 1000.0

    # Current Power State (Snapshot)
    pv_kw = get_kw("pv_power")
    load_kw = get_kw("load_power")
    import_kw = get_kw("grid_import_power")
    export_kw = get_kw("grid_export_power")
    
    # Estimate Energy for the 15m slot (kWh = avg_kW * 0.25h)
    # This is a Rough Approximation if we don't have cumulative counters
    # ideally we would diff cumulative counters.
    # For now, we store the snapshot rate converted to energy.
    pv_kwh = pv_kw * 0.25
    load_kwh = load_kw * 0.25
    import_kwh = import_kw * 0.25
    export_kwh = export_kw * 0.25
    
    # Battery
    soc_entity = input_sensors.get("battery_soc")
    if soc_entity:
        soc_percent = get_home_assistant_sensor_float(soc_entity) or 0.0
    else:
        soc_percent = 0.0
        
    # Construct Record
    record = {
        "slot_start": slot_start,
        "slot_end": slot_end,
        "pv_kwh": pv_kwh,
        "load_kwh": load_kwh,
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "soc_end_percent": soc_percent,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    logger.info(f"Recording observation for {slot_start}: SOC={soc_percent}% PV={pv_kwh:.3f}kWh Load={load_kwh:.3f}kWh")
    
    # Store
    df = pd.DataFrame([record])
    store.store_slot_observations(df)

def _sleep_until_next_quarter() -> None:
    """Sleep until the next 15-minute boundary (UTC-based)."""
    now = datetime.now(timezone.utc)
    minute_block = (now.minute // 15) * 15
    current_slot = now.replace(minute=minute_block, second=0, microsecond=0)
    next_slot = current_slot + timedelta(minutes=15)
    sleep_seconds = max(5.0, (next_slot - now).total_seconds())
    time.sleep(sleep_seconds)


def _run_analyst() -> None:
    """Run the Learning Analyst to update s_index_base_factor and bias adjustments."""
    try:
        from backend.learning.analyst import Analyst
        config = _load_config()
        print("[recorder] Running Analyst (Learning Loop)...")
        analyst = Analyst(config)
        analyst.update_learning_overlays()
    except Exception as e:
        print(f"[recorder] Analyst failed: {e}")


def main() -> int:
    """Background recorder loop: capture observations every 15 minutes."""
    print("[recorder] Starting live observation recorder (15m cadence)")

    config = _load_config()
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    # Run backfill on startup
    try:
        print("[recorder] Running startup backfill...")
        backfill = BackfillEngine()
        backfill.run()
    except Exception as e:
        print(f"[recorder] Backfill failed: {e}")

    # Run Analyst on startup
    _run_analyst()

    # Track last analyst run date to run once daily at ~6 AM local
    last_analyst_date = datetime.now(tz).date()

    while True:
        try:
            record_observation_from_current_state()
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[recorder] Error while recording observation: {exc}")

        # Run Analyst once per day around 6 AM local time
        now_local = datetime.now(tz)
        if now_local.date() > last_analyst_date and now_local.hour >= 6:
            print(f"[recorder] Daily Analyst run triggered ({now_local.date()})")
            _run_analyst()
            last_analyst_date = now_local.date()

        _sleep_until_next_quarter()


if __name__ == "__main__":
    raise SystemExit(main())
