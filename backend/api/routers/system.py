import asyncio
import json
import logging
from collections.abc import Coroutine  # noqa: TC003
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.api.models.system import (
    LogInfoResponse,
    StatusResponse,
    SystemHealthResponse,
    VersionResponse,
)
from backend.core.ha_client import get_ha_bool, get_ha_sensor_float, get_ha_sensor_kw_normalized
from backend.core.secrets import load_yaml
from backend.core.version import get_version as _get_git_version

logger = logging.getLogger("darkstar.api.system")
router = APIRouter(tags=["system"])


def _get_learning_engine() -> Any:
    """Get the learning engine instance."""
    from backend.learning import get_learning_engine

    return get_learning_engine()


@router.get(
    "/api/version",
    summary="Get System Version",
    description="Returns the current version, commit hash, and build date.",
    response_model=VersionResponse,
)
async def get_version() -> VersionResponse:
    """Return the current system version."""
    return VersionResponse(version=_get_git_version())


@router.get(
    "/api/status",
    summary="Get System Status",
    description="Get instantaneous system status (SoC, Power Flow) in parallel.",
    response_model=StatusResponse,
)
async def get_system_status() -> StatusResponse:
    """Get instantaneous system status (SoC, Power Flow) using parallel async fetching."""
    config = load_yaml("config.yaml")
    sensors: dict[str, Any] = config.get("input_sensors", {})

    # Define keys to fetch
    keys = ["battery_soc", "pv_power", "load_power", "battery_power", "grid_power"]
    tasks: list[Coroutine[Any, Any, float | None]] = []
    for key in keys:
        eid = sensors.get(key)
        if eid:
            if key == "battery_soc":
                tasks.append(get_ha_sensor_float(str(eid)))
            else:
                tasks.append(get_ha_sensor_kw_normalized(str(eid)))
        else:
            tasks.append(asyncio.sleep(0, result=0.0))

    # Fetch EV states
    ev_configs: list[dict[str, Any]] = []
    if config.get("system", {}).get("has_ev_charger", False):
        for ev in config.get("ev_chargers", []):
            if ev.get("enabled", True):
                ev_configs.append(ev)

    for ev in ev_configs:
        sensor = ev.get("sensor")
        tasks.append(
            get_ha_sensor_kw_normalized(str(sensor)) if sensor else asyncio.sleep(0, result=0.0)
        )

        soc_sensor = ev.get("soc_sensor")
        tasks.append(
            get_ha_sensor_float(str(soc_sensor)) if soc_sensor else asyncio.sleep(0, result=None)
        )

        plug_sensor = ev.get("plug_sensor")
        tasks.append(
            get_ha_bool(str(plug_sensor)) if plug_sensor else asyncio.sleep(0, result=False)
        )

    results: list[Any] = await asyncio.gather(*tasks)

    soc = results[0] or 0.0
    pv_pow = results[1] or 0.0
    load_pow = results[2] or 0.0
    batt_pow = results[3] or 0.0
    grid_pow = results[4] or 0.0

    # Apply inversion if configured
    if sensors.get("grid_power_inverted", False):
        grid_pow = -grid_pow
    if sensors.get("battery_power_inverted", False):
        batt_pow = -batt_pow

    # Extract EV results
    ev_chargers: list[dict[str, Any]] = []
    base_idx = len(keys)
    total_ev_kw = 0.0
    any_plugged = False

    for i, ev in enumerate(ev_configs):
        idx = base_idx + i * 3
        kw = results[idx] or 0.0
        # If in Watts, convert to kW (best effort if HA provides numeric only, inputs.py float doesn't convert W to kW but ha_socket does)
        # Assuming inputs.py get_ha_sensor_float returns exact numeric value
        # But wait, ha_socket converts W to kW if unit_of_measurement is 'W'. Let's not duplicate that complexity unless needed.
        # Typically people set kW for EVs.
        ev_soc = results[idx + 1]
        plugged = results[idx + 2] or False

        ev_chargers.append(
            {
                "name": ev.get("name", f"EV {i + 1}"),
                "kw": round(kw, 3),
                "soc": round(ev_soc, 1) if ev_soc is not None else None,
                "plugged_in": plugged,
            }
        )
        total_ev_kw += kw
        if plugged:
            any_plugged = True

    return StatusResponse(
        status="online",
        mode="fastapi",
        rev="ARC1",
        soc_percent=round(soc, 1),
        pv_power_kw=round(pv_pow, 3),
        load_power_kw=round(load_pow, 3),
        battery_power_kw=round(batt_pow, 3),
        grid_power_kw=round(grid_pow, 3),
        ev_kw=round(total_ev_kw, 3),
        ev_plugged_in=any_plugged,
        ev_chargers=ev_chargers,
    )


