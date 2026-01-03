import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pytz
from fastapi import APIRouter

# Local imports (using absolute paths relative to project root)
from inputs import _load_yaml, get_nordpool_data

# executor/history needs access
# We might need to adjust python path in dev-backend.sh if not matching
# But usually PYTHONPATH=. handles it.

logger = logging.getLogger("darkstar.api.schedule")
router = APIRouter(tags=["schedule"])


def _get_executor() -> Any | None:
    """Helper to get executor instance. Delegating to executor router singleton."""
    from backend.api.routers.executor import _get_executor as get_exec

    return get_exec()


@router.get("/api/scheduler/status")
async def get_scheduler_status():
    """Get scheduler status (is it running, last run, etc)."""
    try:
        status_path = "data/scheduler_status.json"
        if os.path.exists(status_path):
            with open(status_path) as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read scheduler status: {e}")

    return {
        "running": False,
        "last_run": None,
        "next_run": None,
        "status": "idle",
        "error": "Status file not found",
    }


@router.get("/api/schedule")
async def get_schedule():
    """Return the current active schedule.json with price overlay."""
    try:
        with open("schedule.json") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"schedule": [], "meta": {}}

    # Add price overlay
    if "schedule" in data:
        price_map = {}
        try:
            # We assume config.yaml is in root
            price_slots = get_nordpool_data("config.yaml")
            tz = pytz.timezone("Europe/Stockholm")  # Default fallback
            # Try to read timezone from config?
            # get_nordpool_data reads config, but we need timezone to normalize execution

            for p in price_slots:
                st = p["start_time"]
                # Normalization logic
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get("import_price_sek_kwh") or 0.0)
        except Exception as exc:
            logger.warning("Price overlay unavailable: %s", exc)

        for slot in data["schedule"]:
            if "import_price_sek_kwh" not in slot:
                try:
                    start_str = slot.get("start_time")
                    if start_str:
                        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                        # Similar normalization
                        local_naive = (
                            start
                            if start.tzinfo is None
                            else start.astimezone(tz).replace(tzinfo=None)
                        )
                        price = price_map.get(local_naive)
                        if price is not None:
                            slot["import_price_sek_kwh"] = round(price, 4)
                except Exception:
                    pass
    return _clean_nans(data)


# ... Porting schedule_today_with_history ...
# This logic is complex (merging SQLite, MariaDB, and Schedule).
# I will port it carefully.


@router.get("/api/schedule/today_with_history")
async def schedule_today_with_history():
    """Merged view of today's schedule and execution history."""
    try:
        config = _load_yaml("config.yaml")
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Stockholm")

    today_local = datetime.now(tz).date()

    # 1. Load schedule.json
    schedule_map = {}
    try:
        with open("schedule.json") as f:
            payload = json.load(f)
        for slot in payload.get("schedule", []):
            start_str = slot.get("start_time")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                local = tz.localize(start) if start.tzinfo is None else start.astimezone(tz)
                if local.date() != today_local:
                    continue
                schedule_map[local.replace(tzinfo=None)] = slot
            except Exception:
                continue
    except Exception:
        pass

    # 2. Load History (SQLite)
    # We can instantiate ExecutionHistory directly to read (it's SQLite)
    exec_map = {}
    try:
        # We need the path to planner_learning.db
        # In config?
        db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
        # History class expects the db_path via some mechanism or we just use raw SQL here for simplicity
        # reusing logic from webapp.py
        import sqlite3

        if os.path.exists(db_path):
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                # Select today's execution logs
                # Schema: execution_log table? Or slot_plans?
                # webapp.py utilized executor.history class.
                # Let's see if we can use it.
                # executor.history.ExecutionHistory needs a DB path.
                # backend/executor/history.py

                # Direct SQL for speed and dependency avoidance

                # We need "execution_log" table?
                # Actually webapp.py used "executor.history.get_todays_slots"
                # which joins `slot_plans` and `execution_log`.

                # Let's import the History class if possible.
                from executor.history import ExecutionHistory

                hist = ExecutionHistory(db_path)

                today_start = tz.localize(datetime.combine(today_local, datetime.min.time()))
                now_dt = datetime.now(tz)

                slots = hist.get_todays_slots(today_start, now_dt)
                for slot in slots:
                    start_str = slot.get("start_time")
                    if not start_str:
                        continue
                    start = datetime.fromisoformat(start_str)
                    local_start = start if start.tzinfo else tz.localize(start)
                    key = local_start.astimezone(tz).replace(tzinfo=None)
                    exec_map[key] = {
                        "actual_charge_kw": slot.get("battery_charge_kw", 0),
                        "actual_soc": slot.get("before_soc_percent"),
                        "water_heating_kw": slot.get("water_heating_kw", 0),
                    }
    except Exception as e:
        logger.warning(f"Failed to load SQLite history: {e}")

    # 3. Forecast Map (for historical slots)
    forecast_map = {}
    try:
        db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
        active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")
        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Minimal query
                cur = conn.execute(
                    "SELECT slot_start, pv_forecast_kwh, load_forecast_kwh FROM slot_forecasts WHERE slot_start >= ? AND forecast_version = ?",
                    (
                        tz.localize(datetime.combine(today_local, datetime.min.time())).isoformat(),
                        active_version,
                    ),
                )
                for row in cur:
                    try:
                        st = datetime.fromisoformat(row["slot_start"])
                        st_local = st if st.tzinfo else tz.localize(st)
                        forecast_map[st_local.astimezone(tz).replace(tzinfo=None)] = {
                            "pv_forecast_kwh": float(row["pv_forecast_kwh"] or 0),
                            "load_forecast_kwh": float(row["load_forecast_kwh"] or 0),
                        }
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Failed to load forecast map: {e}")

    # 4. Merge
    # Logic similar to webapp.py
    all_keys = sorted(set(schedule_map.keys()) | set(exec_map.keys()))
    merged_slots = []

    for key in all_keys:
        slot = {}
        if key in schedule_map:
            slot = schedule_map[key].copy()
        else:
            # Synthetic slot
            slot = {
                "start_time": tz.localize(key).isoformat(),
                "end_time": tz.localize(key + timedelta(minutes=60)).isoformat(),  # Default 60?
                # webapp used resolution_minutes from config (default 15)
            }

        # Attach history
        if key in exec_map:
            h = exec_map[key]
            slot["actual_charge_kw"] = h.get("actual_charge_kw")
            slot["actual_soc"] = h.get("actual_soc")
            # slot["water_heating_kw"] = h.get("water_heating_kw") # Plan usually has this

        # Attach forecast if plan missing it?
        if key in forecast_map:
            f = forecast_map[key]
            if "pv_kwh" not in slot:
                slot["pv_kwh"] = f["pv_forecast_kwh"]
            if "load_kwh" not in slot:
                slot["load_kwh"] = f["load_forecast_kwh"]

        merged_slots.append(slot)

    return _clean_nans({"date": today_local.isoformat(), "slots": merged_slots})


def _clean_nans(obj: Any) -> Any:
    """Recursively replace NaN/Infinity with None (or 0.0) for JSON safety."""
    import math

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0  # or None
        return obj
    elif isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nans(v) for v in obj]
    return obj
