import asyncio
import json
import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytz
from fastapi import APIRouter, HTTPException

from inputs import (
    async_get_ha_entity_state,
    async_get_ha_sensor_float,
    get_async_ha_client,
    get_home_assistant_sensor_float,
    load_home_assistant_config,
    load_yaml,
    make_ha_headers,
)

logger = logging.getLogger("darkstar.api.services")

router_ha = APIRouter(prefix="/api/ha", tags=["ha"])
router_services = APIRouter(tags=["services"])


# --- Helper ---
async def _fetch_ha_history_avg(entity_id: str, hours: int) -> float:
    """Fetch history from HA and calculate time-weighted average."""
    if not entity_id:
        return 0.0

    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")
    if not url or not token:
        return 0.0

    headers = make_ha_headers(token)

    end_time = datetime.now(pytz.UTC)
    start_time = end_time - timedelta(hours=hours)

    # HA History API
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        client = await get_async_ha_client()
        resp = await client.get(api_url, headers=headers, params=params)
        if resp.status_code != 200:
            return 0.0

        data = resp.json()
        if not data or not data[0]:
            return 0.0

        # Calculate Average
        states = data[0]
        total_weighted_sum = 0.0
        total_duration_sec = 0.0

        prev_time = start_time
        prev_val = 0.0

        # Initial value from first state? Or fetch state at start_time?
        # Simplified: Use first state's value as starting point
        try:
            prev_val = float(states[0]["state"])
            prev_time = datetime.fromisoformat(states[0]["last_changed"])
        except Exception:
            pass

        for s in states:
            try:
                curr_time = datetime.fromisoformat(s["last_changed"])
                val = float(s["state"])

                # Duration since last change
                duration = (curr_time - prev_time).total_seconds()
                if duration > 0:
                    total_weighted_sum += prev_val * duration
                    total_duration_sec += duration

                prev_time = curr_time
                prev_val = val
            except Exception:
                continue

        # Add remainder until now
        duration = (end_time - prev_time).total_seconds()
        if duration > 0:
            total_weighted_sum += prev_val * duration
            total_duration_sec += duration

        if total_duration_sec == 0:
            return 0.0

        return round(total_weighted_sum / total_duration_sec, 2)

    except Exception as e:
        logger.warning(f"Error fetching HA history for {entity_id}: {e}")
        return 0.0


@router_ha.get(
    "/entity/{entity_id}",
    summary="Get HA Entity",
    description="Returns the state of a specific Home Assistant entity.",
)
async def get_ha_entity(entity_id: str) -> dict[str, Any]:
    state = await async_get_ha_entity_state(entity_id)
    if not state:
        return {
            "entity_id": entity_id,
            "state": "unknown",
            "attributes": {"friendly_name": "Offline/Missing"},
            "last_changed": None,
        }
    return state


@router_ha.get(
    "/average",
    summary="Get Entity Average",
    description="Calculate average value for an entity over the last N hours.",
)
async def get_ha_average(entity_id: str | None = None, hours: int = 24) -> dict[str, Any]:
    """Calculate average value for an entity over the last N hours."""
    from backend.core.cache import cache
    from inputs import get_load_profile_from_ha, load_yaml

    # Check cache first
    cache_key = f"ha_average:{entity_id}:{hours}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    if not entity_id:
        # Default to load power sensor
        config = load_yaml("config.yaml")
        sensors: dict[str, Any] = config.get("input_sensors", {})
        entity_id = cast("str | None", sensors.get("load_power"))

    if not entity_id:
        return {"average": 0.0, "entity_id": None, "hours": hours}

    avg_val = await _fetch_ha_history_avg(entity_id, hours)

    # Fallback to static profile if history unavailable/zero
    if avg_val == 0.0:
        try:
            config = load_yaml("config.yaml")
            profile = get_load_profile_from_ha(config)
            if profile:
                avg_val = sum(profile) / len(profile)
        except Exception as e:
            logger.warning(f"Fallback average calc failed: {e}")

    # Calculate daily_kwh estimate (avg * 24h)
    # Note: avg_val is usually Watts.
    # HA sensors are usually W. If fetch_ha_history_avg returns W, then /1000 is correct for kWh.
    # If it returns kW, then *24 is correct.
    # Let's assume the sensor is W (standard HA).
    # But wait, fetch_ha_history_avg just returns value.
    # The frontend expects 'average_load_kw'.
    # If standard sensor is W, we should divide by 1000 for kw.

    # Let's ensure we return kW.
    # If value > 100 (likely Watts), divide by 1000.
    # If value < 50 (likely kW), keep as is. Simple heuristic or just be explicit?
    # Let's trust the value is W from typical HA power sensors, so convert to kW.

    val_kw = avg_val / 1000.0 if avg_val > 100 else avg_val

    result = {
        "average_load_kw": round(val_kw, 3),
        "daily_kwh": round(val_kw * 24, 2),
        "entity_id": entity_id,
        "hours": hours,
    }

    # Cache for 60 seconds
    await cache.set(cache_key, result, ttl_seconds=60.0)

    return result


