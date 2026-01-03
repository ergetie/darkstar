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
        success = executor.run_once()
        return {"status": "success" if success else "error"}
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

    executor.set_quick_action(payload.action, payload.duration_minutes)
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
) -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor or not executor.history:
        return {"records": [], "count": 0}

    try:
        success = None
        if success_only is not None:
            success = success_only.lower() in ("true", "1", "yes")

        records = executor.history.get_history(
            limit=limit,
            offset=offset,
            slot_start=slot_start,
            success_only=success,
        )
        return {"records": records, "count": len(records)}
    except Exception as e:
        logger.exception("Error getting executor history")
        return {"records": [], "count": 0, "error": str(e)}


@router.get(
    "/api/executor/stats",
    summary="Get Execution Statistics",
    description="Returns execution statistics over a specified period.",
)
async def get_stats(days: int = 7) -> dict[str, Any]:
    executor = get_executor_instance()
    if not executor:
        return {}
    return executor.get_stats(days=days)


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
        "soc_target_entity": getattr(cfg, "soc_target_entity", None),
        "inverter": {
            "work_mode_entity": cfg.inverter.work_mode_entity,
            "grid_charging_entity": cfg.inverter.grid_charging_entity,
            "max_charging_current_entity": getattr(
                cfg.inverter, "max_charging_current_entity", None
            ),
            "max_discharging_current_entity": getattr(
                cfg.inverter, "max_discharging_current_entity", None
            ),
        },
        "water_heater": {
            "target_entity": cfg.water_heater.target_entity,
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
        for key in ["enabled", "shadow_mode", "interval_seconds", "soc_target_entity"]:
            if key in payload:
                executor_cfg[key] = payload[key]

        # Update nested inverter config
        if "inverter" in payload:
            if "inverter" not in executor_cfg:
                executor_cfg["inverter"] = {}
            for key, value in payload["inverter"].items():
                executor_cfg["inverter"][key] = value

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
        success = executor.send_notification("Test", "This is a test notification from Darkstar")
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
    return executor.get_live_metrics()
