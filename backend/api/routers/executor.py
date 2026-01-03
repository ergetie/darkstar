import logging
import threading
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger("darkstar.api.executor")
router = APIRouter(tags=["executor"])

# --- Executor Singleton ---
_executor_engine = None
_executor_lock = threading.Lock()


def _get_executor():
    global _executor_engine
    if _executor_engine is None:
        with _executor_lock:
            if _executor_engine is None:
                try:
                    # Assuming 'executor' package is in PYTHONPATH (root)
                    from executor import ExecutorEngine

                    _executor_engine = ExecutorEngine()
                    # Initialize HA Client roughly if needed
                    # In webapp.py it called _init_ha_client()
                    if hasattr(_executor_engine, "_init_ha_client"):
                        _executor_engine._init_ha_client()
                except ImportError as e:
                    logger.error("Failed to import executor: %s", e)
                except Exception as e:
                    logger.error("Failed to initialize executor: %s", e)
    return _executor_engine


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
async def get_status():
    """Return current executor status."""
    executor = _get_executor()
    if executor is None:
        return {"status": "error", "message": "Executor not available"}
    return executor.get_status()


@router.post(
    "/api/executor/toggle",
    summary="Toggle Executor",
    description="Enables or disables the executor loop.",
)
async def toggle_executor(payload: ToggleRequest):
    """Enable or disable the executor."""
    try:
        from ruamel.yaml import YAML

        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True
        with open("config.yaml", encoding="utf-8") as f:
            config = yaml_handler.load(f) or {}
    except Exception:
        config = {}

    executor_cfg = config.setdefault("executor", {})
    if payload.enabled is not None:
        executor_cfg["enabled"] = payload.enabled
    if payload.shadow_mode is not None:
        executor_cfg["shadow_mode"] = payload.shadow_mode

    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml_handler.dump(config, f)

    # Reload executor
    executor = _get_executor()
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
async def run_once():
    """Trigger a single loop run."""
    executor = _get_executor()
    if executor:
        success = executor.run_once()
        return {"status": "success" if success else "error"}
    return {"status": "error", "message": "Executor unavailable"}


@router.get(
    "/api/executor/quick-action",
    summary="Get Quick Action Status",
    description="Returns the status of any active quick action.",
)
async def get_quick_actions():
    executor = _get_executor()
    if not executor:
        return {"quick_action": None}
    # Check if executor has an active quick action attribute
    if hasattr(executor, "active_quick_action"):
        return {"quick_action": executor.active_quick_action}
    if hasattr(executor, "get_quick_action_status"):
        return {"quick_action": executor.get_quick_action_status()}
    return {"quick_action": None}


@router.post(
    "/api/executor/quick-action",
    summary="Set Quick Action",
    description="Activates a temporary override (quick action).",
)
async def set_quick_action(payload: QuickActionRequest):
    executor = _get_executor()
    if not executor:
        raise HTTPException(500, "Executor unavailable")

    # Try different method signatures
    if hasattr(executor, "set_quick_action"):
        executor.set_quick_action(payload.action, payload.duration_minutes, payload.params)
    elif hasattr(executor, "activate_quick_action"):
        executor.activate_quick_action(payload.action, payload.duration_minutes)
    return {"status": "success"}


@router.delete(
    "/api/executor/quick-action",
    summary="Clear Quick Action",
    description="Cancels any active quick action.",
)
async def clear_quick_action(action: str | None = None):
    executor = _get_executor()
    if not executor:
        raise HTTPException(500, "Executor unavailable")
    if hasattr(executor, "clear_quick_action"):
        if action:
            executor.clear_quick_action(action)
        else:
            executor.clear_quick_action()
    return {"status": "success"}


@router.post(
    "/api/executor/pause",
    summary="Pause Executor",
    description="Pauses the executor for a specified duration.",
)
async def pause_executor(payload: PauseRequest):
    executor = _get_executor()
    if not executor:
        raise HTTPException(500, "Executor unavailable")
    if hasattr(executor, "pause"):
        executor.pause(payload.duration_minutes)
        paused_until = getattr(executor, "paused_until", None)
        return {
            "status": "success",
            "paused_until": paused_until.isoformat() if paused_until else None,
        }
    return {"status": "error", "message": "Pause not supported"}


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
async def resume_executor():
    executor = _get_executor()
    if not executor:
        raise HTTPException(500, "Executor unavailable")
    if hasattr(executor, "resume"):
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
):
    executor = _get_executor()
    if not executor or not hasattr(executor, "history") or executor.history is None:
        return {"records": [], "count": 0}

    try:
        # Try the full get_history method like old webapp.py
        if hasattr(executor.history, "get_history"):
            success = None
            if success_only is not None:
                success = success_only.lower() in ("true", "1", "yes")
            records = executor.history.get_history(
                limit=limit,
                offset=offset,
                slot_start=slot_start,
                success_only=success,
            )
        elif hasattr(executor.history, "get_recent"):
            records = executor.history.get_recent(limit=limit)
        else:
            records = []
        return {"records": records, "count": len(records)}
    except Exception as e:
        logger.exception("Error getting executor history")
        return {"records": [], "count": 0, "error": str(e)}


@router.get(
    "/api/executor/stats",
    summary="Get Execution Statistics",
    description="Returns execution statistics over a specified period.",
)
async def get_stats(days: int = 7):
    executor = _get_executor()
    if not executor:
        return {}
    if hasattr(executor, "get_stats"):
        return executor.get_stats(days=days)
    if hasattr(executor, "history") and executor.history:
        return executor.history.get_stats(days=days)
    return {}