@router_ha.get(
    "/entities",
    summary="List HA Entities",
    description="List available Home Assistant entities.",
)
async def get_ha_entities() -> dict[str, list[dict[str, str]]]:
    """List available HA entities."""
    # Fetch from HA states
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token:
        return {"entities": []}

    try:
        headers = make_ha_headers(token)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/api/states", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            # Filter and format
            entities: list[dict[str, str]] = []
            for s in data:
                eid = str(s.get("entity_id", ""))
                if eid.startswith(
                    ("sensor.", "binary_sensor.", "input_boolean.", "switch.", "input_number.")
                ):
                    entities.append(
                        {
                            "entity_id": eid,
                            "friendly_name": str(s.get("attributes", {}).get("friendly_name", eid)),
                            "domain": eid.split(".")[0],
                        }
                    )
            return {"entities": entities}
    except Exception as e:
        logger.warning(f"Error fetching HA entities: {e}")

    return {"entities": []}


@router_services.get(
    "/api/performance/data",
    summary="Get Performance Data",
    description="Get performance metrics for the Aurora card.",
)
async def get_performance_data(days: int = 7) -> dict[str, Any]:
    """Get performance metrics for Aurora card."""
    try:
        from backend.learning import get_learning_engine

        engine = get_learning_engine()
        if hasattr(engine, "get_performance_series"):
            data = engine.get_performance_series(days_back=days)  # pyright: ignore [reportUnknownMemberType, reportUnknownVariableType]
            return cast("dict[str, Any]", data)
        else:
            return {
                "soc_series": [],
                "cost_series": [],
                "mae_pv_aurora": None,
                "mae_pv_baseline": None,
                "mae_load_aurora": None,
                "mae_load_baseline": None,
            }
    except Exception as e:
        return {
            "soc_series": [],
            "cost_series": [],
            "mae_pv_aurora": None,
            "mae_pv_baseline": None,
            "mae_load_aurora": None,
            "mae_load_baseline": None,
            "error": str(e),
        }


@router_ha.get(
    "/water_today",
    summary="Get Water Heating Energy",
    description="Get today's water heating energy usage.",
)
async def get_water_today() -> dict[str, Any]:
    """Get today's water heating energy usage."""
    config = load_yaml("config.yaml")

    # Check if water heater feature is enabled
    system_config: dict[str, Any] = config.get("system", {})
    has_water_heater = system_config.get("has_water_heater", False)

    if not has_water_heater:
        return {"water_kwh_today": 0.0, "cost": 0.0, "source": "disabled"}

    sensors: dict[str, Any] = config.get("input_sensors", {})
    entity_id = sensors.get("water_heater_consumption", "sensor.vvb_energy_daily")

    kwh = await async_get_ha_sensor_float(str(entity_id)) or 0.0
    return {"water_kwh_today": kwh, "cost": 0.0, "source": "home_assistant"}


# --- Services Endpoints ---
# NOTE: /api/status has been moved to system.py (Rev ARC4)


@router_services.get(
    "/api/water/boost",
    summary="Get Water Boost Status",
    description="Get current water boost status from executor.",
)
async def get_water_boost():
    """Get current water boost status from executor."""
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()
    if not executor:
        return {"boost": False, "source": "no_executor"}

    if hasattr(executor, "get_water_boost_status"):
        status = executor.get_water_boost_status()
        if status:
            return {"boost": True, "expires_at": status.get("expires_at"), "source": "executor"}
    return {"boost": False, "source": "executor"}


