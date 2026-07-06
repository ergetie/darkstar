import asyncio
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from ruamel.yaml import YAML

if TYPE_CHECKING:
    from executor import ExecutorEngine

logger = logging.getLogger("darkstar.api.executor")
router = APIRouter(tags=["executor"])

# --- Executor Singleton ---
_executor_engine: "ExecutorEngine | None" = None
_executor_lock = threading.Lock()


def get_executor_instance() -> "ExecutorEngine | None":
    """Get or create the singleton ExecutorEngine instance.

    Thread-safe singleton pattern using double-checked locking.
    Returns None if executor cannot be initialized (e.g., missing dependencies).
    """
    global _executor_engine
    if _executor_engine is None:
        with _executor_lock:
            if _executor_engine is None:
                try:
                    # Assuming 'executor' package is in PYTHONPATH (root)
                    from executor import ExecutorEngine

                    _executor_engine = ExecutorEngine()
                    # Initialize HA Client
                    _executor_engine.init_ha_client()
                except ImportError as e:
                    logger.error("Failed to import executor: %s", e)
                except Exception as e:
                    logger.error("Failed to initialize executor: %s", e)
    return _executor_engine


def require_executor() -> "ExecutorEngine":
    """FastAPI dependency that requires an executor instance.

    Use with Depends() for endpoints that require a working executor.
    Raises HTTPException 503 if executor is unavailable.
    """
    executor = get_executor_instance()
    if executor is None:
        raise HTTPException(503, "Executor service unavailable")
    return executor


# Type alias for dependency injection
ExecutorDep = Annotated["ExecutorEngine", Depends(require_executor)]


# --- Models ---


class ToggleRequest(BaseModel):
    enabled: bool | None = None
    shadow_mode: bool | None = None


class QuickActionRequest(BaseModel):
    action: str
    duration_minutes: int = 60
    params: dict[str, Any] = {}


class PauseRequest(BaseModel):
    duration_minutes: int = 60


# --- Routes ---


@router.get(
    "/api/executor/status",
    summary="Get Executor Status",
    description="Returns the current operational status of the executor.",
)
async def get_status(executor: ExecutorDep) -> dict[str, Any]:
    """Return current executor status.

    Uses FastAPI Depends() for clean dependency injection (Rev ARC4).
    """
    return executor.get_status()


@router.get(
    "/api/executor/load-balancer/status",
    summary="Get Load Balancer Status",
    description="Returns the real-time per-phase load balancer status (universal-load-balancing 6.2).",
)
async def get_load_balancer_status(executor: ExecutorDep) -> dict[str, Any]:
    """Return the latest load-balancer tick result (same shape as the
    `load_balancing` key in the live-metrics WebSocket payload)."""
    return executor.get_load_balancer_status()


@router.post(
    "/api/executor/toggle",
    summary="Toggle Executor",
    description="Enables or disables the executor loop.",
)
async def toggle_executor(payload: ToggleRequest) -> dict[str, Any]:
    """Enable or disable the executor."""
    yaml_handler = YAML()
    yaml_handler.preserve_quotes = True

    config_path = Path("config.yaml")
    try:
        with config_path.open(encoding="utf-8") as f:
            config = cast("dict[str, Any]", yaml_handler.load(f) or {})  # type: ignore
    except Exception:
        config = {}

    executor_cfg = config.setdefault("executor", {})
    if payload.enabled is not None:
        executor_cfg["enabled"] = payload.enabled
    if payload.shadow_mode is not None:
        executor_cfg["shadow_mode"] = payload.shadow_mode

    with config_path.open("w", encoding="utf-8") as f:
        yaml_handler.dump(config, f)  # type: ignore

    # Reload executor
    executor = get_executor_instance()
    if executor:
        executor.reload_config()
        if payload.enabled and executor.config.enabled:
            executor.start()
        elif payload.enabled is False:
            executor.stop()

    return {
        "status": "success",
        "enabled": executor_cfg.get("enabled", False),
        "shadow_mode": executor_cfg.get("shadow_mode", False),
    }


