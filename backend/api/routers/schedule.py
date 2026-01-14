import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
from fastapi import APIRouter

# Local imports (using absolute paths relative to project root)
from inputs import get_nordpool_data, load_yaml

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
    """Get live scheduler status from in-process service."""
    from backend.services.scheduler_service import scheduler_service

    status = scheduler_service.status
    return {
        "running": status.running,
        "enabled": status.enabled,
        "last_run_at": status.last_run_at.isoformat() if status.last_run_at else None,
        "next_run_at": status.next_run_at.isoformat() if status.next_run_at else None,
        "last_run_status": status.last_run_status,
        "last_error": status.last_error,
        "current_task": status.current_task,
    }


@router.get(
    "/api/schedule",
    summary="Get Active Schedule",
    description="Returns the current active optimization schedule with price overlay.",
)
async def get_schedule() -> dict[str, Any]:
    """Return the current active schedule.json with price overlay."""
    from backend.core.cache import cache

    # Check cache first (5 min TTL)
    cache_key = "schedule:current"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        schedule_path = Path("schedule.json")
        if schedule_path.exists():
            with schedule_path.open() as f:
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

    result = cast("dict[str, Any]", _clean_nans(data))

    # Cache result
    await cache.set(cache_key, result, ttl_seconds=300.0)

    return result


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
        schedule_path = Path("schedule.json")
        if schedule_path.exists():
            with schedule_path.open() as f:
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
        db_path_str = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
        db_path = Path(db_path_str)
        if db_path.exists():
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row

                # Query window: Today start to Now
                today_start = tz.localize(datetime.combine(today_local, datetime.min.time()))
                now_dt = datetime.now(tz)

                query = """
                    SELECT
                        slot_start, slot_end,
                        batt_charge_kwh, batt_discharge_kwh, soc_end_percent, water_kwh,
                        import_kwh, export_kwh,
                        import_price_sek_kwh
                    FROM slot_observations
                    WHERE slot_start >= ? AND slot_start < ?
                    ORDER BY slot_start ASC
                """
                async with conn.execute(
                    query, (today_start.isoformat(), now_dt.isoformat())
                ) as cursor:
                    async for row in cursor:
                        try:
                            # Parse Timestamp
                            s_start = datetime.fromisoformat(str(row["slot_start"]))
                            s_end = datetime.fromisoformat(str(row["slot_end"]))

                            # Normalize key
                            local_start = s_start if s_start.tzinfo else tz.localize(s_start)
                            local_end = s_end if s_end.tzinfo else tz.localize(s_end)
                            key = local_start.astimezone(tz).replace(tzinfo=None)

                            # Calculate Duration (hours)
                            duration_hours = (local_end - local_start).total_seconds() / 3600.0
                            if duration_hours <= 0:
                                duration_hours = 0.25  # Fallback 15 mins

                            # Kw calculation: kWh / hours = kW
                            # water_kwh -> water_heating_kw
                            water_kw = float(row["water_kwh"] or 0.0) / duration_hours

                            # batt_charge_kwh -> actual_charge_kw
                            charge_kwh = float(row["batt_charge_kwh"] or 0.0)
                            charge_kw = charge_kwh / duration_hours

                            # batt_discharge_kwh -> actual_discharge_kw (for export/discharge slots)
                            discharge_kwh = float(row["batt_discharge_kwh"] or 0.0)
                            discharge_kw = discharge_kwh / duration_hours

                            # export_kwh for display
                            export_kwh = float(row["export_kwh"] or 0.0)

                            exec_map[key] = {
                                "actual_charge_kw": round(charge_kw, 3),
                                "actual_discharge_kw": round(discharge_kw, 3),
                                "actual_export_kwh": round(export_kwh, 3),
                                "actual_soc": float(row["soc_end_percent"] or 0.0),
                                "water_heating_kw": round(water_kw, 3),
                                "import_price_sek_kwh": float(row["import_price_sek_kwh"] or 0.0),
                            }
                        except Exception:
                            continue

    except Exception as e:
        logger.warning(f"Failed to load History: {e}")

    # 3. Forecast Map (aiosqlite)
    forecast_map: dict[datetime, dict[str, float]] = {}
    try:
        db_path_str = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
        db_path = Path(db_path_str)
        active_version = str(config.get("forecasting", {}).get("active_forecast_version", "aurora"))
        if db_path.exists():
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                today_iso = tz.localize(
                    datetime.combine(today_local, datetime.min.time())
                ).isoformat()
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
        logger.info(
            f"Loaded {len(forecast_map)} forecast slots for {today_local} (ver={active_version})"
        )
    except Exception as e:
        logger.warning(f"Failed to load forecast map: {e}")

    # 4. Planned Actions Map (slot_plans table)
    planned_map: dict[datetime, dict[str, float]] = {}
    try:
        db_path_str = str(config.get("learning", {}).get("sqlite_path", "data/planner_learning.db"))
        db_path = Path(db_path_str)
        if db_path.exists():
            async with aiosqlite.connect(str(db_path)) as conn:
                conn.row_factory = aiosqlite.Row
                today_iso = tz.localize(
                    datetime.combine(today_local, datetime.min.time())
                ).isoformat()

                query = """
                    SELECT
                        slot_start,
                        planned_charge_kwh,
                        planned_discharge_kwh,
                        planned_soc_percent,
                        planned_export_kwh,
                        planned_water_heating_kwh
                    FROM slot_plans
                    WHERE slot_start >= ?
                    ORDER BY slot_start ASC
                """

                async with conn.execute(query, (today_iso,)) as cursor:
                    async for row in cursor:
                        try:
                            st = datetime.fromisoformat(str(row["slot_start"]))
                            st_local = st if st.tzinfo else tz.localize(st)
                            key = st_local.astimezone(tz).replace(tzinfo=None)

                            # Convert kWh to kW (slot_plans stores kWh, frontend expects kW)
                            duration_hours = 0.25  # 15-min slots

                            planned_map[key] = {
                                "battery_charge_kw": float(row["planned_charge_kwh"] or 0.0)
                                / duration_hours,
                                "battery_discharge_kw": float(row["planned_discharge_kwh"] or 0.0)
                                / duration_hours,
                                "soc_target_percent": float(row["planned_soc_percent"] or 0.0),
                                "export_kwh": float(row["planned_export_kwh"] or 0.0),
                                "water_heating_kw": float(
                                    row["planned_water_heating_kwh"] or 0.0
                                )
                                / duration_hours,
                            }
                        except Exception:
                            continue

        logger.info(f"Loaded {len(planned_map)} planned slots for {today_local}")
    except Exception as e:
        logger.warning(f"Failed to load planned map: {e}")

    # 5. Merge
    all_keys = sorted(set(schedule_map.keys()) | set(exec_map.keys()) | set(planned_map.keys()))
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
            slot["actual_discharge_kw"] = h.get("actual_discharge_kw")
            slot["actual_export_kwh"] = h.get("actual_export_kwh")
            slot["actual_soc"] = h.get("actual_soc")
            slot["water_heating_kw"] = h.get("water_heating_kw", slot.get("water_heating_kw"))
            # Add historical price from DB if not already present
            if "import_price_sek_kwh" not in slot:
                slot["import_price_sek_kwh"] = h.get("import_price_sek_kwh")

        # Attach forecast
        if key in forecast_map:
            f = forecast_map[key]
            slot["pv_forecast_kwh"] = f["pv_forecast_kwh"]
            slot["load_forecast_kwh"] = f["load_forecast_kwh"]
            if "pv_kwh" not in slot:
                slot["pv_kwh"] = f["pv_forecast_kwh"]
            if "load_kwh" not in slot:
                slot["load_kwh"] = f["load_forecast_kwh"]
        elif not slot.get("pv_kwh") and not exec_map.get(key):
            # Only warn if we have neither plan nor history nor forecast for a slot that exists
            pass

        # Attach planned actions from slot_plans database (Historical Overlay)
        if key in planned_map:
            p = planned_map[key]
            # Only add if not already present from schedule.json (schedule.json takes priority for future)
            if "battery_charge_kw" not in slot or slot.get("battery_charge_kw") is None:
                slot["battery_charge_kw"] = p["battery_charge_kw"]
            if "battery_discharge_kw" not in slot or slot.get("battery_discharge_kw") is None:
                slot["battery_discharge_kw"] = p["battery_discharge_kw"]
            if "soc_target_percent" not in slot or slot.get("soc_target_percent") is None:
                slot["soc_target_percent"] = p["soc_target_percent"]
            if "export_kwh" not in slot or slot.get("export_kwh") is None:
                slot["export_kwh"] = p.get("export_kwh", 0.0)
            if "water_heating_kw" not in slot or slot.get("water_heating_kw") is None:
                slot["water_heating_kw"] = p.get("water_heating_kw", 0.0)

        merged_slots.append(slot)

    historical_with_planned = sum(
        1
        for s in merged_slots
        if s.get("actual_soc") is not None and s.get("battery_charge_kw") is not None
    )
    logger.info(
        f"Returning {len(merged_slots)} slots, {historical_with_planned} historical with planned actions"
    )

    result_data = {"date": today_local.isoformat(), "slots": merged_slots}
    return cast("dict[str, Any]", _clean_nans(result_data))