@router_services.post(
    "/api/water/boost",
    summary="Set Water Boost",
    description="Activate water heater boost via executor quick action.",
)
async def set_water_boost() -> dict[str, str]:
    """Activate water heater boost via executor quick action."""
    try:
        from backend.api.routers.executor import (
            get_executor_instance,
        )

        executor = get_executor_instance()
        if not executor:
            logger.error("Executor unavailable for water boost")
            raise HTTPException(503, "Executor not available")
        if hasattr(executor, "set_water_boost"):
            # The executor.set_water_boost isn't strictly typed in Pyright's eyes yet maybe?
            # We fixed it in executor/actions.py, but need to be sure engine calls match.
            # Assuming set_water_boost(duration_minutes=...) exists on the executor instance
            # which is actually engine.py's ExecutorEngine or similar.
            # Actually get_executor_instance returns the Engine instance.
            result = executor.set_water_boost(duration_minutes=60)  # pyright: ignore [reportUnknownMemberType]
            if not result.get("success"):
                logger.error(f"Failed to set water boost: {result.get('error')}")
                raise HTTPException(500, f"Failed to set water boost: {result.get('error')}")

            logger.info("Water boost activated successfully")
            return {"status": "success", "message": "Water boost activated for 60 minutes"}

        logger.error("Executor missing set_water_boost method")
        raise HTTPException(501, "Water boost not supported by executor")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting water boost: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error setting water boost: {e}") from e


@router_services.delete(
    "/api/water/boost",
    summary="Cancel Water Boost",
    description="Cancel active water boost.",
)
async def cancel_water_boost() -> dict[str, str]:
    """Cancel active water boost."""
    try:
        from backend.api.routers.executor import (
            get_executor_instance,
        )

        executor = get_executor_instance()
        if executor and hasattr(executor, "clear_water_boost"):
            executor.clear_water_boost()
            logger.info("Water boost cancelled successfully")
        return {"status": "success", "message": "Water boost cancelled"}
    except Exception as e:
        logger.error(f"Error cancelling water boost: {e}\n{traceback.format_exc()}")
        raise HTTPException(500, f"Internal error cancelling water boost: {e}") from e


@router_services.get(
    "/api/energy/today",
    summary="Get Today's Energy",
    description="Get today's energy summary from HA sensors using parallel async fetching.",
)
async def get_energy_today() -> dict[str, float]:
    """Get today's energy summary from HA sensors in parallel."""
    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    # Define keys we want to fetch
    keys = [
        "today_grid_import",
        "today_grid_export",
        "today_pv_production",
        "today_load_consumption",
        "today_battery_charge",
        "today_net_cost",
    ]

    # Map keys to entity IDs
    tasks = []
    for key in keys:
        eid = sensors.get(key)
        if eid:
            tasks.append(async_get_ha_sensor_float(str(eid)))
        else:
            tasks.append(asyncio.sleep(0, result=0.0))  # Placeholder for missing config

    # Fetch all in parallel!
    results = await asyncio.gather(*tasks)

    # Map back to variables
    grid_imp_kwh = results[0] or 0.0
    grid_exp_kwh = results[1] or 0.0
    pv_kwh = results[2] or 0.0
    load_kwh = results[3] or 0.0
    batt_chg_kwh = results[4] or 0.0
    net_cost = results[5] or 0.0

    return {
        "solar": round(pv_kwh, 2),
        "grid_import": round(grid_imp_kwh, 2),
        "grid_export": round(grid_exp_kwh, 2),
        "consumption": round(load_kwh, 2),
        "grid_import_kwh": round(grid_imp_kwh, 2),
        "grid_export_kwh": round(grid_exp_kwh, 2),
        "battery_charge_kwh": round(batt_chg_kwh, 2),
        "battery_cycles": 0,
        "pv_production_kwh": round(pv_kwh, 2),
        "load_consumption_kwh": round(load_kwh, 2),
        "net_cost_kr": round(net_cost, 2),
    }


