import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, cast

import pytz
from fastapi import APIRouter

# Local imports (using absolute paths relative to project root)
from inputs import load_yaml, get_nordpool_data

# executor/history needs access
# We might need to adjust python path in dev-backend.sh if not matching
# But usually PYTHONPATH=. handles it.

logger = logging.getLogger("darkstar.api.schedule")
router = APIRouter(tags=["schedule"])


def get_executor_instance() -> Any | None:
    """Helper to get executor instance. Delegating to executor router singleton."""
    from backend.api.routers.executor import get_executor_instance as get_exec
    return get_exec()


@router.get(
    "/api/scheduler/status",
    summary="Get Scheduler Status",
    description="Returns the current status of the background scheduler.",
)
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


@router.get(
    "/api/schedule",
    summary="Get Active Schedule",
    description="Returns the current active optimization schedule with price overlay.",
)
async def get_schedule() -> dict[str, Any]:
    """Return the current active schedule.json with price overlay."""
    try:
        if os.path.exists("schedule.json"):
            with open("schedule.json") as f:
                data = json.load(f)
        else:
            return {"schedule": [], "meta": {}}
    except Exception as exc:
        logger.error(f"Failed to load schedule.json: {exc}")
        return {"schedule": [], "meta": {}}

    # Add price overlay
    if "schedule" in data:
        price_map: dict[datetime, float] = {}
        try:
            # We assume config.yaml is in root
            price_slots = get_nordpool_data("config.yaml")
            tz = pytz.timezone("Europe/Stockholm")  # Default fallback
            
            # Try to read timezone from config
            config = load_yaml("config.yaml")
            if "timezone" in config:
                tz = pytz.timezone(str(config["timezone"]))

            for p in price_slots:
                st = p["start_time"]
                # Normalization logic
                if st.tzinfo is None:
                    st_local_naive = tz.localize(st).replace(tzinfo=None)
                else:
                    st_local_naive = st.astimezone(tz).replace(tzinfo=None)
                price_map[st_local_naive] = float(p.get("import_price_sek_kwh") or 0.0)

            for slot in data["schedule"]:
                if "import_price_sek_kwh" not in slot:
                    try:
                        start_str = slot.get("start_time")
                        if start_str:
                            start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
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
        except Exception as exc:
            logger.warning("Price overlay unavailable: %s", exc)

    return cast(dict[str, Any], _clean_nans(data))


# ... Porting schedule_today_with_history ...
# This logic is complex (merging SQLite, MariaDB, and Schedule).
# I will port it carefully.


@router.get(
    "/api/schedule/today_with_history",
    summary="Get Today's Schedule & History",
    description="Returns a merged view of the planned schedule and actual execution history for the current day.",
)
async def schedule_today_with_history() -> dict[str, Any]:
    """Merged view of today's schedule and execution history."""
    import aiosqlite
    try:
        config = load_yaml("config.yaml")
        tz_name = str(config.get("timezone", "Europe/Stockholm"))
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Stockholm")
        config = {}

    today_local = datetime.now(tz).date()

    # 1. Load schedule.json
    schedule_map: dict[datetime, dict[str, Any]] = {}
    try:
        if os.path.exists("schedule.json"):
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

    # 2. Load History (aiosqlite)
    exec_map: dict[datetime, dict[str, Any]] = {}
    try:
        db_path = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
        if os.path.exists(db_path):
            from executor.history import ExecutionHistory
            hist = ExecutionHistory(db_path)

            today_start = tz.localize(datetime.combine(today_local, datetime.min.time()))
            now_dt = datetime.now(tz)

            slots = hist.get_todays_slots(today_start, now_dt)
            for slot in slots:
                start_str = slot.get("start_time")
                if not start_str:
                    continue
                start = datetime.fromisoformat(str(start_str))
                local_start = start if start.tzinfo else tz.localize(start)
                key = local_start.astimezone(tz).replace(tzinfo=None)
                exec_map[key] = {
                    "actual_charge_kw": slot.get("battery_charge_kw", 0),
                    "actual_soc": slot.get("before_soc_percent"),
                    "water_heating_kw": slot.get("water_heating_kw", 0),
                }
    except Exception as e:
        logger.warning(f"Failed to load History: {e}")

    # 3. Forecast Map (aiosqlite)
    forecast_map: dict[datetime, dict[str, float]] = {}
    try:
        db_path = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
        active_version = str(config.get("forecasting", {}).get("active_forecast_version", "aurora"))
        if os.path.exists(db_path):
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                today_iso = tz.localize(datetime.combine(today_local, datetime.min.time())).isoformat()
                async with conn.execute(
                    "SELECT slot_start, pv_forecast_kwh, load_forecast_kwh FROM slot_forecasts WHERE slot_start >= ? AND forecast_version = ?",
                    (today_iso, active_version),
                ) as cursor:
                    async for row in cursor:
                        try:
                            st = datetime.fromisoformat(str(row["slot_start"]))
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
    all_keys = sorted(set(schedule_map.keys()) | set(exec_map.keys()))
    merged_slots: list[dict[str, Any]] = []

    for key in all_keys:
        slot: dict[str, Any] = {}
        if key in schedule_map:
            slot = schedule_map[key].copy()
        else:
            # Synthetic slot
            slot = {
                "start_time": tz.localize(key).isoformat(),
                "end_time": tz.localize(key + timedelta(minutes=60)).isoformat(),
            }

        # Attach history
        if key in exec_map:
            h = exec_map[key]
            slot["actual_charge_kw"] = h.get("actual_charge_kw")
            slot["actual_soc"] = h.get("actual_soc")

        # Attach forecast
        if key in forecast_map:
            f = forecast_map[key]
            if "pv_kwh" not in slot:
                slot["pv_kwh"] = f["pv_forecast_kwh"]
            if "load_kwh" not in slot:
                slot["load_kwh"] = f["load_forecast_kwh"]

        merged_slots.append(slot)

    result_data = {"date": today_local.isoformat(), "slots": merged_slots}
    return cast(dict[str, Any], _clean_nans(result_data))


def _clean_nans(obj: Any) -> Any:
    """Recursively replace NaN/Infinity with 0.0 for JSON safety."""
    import math

    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {str(k): _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nans(v) for v in obj]
    return obj