@router.get(
    "/api/system/log-info",
    summary="Get Log File Info",
    description="Returns metadata about the main log file (size, date).",
    response_model=LogInfoResponse,
)
async def get_log_info() -> LogInfoResponse:
    """Return metadata about the main log file."""
    log_path = Path("data/darkstar.log")
    if not log_path.exists():
        return LogInfoResponse(filename="darkstar.log", size_bytes=0, last_modified="never")

    stats = log_path.stat()
    return LogInfoResponse(
        filename="darkstar.log",
        size_bytes=stats.st_size,
        last_modified=datetime.fromtimestamp(stats.st_mtime, tz=UTC).isoformat(),
    )


@router.get(
    "/api/system/logs",
    summary="Download Log File",
    description="Returns the main log file as a downloadable attachment.",
)
async def download_logs():
    """Download the main log file."""
    from fastapi.responses import FileResponse

    log_path = Path("data/darkstar.log")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")

    return FileResponse(path=log_path, filename="darkstar.log", media_type="text/plain")


@router.delete(
    "/api/system/logs",
    summary="Clear/Truncate Log File",
    description="Truncates the main log file to zero bytes.",
)
async def clear_logs():
    """Clear/Truncate the main log file."""
    log_path = Path("data/darkstar.log")
    try:
        if log_path.exists():
            with log_path.open("w") as f:
                f.truncate(0)
        return {"status": "ok", "message": "Logs cleared"}
    except Exception as e:
        logger.error(f"Failed to clear logs: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/system/monitors",
    summary="Get Runtime Invariant Monitor Status",
    description=(
        "Latest evaluation result for each runtime invariant (slot continuity, "
        "energy balance, SoC bounds, plan freshness, command success, forecast "
        "sanity, data quality), active violation episodes, and monitor health."
    ),
)
async def get_invariant_monitors() -> dict[str, Any]:
    """Expose runtime invariant monitor status (stabilization-review-2)."""
    from backend.monitors import invariant_monitors

    return invariant_monitors.get_status()


@router.get(
    "/api/system/health",
    summary="Get System Health",
    description="Returns comprehensive system health metrics (learning, database, planner).",
    response_model=SystemHealthResponse,
)
async def get_system_health() -> SystemHealthResponse:
    """Get comprehensive system health metrics."""
    from backend.api.models.system import (
        DatabaseHealth,
        ForecastHealth,
        LearningHealth,
        PlannerHealth,
        SystemHealthResponse,
        SystemMetrics,
    )
    from backend.health import get_forecast_status, get_load_forecast_status

    # 1. Learning Stats
    try:
        engine = _get_learning_engine()
        learning_stats = await engine.store.get_learning_stats()
        learning_health = LearningHealth(
            total_runs=learning_stats["total_runs"],
            status=learning_stats["status"],
            last_run=learning_stats["last_run"],
        )
    except Exception as e:
        logger.error(f"Error getting learning stats: {e}")
        learning_health = LearningHealth(total_runs=0, status="unknown", last_run=None)

    # 2. Database Stats
    try:
        engine = _get_learning_engine()
        db_stats = await engine.store.get_db_stats()
        database_health = DatabaseHealth(
            size_mb=db_stats["size_mb"],
            slot_plans_count=db_stats["slot_plans_count"],
            slot_observations_count=db_stats["slot_observations_count"],
            health=db_stats["health"],
        )
    except Exception as e:
        logger.error(f"Error getting DB stats: {e}")
        database_health = DatabaseHealth(
            size_mb=0.0, slot_plans_count=0, slot_observations_count=0, health="error"
        )

    # 3. Planner Stats
    planner_health = PlannerHealth(last_run=None, status="unknown", next_scheduled=None)
    try:
        status_path = Path("data/scheduler_status.json")
        if status_path.exists():
            with status_path.open() as f:
                data = json.load(f)

            planner_health = PlannerHealth(
                last_run=data.get("last_run_at"),
                status=data.get("last_run_status", "unknown"),
                next_scheduled=data.get("next_run_at"),
            )
    except Exception as e:
        logger.error(f"Error getting planner stats: {e}")

    # 4. System Metrics
    uptime_hours = 0.0
    try:
        with Path("/proc/uptime").open() as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime_hours = round(uptime_seconds / 3600, 1)
    except Exception:
        pass

    errors_24h = 0
    # Simple grep for ERROR in logs? Skipping for now to avoid perf issues, hardcode 0
    # or check log size changes.

    system_metrics = SystemMetrics(
        errors_24h=errors_24h, uptime_hours=uptime_hours, version=_get_git_version()
    )

    # 5. Forecast Health (REV F65 Phase 5d)
    pv_info = get_forecast_status()
    load_info = get_load_forecast_status()
    forecast_health = ForecastHealth(
        pv_status=pv_info.get("status", "ok"),
        load_status=load_info.get("status", "ok"),
        load_reason=load_info.get("reason", ""),
    )

    return SystemHealthResponse(
        learning=learning_health,
        database=database_health,
        planner=planner_health,
        forecast=forecast_health,
        system=system_metrics,
    )