@router_services.get(
    "/api/energy/range",
    summary="Get Energy Range",
    description="Get energy range data (today, yesterday, week, month).",
)
async def get_energy_range(period: str = "today") -> dict[str, Any]:
    """Get energy range data."""
    import sqlite3

    import pytz

    from backend.learning import get_learning_engine

    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    def get_val(key: str, default: float = 0.0) -> float:
        eid = sensors.get(key)
        if not eid:
            return default
        return get_home_assistant_sensor_float(str(eid)) or default

    # All periods now query the database for financial metrics
    try:
        engine = get_learning_engine()
        tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
        now_local = datetime.now(tz)
        today_local = now_local.date()

        # Determine date range based on period
        if period == "today":
            start_date = end_date = today_local
        elif period == "yesterday":
            end_date = today_local - timedelta(days=1)
            start_date = end_date
        elif period == "week":
            end_date = today_local
            start_date = today_local - timedelta(days=6)
        elif period == "month":
            end_date = today_local
            start_date = today_local - timedelta(days=29)
        else:
            # Fallback
            start_date = end_date = today_local

        # Query
        with sqlite3.connect(str(engine.db_path), timeout=5.0) as conn:  # pyright: ignore [reportUnknownMemberType, reportUnknownArgumentType]
            cursor = conn.cursor()
            # We filter by DATE(slot_start) which works if slot_start is ISO-8601 YYYY-MM-DD...
            row = cursor.execute(
                """
                SELECT
                    SUM(COALESCE(import_kwh, 0)),
                    SUM(COALESCE(export_kwh, 0)),
                    SUM(COALESCE(batt_charge_kwh, 0)),
                    SUM(COALESCE(batt_discharge_kwh, 0)),
                    SUM(COALESCE(water_kwh, 0)),
                    SUM(COALESCE(pv_kwh, 0)),
                    SUM(COALESCE(load_kwh, 0)),
                    -- Costs
                -- Costs
                    SUM(COALESCE(import_kwh, 0) * COALESCE(import_price_sek_kwh, 0)),
                    SUM(COALESCE(export_kwh, 0) * COALESCE(export_price_sek_kwh, 0)),
                    -- Grid Charge Cost (Import excess of load)
                    SUM(MAX(0, COALESCE(import_kwh, 0) - COALESCE(load_kwh, 0))
                        * COALESCE(import_price_sek_kwh, 0)),
                    -- Self Consumption Savings (Load covered by non-grid sources)
                    SUM(MAX(0, COALESCE(load_kwh, 0) - COALESCE(import_kwh, 0))
                        * COALESCE(import_price_sek_kwh, 0)),
                    -- Count
                    COUNT(*)
                FROM slot_observations
                WHERE DATE(slot_start) >= ? AND DATE(slot_start) <= ?
            """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchone()

        if not row:
            raise ValueError("No data returned")

        grid_imp_kwh = row[0] or 0.0
        grid_exp_kwh = row[1] or 0.0
        batt_chg_kwh = row[2] or 0.0
        batt_dis_kwh = row[3] or 0.0
        water_kwh = row[4] or 0.0
        pv_kwh = row[5] or 0.0
        load_kwh = row[6] or 0.0

        import_cost = row[7] or 0.0
        export_rev = row[8] or 0.0
        grid_charge_cost = row[9] or 0.0
        self_cons_savings = row[10] or 0.0

        net_cost = import_cost - export_rev

        # For "today", overlay real-time HA sensor values for energy totals
        # This ensures dashboard shows up-to-date energy values even if DB lags
        if period == "today":
            ha_grid_imp = get_val("today_grid_import")
            ha_grid_exp = get_val("today_grid_export")
            ha_pv = get_val("today_pv_production")
            ha_load = get_val("today_load_consumption")
            ha_batt_chg = get_val("today_battery_charge")
            ha_batt_dis = get_val("today_battery_discharge")
            ha_water = get_val("water_heater_consumption")

            # Use HA values if they're larger (more current) than DB values
            grid_imp_kwh = max(grid_imp_kwh, ha_grid_imp)
            grid_exp_kwh = max(grid_exp_kwh, ha_grid_exp)
            pv_kwh = max(pv_kwh, ha_pv)
            load_kwh = max(load_kwh, ha_load)
            batt_chg_kwh = max(batt_chg_kwh, ha_batt_chg)
            batt_dis_kwh = max(batt_dis_kwh, ha_batt_dis)
            water_kwh = max(water_kwh, ha_water)

        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "grid_import_kwh": round(grid_imp_kwh, 2),
            "grid_export_kwh": round(grid_exp_kwh, 2),
            "battery_charge_kwh": round(batt_chg_kwh, 2),
            "battery_discharge_kwh": round(batt_dis_kwh, 2),
            "water_heating_kwh": round(water_kwh, 2),
            "pv_production_kwh": round(pv_kwh, 2),
            "load_consumption_kwh": round(load_kwh, 2),
            "import_cost_sek": round(import_cost, 2),
            "export_revenue_sek": round(export_rev, 2),
            "grid_charge_cost_sek": round(grid_charge_cost, 2),
            "self_consumption_savings_sek": round(self_cons_savings, 2),
            "net_cost_sek": round(net_cost, 2),
            "slot_count": row[11] or 0,
        }
    except Exception as e:
        # logger.warning(f"Failed to get historical energy data for {period}: {e}")
        # Fallback with zeros
        return {
            "period": period,
            "start_date": datetime.now().date().isoformat(),
            "end_date": datetime.now().date().isoformat(),
            "grid_import_kwh": 0.0,
            "grid_export_kwh": 0.0,
            "battery_charge_kwh": 0.0,
            "battery_discharge_kwh": 0.0,
            "water_heating_kwh": 0.0,
            "pv_production_kwh": 0.0,
            "load_consumption_kwh": 0.0,
            "import_cost_sek": 0.0,
            "export_revenue_sek": 0.0,
            "grid_charge_cost_sek": 0.0,
            "self_consumption_savings_sek": 0.0,
            "net_cost_sek": 0.0,
            "slot_count": 0,
            "error": str(e),
        }