@router.post(
    "/api/executor/run",
    summary="Trigger Executor Run",
    description="Forcefully triggers a single execution loop iteration.",
)
async def run_once() -> dict[str, str]:
    """Trigger a single loop run."""
    executor = get_executor_instance()
    if executor:
        result = await executor.run_once()
        return {"status": "success" if result.get("success") else "error"}
    return {"status": "error", "message": "Executor unavailable"}


@router.get(
    "/api/executor/quick-action",
    summary="Get Quick Action Status",
    description="Returns the status of any active quick action.",
)
async def get_quick_actions() -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor:
        return {"quick_action": None}
    return {"quick_action": executor.get_active_quick_action()}


@router.post(
    "/api/executor/quick-action",
    summary="Set Quick Action",
    description="Activates a temporary override (quick action).",
)
async def set_quick_action(payload: QuickActionRequest) -> dict[str, str]:
    executor = get_executor_instance()
    if not executor:
        raise HTTPException(500, "Executor unavailable")

    executor.set_quick_action(payload.action, payload.duration_minutes, payload.params)
    return {"status": "success"}


@router.delete(
    "/api/executor/quick-action",
    summary="Clear Quick Action",
    description="Cancels any active quick action.",
)
async def clear_quick_action() -> dict[str, str]:
    executor = get_executor_instance()
    if not executor:
        raise HTTPException(500, "Executor unavailable")
    executor.clear_quick_action()
    return {"status": "success"}


@router.post(
    "/api/executor/pause",
    summary="Pause Executor",
    description="Pauses the executor for a specified duration.",
)
async def pause_executor(payload: PauseRequest) -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor:
        raise HTTPException(500, "Executor unavailable")

    executor.pause(payload.duration_minutes)
    status = executor.get_pause_status()
    return {
        "status": "success",
        "paused_until": status["paused_at"] if status else None,
    }


@router.post(
    "/api/executor/resume",
    summary="Resume Executor",
    description="Resumes the executor from a paused state.",
)
@router.get(
    "/api/executor/resume",
    summary="Resume Executor (GET)",
    description="Resumes the executor via GET request (e.g. for simple links).",
)
async def resume_executor() -> dict[str, str]:
    executor = get_executor_instance()
    if not executor:
        raise HTTPException(500, "Executor unavailable")
    executor.resume()
    return {"status": "success"}


