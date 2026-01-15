"""
Debug API Router - Rev ARC1

Provides debug endpoints for logs, history, and diagnostics.
"""

import json
import logging
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import aiosqlite
import pytz
from fastapi import APIRouter, HTTPException, Query

from backend.learning import get_learning_engine
from inputs import get_dummy_load_profile, get_load_profile_from_ha, load_yaml

logger = logging.getLogger("darkstar.api.debug")

router = APIRouter(tags=["debug"])


# --- Ring Buffer for Logs ---
class RingBufferHandler(logging.Handler):
    """In-memory ring buffer for log entries that the UI can poll."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            timestamp = datetime.fromtimestamp(record.created, tz=UTC)
        except Exception:
            timestamp = datetime.now(UTC)
        entry = {
            "timestamp": timestamp.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self._buffer.append(entry)

    def get_logs(self) -> list[dict[str, Any]]:
        return list(self._buffer)


# Global ring buffer handler
_ring_buffer_handler = RingBufferHandler(maxlen=1000)
_ring_buffer_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
_ring_buffer_handler.setFormatter(_ring_buffer_formatter)

# Attach to root logger
root_logger = logging.getLogger()
if not any(isinstance(h, RingBufferHandler) for h in root_logger.handlers):
    root_logger.addHandler(_ring_buffer_handler)


@router.get(
    "/api/debug",
    summary="Get Planner Debug Data",
    description="Return comprehensive planner debug data from schedule.json.",
)
async def debug_data() -> dict[str, Any]:
    """Return comprehensive planner debug data from schedule.json."""
    try:
        schedule_path = Path("schedule.json")
        with schedule_path.open() as f:
            data = json.load(f)

        debug_section = data.get("debug", {})
        if not debug_section:
            return {
                "error": (
                    "No debug data available. "
                    "Enable debug mode in config.yaml with enable_planner_debug: true"
                )
            }

        return debug_section

    except FileNotFoundError as e:
        raise HTTPException(404, "schedule.json not found. Run the planner first.") from e


@router.get(
    "/api/debug/logs",
    summary="Get Server Logs",
    description="Return recent server logs stored in the ring buffer handler.",
)
async def debug_logs() -> dict[str, Any]:
    """Return recent server logs stored in the ring buffer handler."""
    try:
        return {"logs": _ring_buffer_handler.get_logs()}
    except Exception as exc:
        logger.exception("Failed to fetch debug logs")
        raise HTTPException(500, str(exc)) from exc


@router.get(
    "/api/history/soc",
    summary="Get Historic SoC",
    description="Return historic SoC data for today from learning database.",
)
async def historic_soc(date: str = Query("today")) -> dict[str, Any]:
    """Return historic SoC data for today from learning database."""
    try:
        tz = pytz.timezone("Europe/Stockholm")

        # Determine target date
        if date == "today":
            target_date = datetime.now(tz).date()
        else:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError as e:
                raise HTTPException(400, 'Invalid date format. Use YYYY-MM-DD or "today"') from e

        # Get learning engine and query historic SoC data
        engine = get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        async with aiosqlite.connect(db_path) as conn:
            query = """
                SELECT slot_start, soc_end_percent, quality_flags
                FROM slot_observations
                WHERE DATE(slot_start) = ?
                  AND soc_end_percent IS NOT NULL
                ORDER BY slot_start ASC
            """
            async with conn.execute(query, (target_date.isoformat(),)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return {
                "date": target_date.isoformat(),
                "slots": [],
                "message": "No historical SoC data available for this date",
            }

        # Convert to JSON format
        slots: list[dict[str, Any]] = []
        for row in rows:
            slots.append(
                {"timestamp": row[0], "soc_percent": row[1], "quality_flags": row[2] or ""}
            )

        return {"date": target_date.isoformat(), "slots": slots, "count": len(slots)}

    except Exception as e:
        logger.exception("Failed to fetch historical SoC data")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"Failed to fetch historical SoC data: {e!s}") from e


@router.get(
    "/api/performance/metrics",
    summary="Get Performance Metrics",
    description="Get performance metrics for charts.",
)
async def get_performance_metrics(days: int = Query(7, ge=1, le=90)) -> dict[str, Any]:
    """Get performance metrics for charts."""
    try:
        engine = get_learning_engine()
        data = cast("dict[str, Any]", engine.get_performance_series(days_back=days))  # type: ignore
        return data
    except Exception:
        logger.exception("Failed to get performance metrics")
        return {"soc_series": [], "cost_series": []}


@router.get(
    "/api/debug/load_profile",
    summary="Debug Load Profile",
    description="Debug endpoint to test HA load profile fetching.",
)
async def debug_load_profile() -> dict[str, Any]:
    """Debug endpoint to test HA load profile fetching."""
    try:
        conf = load_yaml("config.yaml") or {}
        try:
            profile = get_load_profile_from_ha(conf)
            return {
                "source": "ha",
                "profile_sum": sum(profile),
                "profile": profile,
                "message": "Successfully fetched from HA",
            }
        except Exception as e:
            dummy = get_dummy_load_profile(conf)
            return {
                "source": "dummy_fallback",
                "error": str(e),
                "profile_sum": sum(dummy),
                "profile": dummy,
                "message": "Failed to fetch from HA, used dummy",
            }
    except Exception as e:
        return {"error": f"Critical error: {e!s}"}


@router.get(
    "/api/ha-socket",
    summary="HA WebSocket Status",
    description="Diagnostic info about the Home Assistant WebSocket connection.",
)
async def ha_socket_status() -> dict[str, Any]:
    """Return HA WebSocket diagnostic info for debugging."""
    from backend.ha_socket import get_ha_socket_status

    return get_ha_socket_status()


@router.get(
    "/api/scheduler-debug",
    summary="Scheduler Debug Status",
    description="Comprehensive diagnostic info about the background scheduler.",
)
async def scheduler_debug_status() -> dict[str, Any]:
    """Return comprehensive scheduler diagnostic info for debugging."""
    from backend.services.scheduler_service import scheduler_service

    status = scheduler_service.status

    # Load config to show what scheduler reads
    try:
        config = load_yaml("config.yaml") or {}
        automation = config.get("automation", {})
        schedule_cfg = automation.get("schedule", {})
        scheduler_config = {
            "enabled_in_config": bool(automation.get("enable_scheduler", False)),
            "every_minutes": schedule_cfg.get("every_minutes", 60),
            "jitter_minutes": schedule_cfg.get("jitter_minutes", 0),
        }
    except Exception as e:
        scheduler_config = {"error": str(e)}

    return {
        "status": "running" if status.running else "stopped",
        "enabled": status.enabled,
        "enabled_in_config": scheduler_config.get("enabled_in_config", False),
        "schedule_config": scheduler_config,
        "runtime": {
            "last_run_at": status.last_run_at.isoformat() if status.last_run_at else None,
            "next_run_at": status.next_run_at.isoformat() if status.next_run_at else None,
            "last_run_status": status.last_run_status,
            "last_error": status.last_error,
            "current_task": status.current_task,
        },
        "diagnostics": {
            "now": datetime.now(UTC).isoformat(),
            "message": _get_scheduler_diagnostic_message(status, scheduler_config),
        },
    }


def _get_scheduler_diagnostic_message(status: Any, config: dict[str, Any]) -> str:
    """Generate a human-readable diagnostic message for scheduler state."""
    if not config.get("enabled_in_config", False):
        return "❌ Scheduler is DISABLED in config.yaml (automation.enable_scheduler: false)"
    if not status.running:
        return "⚠️ Scheduler task not running (should have started on app startup)"
    if not status.enabled:
        return "⚠️ Scheduler task is running but disabled flag is set"
    if status.last_run_status == "error":
        return f"⚠️ Last planner run failed: {status.last_error}"
    if status.last_run_at is None:
        return "🔄 Scheduler is enabled but hasn't run yet (waiting for first scheduled time)"
    return "✅ Scheduler is running normally"


@router.get(
    "/api/executor-debug",
    summary="Executor Debug Status",
    description="Comprehensive diagnostic info about the executor engine.",
)
async def executor_debug_status() -> dict[str, Any]:
    """Return comprehensive executor diagnostic info for debugging."""
    from backend.api.routers.executor import get_executor_instance

    executor = get_executor_instance()

    if executor is None:
        return {
            "status": "not_initialized",
            "error": "Executor failed to initialize - check logs for import/config errors",
            "diagnostics": {
                "now": datetime.now(UTC).isoformat(),
                "message": "❌ Executor could not be initialized (check Python errors in logs)",
            },
        }

    # Get executor config
    cfg = executor.config
    ha_client = executor.ha_client

    # Check thread status
    thread_alive = executor._thread is not None and executor._thread.is_alive()

    # Load config to compare
    try:
        config = load_yaml("config.yaml") or {}
        executor_cfg = config.get("executor", {})
        config_enabled = executor_cfg.get("enabled", False)
    except Exception:
        executor_cfg = {}
        config_enabled = "unknown"

    return {
        "status": "running" if thread_alive else "stopped",
        "enabled": cfg.enabled,
        "enabled_in_config": config_enabled,
        "shadow_mode": cfg.shadow_mode,
        "ha_client_initialized": ha_client is not None,
        "config": {
            "interval_seconds": cfg.interval_seconds,
            "automation_toggle_entity": cfg.automation_toggle_entity,
            "soc_target_entity": cfg.soc_target_entity,
            "has_battery": cfg.has_battery,
            "has_water_heater": cfg.has_water_heater,
        },
        "entities": {
            "work_mode_entity": cfg.inverter.work_mode_entity,
            "grid_charging_entity": cfg.inverter.grid_charging_entity,
            "water_target_entity": cfg.water_heater.target_entity,
        },
        "runtime": {
            "thread_alive": thread_alive,
            "is_paused": executor.is_paused,
            "last_run_at": executor.status.last_run_at,
            "last_run_status": executor.status.last_run_status,
            "last_error": executor.status.last_error,
            "next_run_at": executor.status.next_run_at,
            "current_slot": executor.status.current_slot,
            "override_active": executor.status.override_active,
            "quick_action": executor.get_active_quick_action(),
        },
        "recent_errors": list(executor.recent_errors) if executor.recent_errors else [],
        "diagnostics": {
            "now": datetime.now(UTC).isoformat(),
            "message": _get_executor_diagnostic_message(executor, cfg, thread_alive, config_enabled),
        },
    }


def _get_executor_diagnostic_message(
    executor: Any, cfg: Any, thread_alive: bool, config_enabled: Any
) -> str:
    """Generate a human-readable diagnostic message for executor state."""
    if not config_enabled:
        return "❌ Executor is DISABLED in config.yaml (executor.enabled: false)"
    if not cfg.enabled:
        return "⚠️ Executor config.enabled is false (may need reload)"
    if not thread_alive:
        return "⚠️ Executor is enabled but background thread is not running"
    if executor.ha_client is None:
        return "⚠️ HA client not initialized - check secrets.yaml for home_assistant.url and token"
    if executor.is_paused:
        return "⏸️ Executor is PAUSED (user-initiated)"
    if executor.status.last_run_status == "error":
        return f"⚠️ Last executor run failed: {executor.status.last_error}"
    if executor.status.last_run_at is None:
        return "🔄 Executor is enabled but hasn't run yet"
    return "✅ Executor is running normally"