@router.get(
    "/api/executor/config",
    summary="Get Executor Config",
    description="Returns the current executor configuration.",
)
async def get_executor_config():
    """Return current executor configuration."""
    executor = _get_executor()
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
            "work_mode_entity": cfg.inverter.work_mode_entity if hasattr(cfg, "inverter") else None,
            "grid_charging_entity": cfg.inverter.grid_charging_entity
            if hasattr(cfg, "inverter")
            else None,
            "max_charging_current_entity": getattr(
                cfg.inverter, "max_charging_current_entity", None
            )
            if hasattr(cfg, "inverter")
            else None,
            "max_discharging_current_entity": getattr(
                cfg.inverter, "max_discharging_current_entity", None
            )
            if hasattr(cfg, "inverter")
            else None,
        }
        if hasattr(cfg, "inverter")
        else {},
        "water_heater": {
            "target_entity": cfg.water_heater.target_entity
            if hasattr(cfg, "water_heater")
            else None,
            "temp_normal": cfg.water_heater.temp_normal if hasattr(cfg, "water_heater") else None,
            "temp_off": cfg.water_heater.temp_off if hasattr(cfg, "water_heater") else None,
            "temp_boost": cfg.water_heater.temp_boost if hasattr(cfg, "water_heater") else None,
            "temp_max": cfg.water_heater.temp_max if hasattr(cfg, "water_heater") else None,
        }
        if hasattr(cfg, "water_heater")
        else {},
        "notifications": {
            "service": cfg.notifications.service if hasattr(cfg, "notifications") else None,
            "on_charge_start": getattr(cfg.notifications, "on_charge_start", False)
            if hasattr(cfg, "notifications")
            else False,
            "on_charge_stop": getattr(cfg.notifications, "on_charge_stop", False)
            if hasattr(cfg, "notifications")
            else False,
            "on_export_start": getattr(cfg.notifications, "on_export_start", False)
            if hasattr(cfg, "notifications")
            else False,
            "on_export_stop": getattr(cfg.notifications, "on_export_stop", False)
            if hasattr(cfg, "notifications")
            else False,
            "on_error": getattr(cfg.notifications, "on_error", False)
            if hasattr(cfg, "notifications")
            else False,
        }
        if hasattr(cfg, "notifications")
        else {},
    }


@router.put(
    "/api/executor/config",
    summary="Update Executor Config",
    description="Updates the executor configuration.",
)
async def update_executor_config(request: Request):
    """Update executor entity configuration."""
    from ruamel.yaml import YAML

    payload = await request.json()

    try:
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        with open("config.yaml", encoding="utf-8") as f:
            config = yaml_handler.load(f)

        if "executor" not in config:
            config["executor"] = {}

        executor_cfg = config["executor"]

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

        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_handler.dump(config, f)

        # Reload executor config
        executor = _get_executor()
        if executor and hasattr(executor, "reload_config"):
            executor.reload_config()

        return {"status": "success", "message": "Configuration updated"}

    except Exception as e:
        logger.exception("Failed to update executor config")
        raise HTTPException(500, str(e))


@router.get(
    "/api/executor/notifications",
    summary="Get Notification Settings",
    description="Returns current notification settings.",
)
async def get_notifications():
    """Get notification settings."""
    executor = _get_executor()
    if executor and hasattr(executor, "config") and hasattr(executor.config, "notifications"):
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
        from ruamel.yaml import YAML

        yaml_handler = YAML()
        with open("config.yaml", encoding="utf-8") as f:
            config = yaml_handler.load(f) or {}

        notify_cfg = config.get("executor", {}).get("notifications", {})
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
async def update_notifications(request: Request):
    """Update notification settings."""
    from ruamel.yaml import YAML

    payload = await request.json()

    try:
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        with open("config.yaml", encoding="utf-8") as f:
            config = yaml_handler.load(f)

        if "executor" not in config:
            config["executor"] = {}
        if "notifications" not in config["executor"]:
            config["executor"]["notifications"] = {}

        notify_cfg = config["executor"]["notifications"]
        for key, value in payload.items():
            notify_cfg[key] = value

        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_handler.dump(config, f)

        # Reload executor config
        executor = _get_executor()
        if executor and hasattr(executor, "reload_config"):
            executor.reload_config()

        return {"status": "success"}

    except Exception as e:
        logger.exception("Failed to update notifications")
        raise HTTPException(500, str(e))


@router.post(
    "/api/executor/notifications/test",
    summary="Test Notifications",
    description="Sends a test notification to verify configuration.",
)
async def test_notifications():
    """Send a test notification."""
    executor = _get_executor()
    if not executor:
        raise HTTPException(500, "Executor not available")

    try:
        if hasattr(executor, "send_notification"):
            executor.send_notification("Test", "This is a test notification from Darkstar")
            return {"status": "success", "message": "Test notification sent"}
        elif hasattr(executor, "notifier") and hasattr(executor.notifier, "send"):
            executor.notifier.send("Test", "This is a test notification from Darkstar")
            return {"status": "success", "message": "Test notification sent"}
        else:
            return {"status": "error", "message": "Notification sending not available"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get(
    "/api/executor/live",
    summary="Get Live Metrics",
    description="Returns real-time metrics from the executor.",
)
async def get_live():
    executor = _get_executor()
    if not executor:
        return {}
    if hasattr(executor, "get_live_metrics"):
        return executor.get_live_metrics()
    return {}