@router.post(
    "/api/schedule/save",
    summary="Save Schedule Overrides",
    description="Persist manual schedule overrides to schedule.json.",
)
async def save_schedule(request_body: dict[str, Any]) -> dict[str, str]:
    """Save manual schedule overrides."""
    try:
        schedule_path = Path("schedule.json")

        # Load existing schedule
        if schedule_path.exists():
            with schedule_path.open() as f:
                existing = json.load(f)
        else:
            existing = {"schedule": [], "meta": {}}

        # Merge overrides
        overrides = request_body.get("overrides", [])
        if overrides:
            # Simple override logic: replace matching slots by start_time
            override_map = {o.get("start_time"): o for o in overrides}
            for slot in existing.get("schedule", []):
                st = slot.get("start_time")
                if st in override_map:
                    slot.update(override_map[st])

            existing["meta"]["last_manual_override"] = datetime.now().isoformat()

        # Write back
        with schedule_path.open("w") as f:
            json.dump(existing, f, indent=2, default=str)

        logger.info("Schedule saved with %d overrides", len(overrides))
        return {"status": "success", "message": f"Saved {len(overrides)} overrides"}
    except Exception as e:
        logger.exception("Failed to save schedule")
        return {"status": "error", "message": str(e)}


def _clean_nans(obj: Any) -> Any:
    """Recursively replace NaN/Infinity with 0.0 for JSON safety."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {str(k): _clean_nans(v) for k, v in cast("dict[Any, Any]", obj).items()}
    if isinstance(obj, list):
        return [_clean_nans(v) for v in cast("list[Any]", obj)]
    return obj
