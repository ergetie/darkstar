import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
from fastapi import APIRouter, Depends

from backend.api.deps import get_learning_store

# Local imports (using absolute paths relative to project root)
from backend.core.prices import get_nordpool_data
from backend.core.secrets import load_yaml
from backend.learning.store import LearningStore

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
        # ARC11 Training Info
        "training_enabled": status.training_enabled,
        "next_training_at": status.next_training_at.isoformat()
        if status.next_training_at
        else None,
        "last_training_at": status.last_training_at.isoformat()
        if status.last_training_at
        else None,
        "last_training_status": status.last_training_status,
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
        schedule_path = Path("data/schedule.json")
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
            price_slots = await get_nordpool_data("config.yaml")
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


@router.get(
    "/api/schedule/today_with_history",
    summary="Get Today's Schedule & History",
    description="Returns a merged view of the planned schedule and actual execution history for the current day.",
)
async def schedule_today_with_history(
    store: LearningStore = Depends(get_learning_store),
) -> dict[str, Any]:
    """Merged view of today's schedule and execution history."""

    try:
        config = load_yaml("config.yaml")
        tz_name = str(config.get("timezone", "Europe/Stockholm"))
        tz = pytz.timezone(tz_name)
    except Exception:
        tz = pytz.timezone("Europe/Stockholm")
        config = {}

    today_local = datetime.now(tz).date()
    now = datetime.now(tz)
    now_naive = now.replace(tzinfo=None)

    # 1. Load schedule.json
    schedule_map: dict[datetime, dict[str, Any]] = {}
    try:
        schedule_path = Path("data/schedule.json")
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
                    tomorrow_local = today_local + timedelta(days=1)
                    # Include today AND tomorrow for 48h view compatibility
                    if local.date() not in (today_local, tomorrow_local):
                        continue
                    schedule_map[local.replace(tzinfo=None)] = slot
                except Exception:
                    continue
    except Exception:
        pass

    # 2. Load History (LearningStore Async)
    exec_map: dict[datetime, dict[str, Any]] = {}
    try:
        today_start = tz.localize(datetime.combine(today_local, datetime.min.time()))
        today_end = today_start + timedelta(days=1)
        rows = await store.get_history_range(today_start, today_end)

        for row in rows:
            try:
                # Parse Timestamp
                # row is a dict now
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

                # ev_charging_kwh -> actual_ev_charging_kw
                ev_charging_kw = float(row["ev_charging_kwh"] or 0.0) / duration_hours

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
                    "actual_ev_charging_kw": round(ev_charging_kw, 3),
                    "import_price_sek_kwh": float(row["import_price_sek_kwh"] or 0.0),
                }
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Failed to load History: {e}")

    # 3. Forecast Map (LearningStore Async)
    forecast_map: dict[datetime, dict[str, float]] = {}
    try:
        active_version = str(config.get("forecasting", {}).get("active_forecast_version", "aurora"))
        today_start_dt = tz.localize(datetime.combine(today_local, datetime.min.time()))

        rows = await store.get_forecasts_range(today_start_dt, active_version)

        for row in rows:
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

    # 4. Planned Actions Map (LearningStore Async)
    planned_map: dict[datetime, dict[str, float]] = {}
    try:
        today_start_dt = tz.localize(datetime.combine(today_local, datetime.min.time()))

        # Use new method
        rows = await store.get_plans_range(today_start_dt)

        for row in rows:
            try:
                st = datetime.fromisoformat(str(row["slot_start"]))
                st_local = st if st.tzinfo else tz.localize(st)
                key = st_local.astimezone(tz).replace(tzinfo=None)

                # Convert kWh to kW (slot_plans stores kWh, frontend expects kW)
                duration_hours = 0.25  # 15-min slots

                planned_map[key] = {
                    "battery_charge_kw": float(row["planned_charge_kwh"] or 0.0) / duration_hours,
                    "battery_discharge_kw": float(row["planned_discharge_kwh"] or 0.0)
                    / duration_hours,
                    "soc_target_percent": float(row["planned_soc_percent"] or 0.0),
                    "projected_soc_percent": float(row["projected_soc_percent"] or 0.0),
                    "export_kwh": float(row["planned_export_kwh"] or 0.0),
                    "water_heating_kw": float(row["planned_water_heating_kwh"] or 0.0)
                    / duration_hours,
                }
            except Exception:
                continue

        logger.info(f"Loaded {len(planned_map)} planned slots for {today_local}")
    except Exception as e:
        logger.warning(f"Failed to load planned map: {e}")

    # 5. Observations Map (LearningStore Async) - Actual PV/Load data
    obs_map: dict[datetime, dict[str, float]] = {}
    try:
        today_start_dt = tz.localize(datetime.combine(today_local, datetime.min.time()))
        tomorrow_end_dt = today_start_dt + timedelta(days=2)

        rows = await store.get_observations_range(today_start_dt, tomorrow_end_dt)

        for row in rows:
            try:
                st = datetime.fromisoformat(str(row["slot_start"]))
                st_local = st if st.tzinfo else tz.localize(st)
                key = st_local.astimezone(tz).replace(tzinfo=None)

                # Convert kWh to kW for water (15-min slots = 0.25h)
                duration_hours = 0.25

                obs_map[key] = {
                    "actual_pv_kwh": float(row["pv_kwh"] or 0),
                    "actual_load_kwh": float(row["load_kwh"] or 0),
                    "actual_water_kw": float(row["water_kwh"] or 0) / duration_hours,
                }
            except Exception:
                continue

        logger.info(f"Loaded {len(obs_map)} observation slots for {today_local}")
    except Exception as e:
        logger.warning(f"Failed to load observations map: {e}")

    # 6. Merge
    # [REV F36] Match Api.schedule() rounding for the starting slot (only return from now forward)
    # [REV F36] Match Api.schedule() rounding for the starting slot (only return from now forward)
    now = datetime.now(tz)
    # planned_start_naive removed (unused)

    # Collect all keys for the entire day (History + Future)
    # [REV F36] FIX: Do NOT filter by 'now'. tailored_schedule needs full day context.
    # We filter by today's start (00:00) to ensure we get the full history.
    today_start_dt = tz.localize(datetime.combine(today_local, datetime.min.time()))
    today_start_naive = today_start_dt.replace(tzinfo=None)

    raw_keys = set(schedule_map.keys()) | set(exec_map.keys()) | set(planned_map.keys())
    all_keys = sorted({k for k in raw_keys if k >= today_start_naive})

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
        slot["is_historical"] = False

        # Attach history
        # [REV F36] FIX: Ensure we never mark future slots as 'executed' even if DB has rogue entries.
        # This prevents 'actuals' (0.0) from hiding 'planned' (e.g. 5.0) in the chart.
        is_future_check = key >= now_naive

        if key in exec_map and not is_future_check:
            h = exec_map[key]
            slot["is_executed"] = True
            slot["is_historical"] = True
            slot["actual_charge_kw"] = h.get("actual_charge_kw")
            slot["actual_discharge_kw"] = h.get("actual_discharge_kw")
            slot["actual_export_kwh"] = h.get("actual_export_kwh")
            slot["actual_soc"] = h.get("actual_soc")
            slot["water_heating_kw"] = h.get("water_heating_kw", slot.get("water_heating_kw"))
            slot["actual_ev_charging_kw"] = h.get("actual_ev_charging_kw")
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
            # [REV F36] Only source battery actions from DB for historical slots.
            # Future slots (>= now) MUST come from schedule.json only to avoid stale DB data.
            is_future = key >= now_naive

            if not is_future:
                # Historical: Add from DB if missing (though schedule_today_with_history prioritizes schedule.json)
                if "battery_charge_kw" not in slot or slot.get("battery_charge_kw") is None:
                    slot["battery_charge_kw"] = p["battery_charge_kw"]
                if "battery_discharge_kw" not in slot or slot.get("battery_discharge_kw") is None:
                    slot["battery_discharge_kw"] = p["battery_discharge_kw"]
                if "soc_target_percent" not in slot or slot.get("soc_target_percent") is None:
                    slot["soc_target_percent"] = p["soc_target_percent"]
                # Attach projected_soc_percent from database for historical slots
                if "projected_soc_percent" not in slot or slot.get("projected_soc_percent") is None:
                    slot["projected_soc_percent"] = p.get("projected_soc_percent", 0.0)
                if "export_kwh" not in slot or slot.get("export_kwh") is None:
                    slot["export_kwh"] = p.get("export_kwh", 0.0)
                if "water_heating_kw" not in slot or slot.get("water_heating_kw") is None:
                    slot["water_heating_kw"] = p.get("water_heating_kw", 0.0)
            else:
                # Future: Only take non-critical data from planned_map if really needed.
                # [REV F36] CRITICAL: Absolutely DO NOT touch battery_charge_kw or battery_discharge_kw for future slots.
                # schedule.json is the ONLY source of truth for future actions.
                # Even if schedule.json has None, we prefer None over stale DB data.
                if "soc_target_percent" not in slot or slot.get("soc_target_percent") is None:
                    slot["soc_target_percent"] = p["soc_target_percent"]
                if "soc_target_percent" not in slot or slot.get("soc_target_percent") is None:
                    slot["soc_target_percent"] = p["soc_target_percent"]
                if "water_heating_kw" not in slot or slot.get("water_heating_kw") is None:
                    slot["water_heating_kw"] = p.get("water_heating_kw", 0.0)

        # Attach actual observations (PV, Load, Water) from slot_observations
        if key in obs_map and not is_future_check:
            obs = obs_map[key]
            slot["actual_pv_kwh"] = obs["actual_pv_kwh"]
            slot["actual_load_kwh"] = obs["actual_load_kwh"]
            slot["actual_water_kw"] = obs["actual_water_kw"]

        merged_slots.append(slot)

    historical_with_planned = sum(
        1
        for s in merged_slots
        if s.get("actual_soc") is not None and s.get("battery_charge_kw") is not None
    )
    logger.info(
        f"Returning {len(merged_slots)} slots, {historical_with_planned} historical with planned actions"
    )

    # 6. Price Overlay (Ensure future prices are visible even if schedule.json missing them)
    try:
        price_slots = await get_nordpool_data("config.yaml")
        price_map_overlay: dict[datetime, float] = {}
        for p in price_slots:
            st = p["start_time"]
            local_naive = st if st.tzinfo is None else st.astimezone(tz).replace(tzinfo=None)
            price_map_overlay[local_naive] = float(p.get("import_price_sek_kwh") or 0.0)

        for slot in merged_slots:
            if "import_price_sek_kwh" not in slot or slot.get("import_price_sek_kwh") is None:
                try:
                    start_str = slot.get("start_time")
                    if start_str:
                        start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                        local_naive = (
                            start
                            if start.tzinfo is None
                            else start.astimezone(tz).replace(tzinfo=None)
                        )
                        price = price_map_overlay.get(local_naive)
                        if price is not None:
                            slot["import_price_sek_kwh"] = round(price, 4)
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("Price overlay unavailable in today_with_history: %s", exc)

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
        schedule_path = Path("data/schedule.json")

        # Load existing schedule
        existing: dict[str, Any]
        if schedule_path.exists():
            with schedule_path.open() as f:
                loaded_data = json.load(f)
                existing = cast("dict[str, Any]", loaded_data)
        else:
            existing = {"schedule": [], "meta": {}}

        # Merge overrides
        overrides: list[dict[str, Any]] = cast(
            "list[dict[str, Any]]", request_body.get("overrides", [])
        )
        if overrides:
            # Simple override logic: replace matching slots by start_time
            override_map: dict[Any, dict[str, Any]] = {o.get("start_time"): o for o in overrides}
            schedule_list: list[dict[str, Any]] = cast(
                "list[dict[str, Any]]", existing.get("schedule", [])
            )
            slot: dict[str, Any]
            for slot in schedule_list:
                st: Any = slot.get("start_time")
                if st in override_map:
                    slot.update(override_map[st])

            meta: dict[str, Any] = cast("dict[str, Any]", existing.get("meta", {}))
            meta["last_manual_override"] = datetime.now().isoformat()
            existing["meta"] = meta

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