@router.get(
    "/api/executor/history",
    summary="Get Execution History",
    description="Returns historical execution logs.",
)
async def get_history(
    limit: int = 100,
    offset: int = 0,
    slot_start: str | None = None,
    success_only: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor or not executor.history:
        return {"records": [], "count": 0}

    try:
        success = None
        if success_only is not None:
            success = success_only.lower() in ("true", "1", "yes")

        records = await asyncio.to_thread(
            executor.history.get_history,
            limit=limit,
            offset=offset,
            slot_start=slot_start,
            success_only=success,
            start_date=start_date,
            end_date=end_date,
        )
        return {"records": records, "count": len(records)}
    except Exception as e:
        logger.exception("Error getting executor history")
        return {"records": [], "count": 0, "error": str(e)}


@router.get(
    "/api/executor/history/download",
    summary="Download Execution History",
    description="Returns historical execution logs as a CSV file.",
)
async def download_history(
    start_date: str | None = None,
    end_date: str | None = None,
    success_only: str | None = None,
):
    from fastapi.responses import Response

    executor = get_executor_instance()
    if not executor or not executor.history:
        raise HTTPException(500, "Executor history not available")

    try:
        success = None
        if success_only is not None:
            success = success_only.lower() in ("true", "1", "yes")

        csv_data = await asyncio.to_thread(
            executor.history.get_history_csv,
            start_date=start_date,
            end_date=end_date,
            success_only=success,
        )

        filename = "execution_history.csv"
        if start_date:
            filename = f"execution_history_{start_date}.csv"

        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("Error downloading history")
        raise HTTPException(500, f"Error generating CSV: {e}") from e


@router.get(
    "/api/executor/stats",
    summary="Get Execution Statistics",
    description="Returns execution statistics over a specified period.",
)
async def get_stats(days: int = 7) -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor:
        return {}
    return await asyncio.to_thread(executor.get_stats, days=days)


@router.get(
    "/api/executor/config",
    summary="Get Executor Config",
    description="Returns the current executor configuration.",
)
async def get_executor_config() -> dict[str, Any]:
    """Return current executor configuration."""
    executor = get_executor_instance()
    if executor is None:
        raise HTTPException(500, "Executor not available")

    cfg = executor.config
    return {
        "enabled": cfg.enabled,
        "shadow_mode": cfg.shadow_mode,
        "interval_seconds": cfg.interval_seconds,
        "automation_toggle_entity": getattr(cfg, "automation_toggle_entity", None),
        "manual_override_entity": getattr(cfg, "manual_override_entity", None),
        "inverter": {
            "work_mode": cfg.inverter.work_mode,
            "soc_target": cfg.inverter.soc_target,
            "grid_charging_enable": cfg.inverter.grid_charging_enable,
            "grid_charge_power": cfg.inverter.grid_charge_power,
            "minimum_reserve": cfg.inverter.minimum_reserve,
            "max_charge_current": cfg.inverter.max_charge_current,
            "max_discharge_current": cfg.inverter.max_discharge_current,
            "grid_max_export_power_switch": cfg.inverter.grid_max_export_power_switch,
        },
        "water_heater": {
            "target_entity": cfg.water_heater_devices[0].target_entity
            if cfg.water_heater_devices
            else None,
            "temp_normal": cfg.water_heater.temp_normal,
            "temp_off": cfg.water_heater.temp_off,
            "temp_boost": cfg.water_heater.temp_boost,
            "temp_max": cfg.water_heater.temp_max,
        },
        "notifications": {
            "service": cfg.notifications.service,
            "on_charge_start": getattr(cfg.notifications, "on_charge_start", False),
            "on_charge_stop": getattr(cfg.notifications, "on_charge_stop", False),
            "on_export_start": getattr(cfg.notifications, "on_export_start", False),
            "on_export_stop": getattr(cfg.notifications, "on_export_stop", False),
            "on_error": getattr(cfg.notifications, "on_error", False),
        },
    }


@router.put(
    "/api/executor/config",
    summary="Update Executor Config",
    description="Updates the executor configuration.",
)
async def update_executor_config(request: Request) -> dict[str, str]:
    """Update executor entity configuration."""
    yaml_handler = YAML()
    yaml_handler.preserve_quotes = True

    payload = await request.json()
    config_path = Path("config.yaml")

    try:
        with config_path.open(encoding="utf-8") as f:
            config = cast("dict[str, Any]", yaml_handler.load(f) or {})  # type: ignore

        if "executor" not in config:
            config["executor"] = {}

        executor_cfg = cast("dict[str, Any]", config["executor"])

        # Update flat fields
        for key in ["enabled", "shadow_mode", "interval_seconds"]:
            if key in payload:
                executor_cfg[key] = payload[key]

        # Update nested inverter config
        if "inverter" in payload:
            if "inverter" not in executor_cfg:
                executor_cfg["inverter"] = {}
            for key, value in payload["inverter"].items():
                # Map legacy keys if they still come from frontend (backward compat during migration)
                mapping = {
                    "work_mode_entity": "work_mode",
                    "soc_target_entity": "soc_target",
                    "grid_charging_entity": "grid_charging_enable",
                    "max_charging_current_entity": "max_charge_current",
                    "max_discharging_current_entity": "max_discharge_current",
                    "grid_max_export_power_switch_entity": "grid_max_export_power_switch",
                }
                standard_key = mapping.get(key, key)
                executor_cfg["inverter"][standard_key] = value

        # Update nested water_heater config
        if "water_heater" in payload:
            if "water_heater" not in executor_cfg:
                executor_cfg["water_heater"] = {}
            for key, value in payload["water_heater"].items():
                executor_cfg["water_heater"][key] = value

        with config_path.open("w", encoding="utf-8") as f:
            yaml_handler.dump(config, f)  # type: ignore

        # Reload executor config
        executor = get_executor_instance()
        if executor:
            executor.reload_config()

        return {"status": "success", "message": "Configuration updated"}

    except Exception as e:
        logger.exception("Failed to update executor config")
        raise HTTPException(500, str(e)) from e


@router.get(
    "/api/executor/notifications",
    summary="Get Notification Settings",
    description="Returns current notification settings.",
)
async def get_notifications() -> dict[str, Any]:
    """Get notification settings."""
    executor = get_executor_instance()
    if executor and executor.config and executor.config.notifications:
        cfg = executor.config.notifications
        return {
            "service": cfg.service,
            "on_charge_start": cfg.on_charge_start,
            "on_charge_stop": cfg.on_charge_stop,
            "on_export_start": cfg.on_export_start,
            "on_export_stop": cfg.on_export_stop,
            "on_water_heat_start": getattr(cfg, "on_water_heat_start", False),
            "on_water_heat_stop": getattr(cfg, "on_water_heat_stop", False),
            "on_soc_target_change": getattr(cfg, "on_soc_target_change", False),
            "on_override_activated": getattr(cfg, "on_override_activated", False),
            "on_error": cfg.on_error,
        }

    # Fallback to config file
    try:
        yaml_handler = YAML()
        config_path = Path("config.yaml")
        with config_path.open(encoding="utf-8") as f:
            config = cast("dict[str, Any]", yaml_handler.load(f) or {})  # type: ignore

        executor_cfg = cast("dict[str, Any]", config.get("executor", {}))
        notify_cfg = cast("dict[str, Any]", executor_cfg.get("notifications", {}))
        return {
            "service": notify_cfg.get("service"),
            "on_charge_start": notify_cfg.get("on_charge_start", False),
            "on_charge_stop": notify_cfg.get("on_charge_stop", False),
            "on_export_start": notify_cfg.get("on_export_start", False),
            "on_export_stop": notify_cfg.get("on_export_stop", False),
            "on_error": notify_cfg.get("on_error", False),
        }
    except Exception:
        return {"service": None}


@router.post(
    "/api/executor/notifications",
    summary="Update Notification Settings",
    description="Updates notification settings.",
)
async def update_notifications(request: Request) -> dict[str, str]:
    """Update notification settings."""
    yaml_handler = YAML()
    yaml_handler.preserve_quotes = True

    payload = await request.json()
    config_path = Path("config.yaml")

    try:
        with config_path.open(encoding="utf-8") as f:
            config = cast("dict[str, Any]", yaml_handler.load(f))  # type: ignore

        if "executor" not in config:
            config["executor"] = {}

        executor_cfg = cast("dict[str, Any]", config["executor"])
        if "notifications" not in executor_cfg:
            executor_cfg["notifications"] = {}

        notify_cfg = cast("dict[str, Any]", executor_cfg["notifications"])
        for key, value in payload.items():
            notify_cfg[key] = value

        with config_path.open("w", encoding="utf-8") as f:
            yaml_handler.dump(config, f)  # type: ignore

        # Reload executor config
        executor = get_executor_instance()
        if executor:
            executor.reload_config()

        return {"status": "success"}

    except Exception as e:
        logger.exception("Failed to update notifications")
        raise HTTPException(500, str(e)) from e


@router.post(
    "/api/executor/notifications/test",
    summary="Test Notifications",
    description="Sends a test notification to verify configuration.",
)
async def test_notifications() -> dict[str, str]:
    """Send a test notification."""
    executor = get_executor_instance()
    if not executor:
        raise HTTPException(500, "Executor not available")

    try:
        success = await executor.send_notification(
            "Test", "This is a test notification from Darkstar"
        )
        if success:
            return {"status": "success", "message": "Test notification sent"}
        else:
            return {"status": "error", "message": "Notification sending failed"}
    except Exception as e:
        raise HTTPException(500, str(e)) from e


@router.get(
    "/api/executor/live",
    summary="Get Live Metrics",
    description="Returns real-time metrics from the executor.",
)
async def get_live() -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor:
        return {}
    return await executor.get_live_metrics()


async def get_executor_status_snapshot() -> dict[str, Any]:
    """Internal helper to get status without dependency injection (for dashboard bundle)."""
    executor = get_executor_instance()
    if not executor:
        return {}
    return executor.get_status()


@router.get(
    "/api/executor/health",
    summary="Get Executor Health",
    description="Returns detailed health information about the executor.",
)
async def get_health(executor: ExecutorDep) -> dict[str, Any]:
    """
    Get executor health status for dashboard.
    """
    is_alive = executor._thread and executor._thread.is_alive()  # type: ignore[attr-defined]
    paused = executor.is_paused
    should_be_running = executor.config.enabled and not paused

    # Collect warnings
    warnings: list[str] = []
    if executor.config.enabled and not is_alive and not paused:
        warnings.append("Executor is enabled but background thread is not running")

    # Profile-driven missing entities (REV F56)
    if executor.inverter_profile:
        # Use existing full config from engine if available
        config: dict[str, Any] = getattr(executor, "_full_config", {})
        for missing_key in executor.inverter_profile.get_missing_entities(config):
            warnings.append(f"Required entity not configured: {missing_key}")

    return {
        "status": "healthy"
        if is_alive == should_be_running and executor.status.last_run_status != "error"
        else "error",
        "is_running": is_alive,
        "is_enabled": executor.config.enabled,
        "is_paused": paused,
        "should_be_running": should_be_running,
        "last_run_at": executor.status.last_run_at,
        "last_run_status": executor.status.last_run_status,
        "has_error": executor.status.last_run_status == "error",
        "error": executor.status.last_error if executor.status.last_run_status == "error" else None,
        "recent_errors": list(executor.recent_errors) if executor.recent_errors else [],  # type: ignore[arg-type]
        "warnings": warnings,
        "is_healthy": is_alive == should_be_running and executor.status.last_run_status != "error",
    }


@router.get(
    "/api/profiles/{name}/suggestions",
    summary="Get Profile Suggestions",
    description="Returns suggested configuration values for a specific inverter profile.",
)
async def get_profile_suggestions(name: str) -> dict[str, Any]:
    """Return suggested configuration for a profile.

    This helps users set up their inverter by providing recommended entities
    and parameters for their selected profile. Returns one suggestion per entity
    in the profile's entity registry using the profile's default_entity values.
    """
    # Deferred imports to avoid circular dependencies
    from backend.core.secrets import load_yaml
    from executor.profiles import load_profile

    try:
        profile = load_profile(name)

        # Build suggestions from the v2 entity registry:
        # Each entity's default_entity is the recommended HA entity ID.
        # Keys are flat config paths like "executor.inverter.work_mode".
        suggestions: dict[str, str | None] = {}
        for key, entity_def in profile.entities.items():
            # Standard keys live directly in executor.inverter.*
            # Custom/composite keys go into executor.inverter.custom_entities.*
            from executor.actions import _STANDARD_INVERTER_KEYS  # type: ignore[import-private]

            if key in _STANDARD_INVERTER_KEYS:  # type: ignore[used-before-def]
                config_path = f"executor.inverter.{key}"
            else:
                config_path = f"executor.inverter.custom_entities.{key}"
            suggestions[config_path] = entity_def.default_entity

        # Calculate missing entities against current config
        config = load_yaml("config.yaml")
        missing = profile.get_missing_entities(config)

        # Build diff to show what's already set and what's suggested
        diff: list[dict[str, Any]] = []
        for config_key, suggested_value in suggestions.items():
            parts = config_key.split(".")
            section: dict[str, Any] | None = config
            for part in parts:
                if isinstance(section, dict):
                    section = section.get(part)
                else:
                    section = None
                    break
            current_value: Any = section
            short_key = parts[-1]

            diff.append(
                {
                    "key": config_key,
                    "short_key": short_key,
                    "suggested": suggested_value,
                    "current": current_value,
                    "is_missing": current_value is None or current_value == "",
                    "is_different": current_value != suggested_value,
                }
            )

        return {
            "profile_name": name,
            "profile_description": profile.metadata.description,
            "suggestions": suggestions,
            "missing_entities": missing,
            "diff": diff,
        }
    except FileNotFoundError:
        raise HTTPException(404, f"Profile '{name}' not found") from None
    except Exception as e:
        logger.exception("Error getting suggestions for profile %s", name)
        raise HTTPException(500, str(e)) from e


@router.get(
    "/api/profiles",
    summary="List Inverter Profiles",
    description="Returns a list of all available inverter profiles discovered on disk.",
)
async def get_profiles() -> list[dict[str, Any]]:
    """Return a list of all available inverter profiles."""
    from executor.profiles import list_profiles

    try:
        return list_profiles()
    except Exception as e:
        logger.exception("Error listing profiles")
        raise HTTPException(500, f"Error listing profiles: {e}") from e