# --- Additional Missing Endpoints ---


@router_ha.get(
    "/services",
    summary="List HA Services",
    description="List available Home Assistant services.",
)
async def get_ha_services() -> dict[str, list[str]]:
    """List available HA services."""
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")
    if not url or not token:
        return {"services": []}

    try:
        headers = make_ha_headers(token)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/api/services", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            # Flatten to list of "domain.service" strings
            services: list[str] = []
            for domain_obj in data:
                domain = str(domain_obj.get("domain", ""))
                for service_name in domain_obj.get("services", {}):
                    services.append(f"{domain}.{service_name}")
            return {"services": sorted(services)}
    except Exception as e:
        logger.warning(f"Error fetching HA services: {e}")

    return {"services": []}


@router_ha.post(
    "/test",
    summary="Test HA Connection",
    description="Test connection to Home Assistant API.",
)
async def test_ha_connection() -> dict[str, str]:
    """Test connection to Home Assistant."""
    config = load_home_assistant_config()
    url = config.get("url")
    token = config.get("token")

    if not url or not token:
        return {"status": "error", "message": "HA not configured"}

    try:
        headers = make_ha_headers(token)
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/api/", headers=headers)
        if resp.status_code == 200:
            return {"status": "success", "message": "Connected to Home Assistant"}
        else:
            return {"status": "error", "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router_services.get(
    "/api/ha-socket",
    summary="Get HA Socket Status",
    description="Return status of the HA WebSocket connection.",
)
async def get_ha_socket_status() -> dict[str, Any]:
    """Return status of the HA WebSocket connection."""
    try:
        from backend.ha_socket import (
            get_socket_status,  # pyright: ignore [reportMissingImports, reportUnknownVariableType, reportAttributeAccessIssue]
        )

        return cast("dict[str, Any]", get_socket_status())
    except ImportError:
        return {"status": "unavailable", "message": "HA socket module not loaded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router_services.post(
    "/api/simulate",
    summary="Run Simulation",
    description="Run a simulation of the current schedule.",
)
async def run_simulation() -> dict[str, Any]:
    """Run schedule simulation."""
    try:
        from planner.simulation import simulate_schedule  # pyright: ignore [reportMissingImports]

        with Path("schedule.json").open() as f:
            schedule = json.load(f)

        config = load_yaml("config.yaml")
        initial_state: dict[str, Any] = {}  # Simplified simulation

        result = simulate_schedule(schedule, config, initial_state)
        return {"status": "success", "result": cast("dict[str, Any]", result)}
    except ImportError:
        return {"status": "error", "message": "Simulation module not available"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
