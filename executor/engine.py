"""
Executor Engine

The main executor loop that orchestrates:
1. Reading the current slot from schedule.json
2. Gathering system state from Home Assistant (async)
3. Evaluating overrides
4. Making controller decisions
5. Executing actions (async)
6. Logging execution history

Async Architecture:
- All HA communication is async using aiohttp (non-blocking)
- Executor continues processing even when HA is slow/unresponsive
- 5-second timeout prevents indefinite hangs
- Automatic retry with exponential backoff for transient errors
"""

import asyncio
import collections
import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz

# import yaml
# Import existing HA config loader
from backend.core.secrets import load_home_assistant_config
from backend.loads.service import LoadDisaggregator

from .actions import ActionDispatcher, ActionResult, HAClient
from .config import load_executor_config, load_yaml
from .controller import ControllerDecision, make_decision
from .history import ExecutionHistory, ExecutionRecord
from .override import (
    OverrideResult,
    SlotPlan,
    SystemState,
    evaluate_overrides,
)

logger = logging.getLogger(__name__)

EXECUTOR_VERSION = "1.0.0"


@dataclass
class EVChargerState:
    """Per-device EV charger runtime state."""

    charging_active: bool = False
    charging_started_at: datetime | None = None
    charging_slot_end: datetime | None = None


@dataclass
class ExecutorStatus:
    """Current runtime state of the executor."""

    enabled: bool = False
    shadow_mode: bool = False
    is_paused: bool = False
    last_run_at: datetime | None = None
    last_run_status: str = "pending"  # "pending", "success", "error", "skipped"
    last_error: str | None = None
    last_skip_reason: str | None = None  # NEW: Explain why we skipped
    next_run_at: datetime | None = None
    ha_client_initialized: bool = False
    current_slot: str | None = None
    last_action: str | None = None
    override_active: bool = False
    override_type: str | None = None
    profile_name: str | None = None
    profile_error: str | None = None


class ExecutorEngine:
    """
    Main executor engine that runs the execution loop.

    Replaces the n8n Helios Executor with a native Python implementation.
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        secrets_path: str = "secrets.yaml",
    ):
        self.config_path = config_path
        self.secrets_path = secrets_path
        self.config = load_executor_config(config_path)

        # Load main config for input_sensors section
        self._full_config = load_yaml(config_path)

        # Status tracking - MUST be initialized BEFORE profile loading (REV IP3 Phase 6 fix)
        self.status = ExecutorStatus(
            enabled=self.config.enabled,
            shadow_mode=self.config.shadow_mode,
        )

        # Load inverter profile (REV ARC13 Phase 1)
        from .profiles import get_profile_from_config

        try:
            self.inverter_profile = get_profile_from_config(self._full_config)
            self.status.profile_name = self.inverter_profile.metadata.name
            logger.info(
                "Loaded inverter profile: %s v%s (%s)",
                self.inverter_profile.metadata.name,
                self.inverter_profile.metadata.version,
                ", ".join(self.inverter_profile.metadata.supported_brands),
            )

            # Check for missing required entities (REV ARC13 Phase 3)
            missing = self.inverter_profile.get_missing_entities(self._full_config)
            if missing:
                error_msg = f"Profile incomplete. Missing sensors: {', '.join(missing)}"
                self.status.profile_error = error_msg
                logger.warning(
                    "⚠️ Inverter profile '%s' configuration incomplete. Missing required entities: %s",
                    self.inverter_profile.metadata.name,
                    ", ".join(missing),
                )
        except Exception as e:
            logger.error("Failed to load inverter profile: %s", e)
            self.status.profile_error = str(e)
            self.status.profile_name = "generic"  # Fallback
            # Set profile to None - executor will use existing hardcoded behavior
            self.inverter_profile = None

        # Validate export power entity is configured when export is enabled
        export_config = self._full_config.get("export", {})
        if export_config.get("enable_export", True):
            inv_config = self._full_config.get("executor", {}).get("inverter", {})
            export_power_entity = inv_config.get("grid_max_export_power") or inv_config.get(
                "grid_max_export_power_entity"
            )
            if not export_power_entity:
                logger.warning(
                    "⚠️ Export enabled but no export power entity configured. "
                    "Grid export will not work properly. "
                    "Configure 'grid_max_export_power' in executor.inverter section."
                )

        # Initialize components
        self.history = ExecutionHistory(
            db_path=self._get_db_path(),
            timezone=self.config.timezone,
        )

        self.ha_client: HAClient | None = None
        self.dispatcher: ActionDispatcher | None = None

        # Threading
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Quick action storage (user-initiated time-limited overrides)
        self._quick_action: dict[str, Any] | None = None  # {type, expires_at, reason}

        # Pause state (idle mode with reminder)
        self._paused_at: datetime | None = None
        self._pause_reminder_sent: bool = False

        # Water boost state
        self._water_boost_until: datetime | None = None
        self._last_boost_state: dict[str, Any] | None = None  # Track changes for WebSocket
        self._last_boost_broadcast: float = 0.0  # Timestamp of last periodic broadcast

        # Override notification deduplication (Issue 3 fix)
        self._last_override_type: str | None = None

        # D3: Stale-schedule alert pending (set by _load_current_slot, consumed in _tick)
        self._stale_schedule_warning: str | None = None
        self._stale_schedule_alerted: bool = False  # dedup: fire once per fresh→stale transition

        # Cached system state for get_status() mode_intent computation
        self._last_system_state: SystemState | None = None

        # System profile toggles (Rev O1)
        system_cfg = self._full_config.get("system", {})
        self._has_solar = system_cfg.get("has_solar", True)
        self._has_battery = system_cfg.get("has_battery", True)
        self._has_water_heater = system_cfg.get("has_water_heater", True)
        self._has_ev_charger = system_cfg.get("has_ev_charger", False)

        # Per-device EV charging state tracking
        self._ev_charger_states: dict[str, EVChargerState] = {}

        # REV F76 Phase 5: Smart logging state tracking (Issue 4 fix)
        self._ev_detected_last_tick = False

        # REV F76 Phase 5: Fail-safe error tracking (Issue 1 fix)
        self._ev_power_fetch_failed = False

        # EV charge failure detection
        self._ev_zero_power_ticks: int = 0
        self._ev_failure_notified: bool = False

        # Recent errors tracking (Phase 3)
        self.recent_errors: collections.deque[dict[str, Any]] = collections.deque(maxlen=10)

        # Load disaggregator for EV power monitoring (REV F76)
        self._load_disaggregator = LoadDisaggregator(self._full_config)

        # Async background tasks reference (RUF006 fix)
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Config and profile mtime caching
        self._config_mtime: float | None = None
        self._profile_mtime: float | None = None

    def _get_db_path(self) -> str:
        """Get the path to the learning database."""
        # Use the same database as the learning engine
        return str(Path("data") / "planner_learning.db")

    def init_ha_client(self) -> bool:
        """Initialize the Home Assistant client."""
        # Use existing HA config loader from inputs.py
        ha_config = load_home_assistant_config()

        if not ha_config:
            logger.error("No Home Assistant configuration found in secrets.yaml")
            self.status.ha_client_initialized = False
            return False

        base_url = ha_config.get("url", "")
        token = ha_config.get("token", "")

        if not base_url or not token:
            logger.error("Missing HA URL or token in secrets")
            self.status.ha_client_initialized = False
            return False

        self.ha_client = HAClient(base_url, token)
        self.dispatcher = ActionDispatcher(
            self.ha_client,
            self.config,
            shadow_mode=self.config.shadow_mode,
            profile=self.inverter_profile,
        )
        self.status.ha_client_initialized = True
        return True

    def reload_config(self) -> None:
        """Reload configuration from config.yaml with mtime-based caching."""
        current_config_mtime = Path(self.config_path).stat().st_mtime
        if self._config_mtime is not None and current_config_mtime == self._config_mtime:
            return

        with self._lock:
            self.config = load_executor_config(self.config_path)
            self._full_config = load_yaml(self.config_path)
            self._config_mtime = current_config_mtime
            self.status.enabled = self.config.enabled
            self.status.shadow_mode = self.config.shadow_mode
            if self.dispatcher:
                self.dispatcher.shadow_mode = self.config.shadow_mode

            system_cfg = self._full_config.get("system", {})
            self._has_water_heater = system_cfg.get("has_water_heater", True)
            self._has_ev_charger = system_cfg.get("has_ev_charger", False)

            # Reload inverter profile if changed (REV FIX: Profile switch now takes effect immediately)
            from .profiles import get_profile_from_config

            try:
                profile_name = self._full_config.get("system", {}).get(
                    "inverter_profile", "generic"
                )
                profile_path = Path("profiles") / f"{profile_name}.yaml"

                # Check profile mtime
                should_reload_profile = True
                if profile_path.exists():
                    current_profile_mtime = profile_path.stat().st_mtime
                    if (
                        self._profile_mtime is not None
                        and current_profile_mtime == self._profile_mtime
                    ):
                        should_reload_profile = False
                    else:
                        self._profile_mtime = current_profile_mtime

                if should_reload_profile:
                    new_profile = get_profile_from_config(self._full_config)
                    if (
                        new_profile.metadata.name != self.inverter_profile.metadata.name
                        if self.inverter_profile
                        else True
                    ):
                        self.inverter_profile = new_profile
                        self.status.profile_name = new_profile.metadata.name
                        self.status.profile_error = None
                        if self.dispatcher:
                            self.dispatcher.profile = new_profile
                        logger.info(
                            "Inverter profile reloaded: %s v%s (%s)",
                            new_profile.metadata.name,
                            new_profile.metadata.version,
                            ", ".join(new_profile.metadata.supported_brands),
                        )
            except Exception as e:
                logger.error("Failed to reload inverter profile during config reload: %s", e)
                self.status.profile_error = str(e)

            logger.info("Executor config reloaded")

    def get_status(self) -> dict[str, Any]:
        """Get current executor status as a dictionary."""
        # Get current slot plan for display
        current_slot_plan = None
        try:
            tz = pytz.timezone(self.config.timezone)
            now = datetime.now(tz)
            slot, slot_start = self._load_current_slot(now)
            if slot:
                # Compute mode_intent using cached system state
                mode_intent = None
                try:
                    if self._last_system_state is not None and self.inverter_profile is not None:
                        decision = make_decision(
                            slot,
                            self._last_system_state,
                            config=self.config.controller,
                            inverter_config=self.config.inverter,
                            water_heater_config=self.config.water_heater,
                            water_heater_devices=self.config.water_heater_devices,
                            profile=self.inverter_profile,
                        )
                        mode_intent = decision.mode_intent
                except Exception as e:
                    logger.debug("Could not compute mode_intent for status: %s", e)

                current_slot_plan = {
                    "slot_start": slot_start,
                    "charge_kw": slot.charge_kw,
                    "export_kw": slot.export_kw,
                    "water_kw": slot.water_kw,
                    "discharge_kw": slot.discharge_kw,
                    "ev_charging_kw": slot.ev_charging_kw,
                    "ev_charger_plans": slot.ev_charger_plans,
                    "water_heater_plans": slot.water_heater_plans,
                    "soc_target": slot.soc_target,
                    "soc_projected": slot.soc_projected,
                    "mode_intent": mode_intent,
                }
        except Exception as e:
            logger.debug("Could not load current slot plan: %s", e)

        # Get statuses BEFORE acquiring lock (they have their own locks)
        quick_action_status = self._get_quick_action_status()
        pause_status = self.get_pause_status()
        water_boost_status = self.get_water_boost_status()

        with self._lock:
            return {
                "enabled": self.status.enabled,
                "shadow_mode": self.status.shadow_mode,
                "last_run_at": (
                    self.status.last_run_at.isoformat() if self.status.last_run_at else None
                ),
                "last_run_status": self.status.last_run_status,
                "last_error": self.status.last_error,
                "last_skip_reason": self.status.last_skip_reason,
                "next_run_at": (
                    self.status.next_run_at.isoformat() if self.status.next_run_at else None
                ),
                "current_slot": self.status.current_slot,
                "current_slot_plan": current_slot_plan,
                "last_action": self.status.last_action,
                "override_active": self.status.override_active,
                "override_type": self.status.override_type,
                "profile_name": self.status.profile_name,
                "profile_error": self.status.profile_error,
                "quick_action": quick_action_status,
                "paused": pause_status,
                "water_boost": water_boost_status,
                "recent_errors": list(self.recent_errors),
                "version": EXECUTOR_VERSION,
            }

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """Get execution statistics."""
        return self.history.get_stats(days=days)

    async def get_live_metrics(self) -> dict[str, Any]:
        """
        Get live system metrics for API.

        Returns a snapshot of current system power flows and state.
        """
        # Start with standard system state
        state = await self._gather_system_state()

        metrics = {
            "soc": state.current_soc_percent,
            "pv_kw": state.current_pv_kw,
            "load_kw": state.current_load_kw,
            "grid_import_kw": state.current_import_kw,
            "grid_export_kw": state.current_export_kw,
            "battery_kw": 0.0,
            "water_kw": 0.0,
            "timestamp": datetime.now(pytz.timezone(self.config.timezone)).isoformat(),
        }

        # Add extra sensors not in SystemState
        if self.ha_client:
            input_sensors = self._full_config.get("input_sensors", {})

            # Battery Power
            batt_pwr_entity = input_sensors.get("battery_power")
            if batt_pwr_entity:
                val = await self.ha_client.get_state_value(batt_pwr_entity)
                if val and val not in ("unknown", "unavailable"):
                    with contextlib.suppress(ValueError):
                        metrics["battery_kw"] = float(val) / 1000.0  # W to kW

            # Water Heater Power (ARC15: read from water_heaters[] array, sum across enabled)
            if self._has_water_heater:
                water_heaters_array = self._full_config.get("water_heaters", [])
                total_water_kw = 0.0
                for heater in cast("list[dict[str, Any]]", water_heaters_array):
                    sensor_entity = heater.get("sensor")
                    if heater.get("enabled", True) and sensor_entity:
                        val = await self.ha_client.get_state_value(sensor_entity)
                        if val and val not in ("unknown", "unavailable"):
                            with contextlib.suppress(ValueError):
                                total_water_kw += float(val) / 1000.0  # W to kW
                if total_water_kw > 0:
                    metrics["water_kw"] = total_water_kw

        return metrics

    def _get_quick_action_status(self) -> dict[str, Any] | None:
        """Get current quick action status with remaining time."""
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            if not self._quick_action:
                return None

            expires_at = datetime.fromisoformat(self._quick_action["expires_at"])
            if now >= expires_at:
                # Expired
                self._quick_action = None
                return None

            remaining = (expires_at - now).total_seconds() / 60
            return {
                "type": self._quick_action["type"],
                "expires_at": self._quick_action["expires_at"],
                "remaining_minutes": round(remaining, 1),
                "reason": self._quick_action.get("reason", ""),
                "params": self._quick_action.get("params", {}),
            }

    def set_quick_action(
        self,
        action_type: str,
        duration_minutes: int,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Set a time-limited quick action override.

        Args:
            action_type: One of 'force_charge', 'force_export', 'force_stop'
            duration_minutes: How long the override should last (15, 30, 60)
            params: Optional parameters (e.g., {'target_soc': 80})

        Returns:
            Status dict with expires_at
        """
        valid_types = ["force_charge", "force_export", "force_stop", "force_heat"]
        if action_type not in valid_types:
            raise ValueError(f"Invalid action type: {action_type}. Must be one of {valid_types}")

        if duration_minutes not in [15, 30, 60]:
            raise ValueError(f"Invalid duration: {duration_minutes}. Must be 15, 30, or 60 minutes")

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        expires_at = now + timedelta(minutes=duration_minutes)

        with self._lock:
            self._quick_action = {
                "type": action_type,
                "expires_at": expires_at.isoformat(),
                "reason": f"User activated {action_type} for {duration_minutes} minutes",
                "created_at": now.isoformat(),
                "params": params or {},
            }

        logger.info(
            "Quick action set: %s for %d minutes (expires %s)",
            action_type,
            duration_minutes,
            expires_at.isoformat(),
        )

        return {
            "success": True,
            "type": action_type,
            "duration_minutes": duration_minutes,
            "expires_at": expires_at.isoformat(),
        }

    def clear_quick_action(self) -> dict[str, Any]:
        """Clear any active quick action."""
        with self._lock:
            was_active = self._quick_action is not None
            self._quick_action = None

        if was_active:
            logger.info("Quick action cleared by user")

        return {"success": True, "was_active": was_active}

    def get_active_quick_action(self) -> dict[str, Any] | None:
        """Get the currently active quick action, if any and not expired."""
        return self._get_quick_action_status()

    # --- Pause/Resume (Idle Mode) ---

    @property
    def is_paused(self) -> bool:
        """Check if executor is currently paused."""
        with self._lock:
            return self._paused_at is not None

    def pause(self, duration_minutes: int = 60) -> dict[str, Any]:
        """
        Pause the executor - stops all automated control.

        IMPORTANT: When paused, the executor simply stops making writes to HA entities.
        The inverter REMAINS in its current state (not forced to idle mode).
        This allows the user to manually control devices via HA without interference.

        A reminder notification will be sent after the configured duration.
        """
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            if self._paused_at is not None:
                return {
                    "success": False,
                    "error": "Already paused",
                    "paused_at": self._paused_at.isoformat(),
                }

            self._paused_at = now
            self._pause_reminder_sent = False
            self.status.is_paused = True

        logger.info("Executor PAUSED at %s - manual control enabled", now.isoformat())

        # NOTE: We do NOT apply idle mode or any settings when pausing.
        # The inverter stays in its current state, allowing user to manually override.
        # This was an intentional design decision (REV F21).

        return {
            "success": True,
            "paused_at": now.isoformat(),
            "message": "Executor paused - you have full manual control",
        }

    def resume(self, token: str | None = None) -> dict[str, Any]:
        """
        Resume the executor from paused state.

        Args:
            token: Optional security token for webhook-based resume (future use)
        """
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            if self._paused_at is None:
                return {"success": False, "error": "Not paused"}

            paused_duration = (now - self._paused_at).total_seconds() / 60
            self._paused_at = None
            self._pause_reminder_sent = False
            self.status.is_paused = False

        logger.info("Executor RESUMED after %.1f minutes paused", paused_duration)

        # Trigger immediate tick to apply scheduled action without waiting
        try:
            # Trigger immediate tick to apply scheduled action without waiting
            try:
                # Issue 0 Fix: Use create_task for async tick execution
                loop = asyncio.get_running_loop()
                task: asyncio.Task[Any] = loop.create_task(self._tick())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                logger.info("Immediate tick scheduled after resume")
            except RuntimeError:
                # If called from a sync context without a loop (unlikely in FastAPI but possible in tests)
                logger.warning("Could not schedule immediate tick: no running event loop")
        except Exception as e:
            logger.warning("Failed to run immediate tick after resume: %s", e)

        return {
            "success": True,
            "resumed_at": now.isoformat(),
            "paused_duration_minutes": round(paused_duration, 1),
            "message": "Executor resumed - action applied immediately",
        }

    def get_pause_status(self) -> dict[str, Any] | None:
        """Get pause status with duration if paused."""
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            if self._paused_at is None:
                return None

            duration = (now - self._paused_at).total_seconds() / 60
            return {
                "paused_at": self._paused_at.isoformat(),
                "paused_minutes": round(duration, 1),
                "reminder_sent": self._pause_reminder_sent,
            }

    async def _check_pause_reminder(self) -> None:
        """Check if 30-minute pause reminder should be sent."""
        if not self.config.pause_reminder_minutes:
            return

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        paused_at: datetime | None = None
        with self._lock:
            if self._paused_at is None or self._pause_reminder_sent:
                return

            paused_minutes = (now - self._paused_at).total_seconds() / 60
            if paused_minutes >= self.config.pause_reminder_minutes:
                self._pause_reminder_sent = True
                paused_at = self._paused_at

        # Send reminder notification (outside lock)
        if self.dispatcher and paused_at:
            await self._send_pause_reminder(paused_at)

    async def _send_pause_reminder(self, paused_at: datetime) -> None:
        """Send pause reminder notification with resume action."""
        if not self.dispatcher:
            return

        try:
            message = (
                f"⚠️ Executor has been paused for {self.config.pause_reminder_minutes} minutes. "
                f"Paused since {paused_at.strftime('%H:%M')}."
            )

            # Send via ActionDispatcher
            await self.dispatcher._send_notification(  # type: ignore[protected-access]
                message,
                title="Darkstar Executor Paused",
            )
            logger.info("Pause reminder notification sent")
        except Exception as e:
            logger.error("Failed to send pause reminder: %s", e)

    async def send_notification(
        self, title: str, message: str, data: dict[str, Any] | None = None
    ) -> bool:
        """Send a notification via the configured service."""
        if not self.dispatcher:
            return False

        try:
            await self.dispatcher._send_notification(message, title=title)  # type: ignore[protected-access]
            # If data is provided, we might need a more direct HA call
            # since _send_notification is simplified
            if data and self.ha_client:
                await self.ha_client.send_notification(
                    self.config.notifications.service, title, message, data=data
                )
            return True
        except Exception as e:
            logger.error("Failed to send notification: %s", e)
            return False

    # --- Water Boost ---

    def set_water_boost(self, duration_minutes: int) -> dict[str, Any]:
        """
        Start water heater boost (heat to 65°C for specified duration).

        Args:
            duration_minutes: Duration in minutes (30, 60, or 120)

        Returns:
            Status dict with expires_at
        """
        # Rev O1: Skip if no water heater configured
        if not self._has_water_heater:
            return {
                "success": False,
                "error": "No water heater configured in system profile",
            }

        valid_durations = [30, 60, 120]
        if duration_minutes not in valid_durations:
            raise ValueError(
                f"Invalid duration: {duration_minutes}. Must be one of {valid_durations}"
            )

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        expires_at = now + timedelta(minutes=duration_minutes)

        with self._lock:
            self._water_boost_until = expires_at

        logger.info(
            "Water boost started for %d minutes (until %s)",
            duration_minutes,
            expires_at.isoformat(),
        )

        # Immediately apply the boost
        if self.ha_client and self.dispatcher:
            try:
                # Schedule async water temp setting
                loop = asyncio.get_running_loop()
                task: asyncio.Task[Any] = loop.create_task(
                    self.dispatcher.set_water_temp(self.config.water_heater.temp_boost)
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                logger.warning("Could not apply water boost: no running event loop")
            except Exception as e:
                logger.error("Failed to apply water boost: %s", e)

        # Emit WebSocket event
        self._emit_water_boost_status(force=True)

        return {
            "success": True,
            "expires_at": expires_at.isoformat(),
            "duration_minutes": duration_minutes,
            "temp_target": self.config.water_heater.temp_boost,
        }

    def clear_water_boost(self) -> dict[str, Any]:
        """Cancel active water boost."""
        with self._lock:
            was_active = self._water_boost_until is not None
            self._water_boost_until = None

        if was_active:
            logger.info("Water boost cancelled by user")
            # Set water temp back to normal
            if self.dispatcher:
                try:
                    # Schedule async water temp setting
                    loop = asyncio.get_running_loop()
                    task: asyncio.Task[Any] = loop.create_task(
                        self.dispatcher.set_water_temp(self.config.water_heater.temp_off)
                    )
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                except RuntimeError:
                    logger.warning("Could not reset water temp: no running event loop")
                except Exception as e:
                    logger.error("Failed to reset water temp: %s", e)

            # Emit WebSocket event
            self._emit_water_boost_status(force=True)

        return {"success": True, "was_active": was_active}

    def get_water_boost_status(self) -> dict[str, Any] | None:
        """Get water boost status with remaining time."""
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            if self._water_boost_until is None:
                return None

            if now >= self._water_boost_until:
                # Expired
                self._water_boost_until = None
                return None

            remaining_seconds = int((self._water_boost_until - now).total_seconds())
            return {
                "expires_at": self._water_boost_until.isoformat(),
                "remaining_seconds": remaining_seconds,
                "temp_target": self.config.water_heater.temp_boost,
            }

    def _emit_water_boost_status(self, force: bool = False) -> None:
        """Emit water boost status via WebSocket if changed or forced."""
        from backend.core.websockets import ws_manager

        current_status = self.get_water_boost_status()

        # Build event payload
        if current_status:
            payload = {
                "active": True,
                "expires_at": current_status["expires_at"],
                "remaining_seconds": current_status["remaining_seconds"],
            }
        else:
            payload = {"active": False, "expires_at": None, "remaining_seconds": 0}

        # Check if status changed or periodic broadcast needed
        status_changed = self._last_boost_state != payload
        now = time.time()
        periodic_broadcast_due = (now - self._last_boost_broadcast) >= 30.0

        if status_changed or force or periodic_broadcast_due:
            try:
                ws_manager.emit_sync("water_boost_updated", payload)
                self._last_boost_state = payload.copy()
                self._last_boost_broadcast = now
                logger.debug(f"Water boost status emitted: {payload}")
            except Exception as e:
                logger.warning(f"Failed to emit water boost status: {e}")

    def start(self) -> None:
        """Start the executor loop in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Executor already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Executor started (interval: %ds)", self.config.interval_seconds)

    def stop(self) -> None:
        """Stop the executor loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("Executor stopped")

    async def run_once(self) -> dict[str, Any]:
        """
        Run a single execution tick synchronously.

        Returns the execution result.
        """
        if not self.ha_client and not self.init_ha_client():
            return {"success": False, "error": "Failed to initialize HA client"}

        return await self._tick()

    def _run_loop(self) -> None:
        """Main execution loop running in background thread."""
        try:
            asyncio.run(self._async_run_loop())
        except Exception as e:
            logger.exception("Fatal error in executor background loop: %s", e)

    async def _async_run_loop(self) -> None:
        """Async implementation of the background loop."""
        tz = pytz.timezone(self.config.timezone)
        logger.info("Executor background loop started (async)")

        # Initialize HA client inside the async loop (not in main thread)
        if not self.ha_client and not self.init_ha_client():
            logger.error("Failed to initialize HA client, executor shutting down")
            return

        try:
            while not self._stop_event.is_set():
                # Reload config to get latest settings
                self.reload_config()

                # Check if enabled
                if not self.config.enabled:
                    logger.debug("Executor disabled in config, sleeping")
                    self.status.last_skip_reason = "disabled_in_config"
                    await asyncio.sleep(10)  # Check every 10s
                    continue

                # Check if paused
                if self.is_paused:
                    logger.debug("Executor paused, sleeping")
                    self.status.last_skip_reason = "paused_by_user"
                    await asyncio.sleep(10)
                    continue

                # Calculate next run time
                now = datetime.now(tz)
                next_run = self._compute_next_run(now)
                self.status.next_run_at = next_run

                # Wait until next run time
                wait_seconds = (next_run - now).total_seconds()
                if wait_seconds > 1:  # Only wait if more than 1s
                    logger.debug(
                        "Waiting %.1fs until next run at %s",
                        wait_seconds,
                        next_run.isoformat(),
                    )
                    # Async wait with check for stop event
                    # We can't easily "wait on event" in async without an async event
                    # So we sleep in chunks or just sleep.
                    # Since _stop_event is threading.Event, we can't await it directly.
                    # We'll just sleep. If stop event is set, loop checks at top.
                    # To be more responsive, we could sleep in small increments, but
                    # strictly sticking to asyncio.sleep is fine for now.

                    # Correction: We should check stop_event periodically if wait is long
                    # But since we are inside asyncio.run(), the threading event set from outside
                    # is the signaling mechanism.

                    # Let's use a small loop for responsiveness
                    end_wait = time.time() + wait_seconds
                    while time.time() < end_wait:
                        if self._stop_event.is_set():
                            return
                        sleep_time = min(1.0, end_wait - time.time())
                        await asyncio.sleep(sleep_time)

                    # Re-check current time after waiting
                    now = datetime.now(tz)

                # Prevent double execution - check if we ran recently
                if self.status.last_run_at:
                    try:
                        last_run = self.status.last_run_at
                        # Skip if we ran within the last interval minus a buffer
                        min_interval = self.config.interval_seconds - 30  # 30s buffer
                        seconds_since_last = (now - last_run).total_seconds()
                        if seconds_since_last < min_interval:
                            logger.debug(
                                "Skipping - already ran %.0fs ago (min interval: %ds)",
                                seconds_since_last,
                                min_interval,
                            )
                            self.status.last_run_status = "skipped"
                            self.status.last_skip_reason = "already_ran_recently"
                            # Don't tight-loop - wait until next boundary
                            continue  # Will recalculate next_run on next iteration
                    except Exception as e:
                        logger.debug("Could not parse last_run_at: %s", e)

                # Execute tick
                try:
                    tick_start = datetime.now(tz)
                    logger.info("Executing scheduled tick at %s", tick_start.isoformat())

                    # The Core Fix: await the async tick
                    await self._tick()

                    tick_duration = (datetime.now(tz) - tick_start).total_seconds()

                    # Rev PERF2: Performance Logging
                    if tick_duration > 1.0:
                        logger.warning(
                            "\u26a0\ufe0f SLOW TICK: %.2fs (Threshold: 1.0s)", tick_duration
                        )
                    else:
                        logger.info("Tick completed in %.2fs", tick_duration)
                except Exception as e:
                    logger.exception("Executor tick failed: %s", e)
                    self.status.last_run_status = "error"
                    self.status.last_error = str(e)

                # No fixed sleep - next iteration will calculate proper wait time
                # This eliminates drift and ensures alignment to interval boundaries
        finally:
            for task in list(self._background_tasks):
                task.cancel()
            if self._background_tasks:
                await asyncio.gather(*self._background_tasks, return_exceptions=True)
            if self.ha_client:
                try:
                    await self.ha_client.close()
                    logger.info("HA client session closed")
                except Exception:
                    logger.warning("Failed to close HA client session", exc_info=True)

        logger.info("Executor background loop stopped")

    def _compute_next_run(self, now: datetime) -> datetime:
        """Compute the next execution time based on interval."""
        # interval = timedelta(seconds=self.config.interval_seconds)

        # Align to interval boundaries (e.g., on the 5-minute mark)
        epoch = datetime(2000, 1, 1, tzinfo=now.tzinfo)
        elapsed = (now - epoch).total_seconds()
        intervals_passed = elapsed // self.config.interval_seconds
        next_boundary = epoch + timedelta(
            seconds=(intervals_passed + 1) * self.config.interval_seconds
        )

        return next_boundary

    async def _tick(self) -> dict[str, Any]:
        """
        Execute one tick of the executor loop.

        This is the core logic:
        1. Check automation toggle
        2. Load current slot from schedule.json
        3. Gather system state
        4. Evaluate overrides
        5. Make controller decision
        6. Execute actions
        7. Log execution
        """
        start_time = time.time()
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        now_iso = now.isoformat()

        logger.info("Executor tick started at %s", now_iso)
        self.status.last_run_at = now

        result: dict[str, Any] = {
            "success": True,
            "executed_at": now_iso,
            "slot_start": None,
            "actions": [],
            "override": None,
            "error": None,
        }

        try:
            # 0. Check pause state first
            if self.is_paused:
                # Rev update: Do NOT re-apply idle mode here.
                # Only apply it once when pause() is called.
                # This allows the user to manually control devices while paused.
                logger.debug("Executor is PAUSED - skipping tick")
                await self._check_pause_reminder()

                self.status.last_run_status = "skipped"
                self.status.last_skip_reason = "paused_idle_mode"
                result["success"] = True
                result["actions"] = [{"type": "skip", "reason": "paused_idle_mode"}]
                return result

            # 1. Check automation toggle (Rev O1)
            if self.config.automation_toggle_entity and self.ha_client:
                toggle_state = await self.ha_client.get_state_value(
                    self.config.automation_toggle_entity
                )
                if toggle_state and toggle_state.lower() != "on":
                    logger.warning(
                        "Executor skip: Automation toggle (%s) is %s",
                        self.config.automation_toggle_entity,
                        toggle_state,
                    )
                    self.status.last_run_status = "skipped"
                    self.status.last_skip_reason = f"automation_toggle_off ({toggle_state})"
                    return {
                        "success": True,
                        "executed_at": now_iso,
                        "actions": [
                            {
                                "type": "skip",
                                "reason": "automation_disabled",
                                "message": (
                                    f"Toggle {self.config.automation_toggle_entity} "
                                    f"is {toggle_state}"
                                ),
                            }
                        ],
                    }

            self.status.last_skip_reason = None  # Reset if we proceed

            # 2. Load current slot from schedule.json
            slot, slot_start = self._load_current_slot(now)
            result["slot_start"] = slot_start

            if slot:
                self.status.current_slot = slot_start
                self._stale_schedule_alerted = (
                    False  # schedule is fresh again; re-arm for next stale event
                )
            else:
                if self._stale_schedule_warning:
                    if not self._stale_schedule_alerted:
                        if self.dispatcher:
                            await self.dispatcher.notify_error(self._stale_schedule_warning)
                        self._stale_schedule_alerted = True
                else:
                    logger.warning("No valid slot found for current time")

            # 3. Gather system state
            state = await self._gather_system_state()
            self._last_system_state = state

            # Emit live metrics for UI sparklines (Rev E1)
            try:
                from backend.events import emit_live_metrics

                emit_live_metrics(
                    {
                        "soc": state.current_soc_percent,
                        "pv_kw": state.current_pv_kw,
                        "load_kw": state.current_load_kw,
                        "grid_import_kw": state.current_import_kw,
                        "grid_export_kw": state.current_export_kw,
                        "work_mode": state.current_work_mode,
                        "grid_charging": state.grid_charging_enabled,
                        "timestamp": now_iso,
                    }
                )
            except Exception as e:
                logger.debug("Failed to emit live metrics: %s", e)

            # Update state with slot validity
            state.slot_exists = slot is not None
            state.slot_valid = slot is not None

            # D1: Honor manual override — skip all writes but keep telemetry
            skip_writes = state.manual_override_active

            # 4. Check for active Quick Action OR Water Boost
            quick_action = self._get_quick_action_status()
            water_boost = self.get_water_boost_status()

            if quick_action:
                # Quick action takes priority
                from .override import OverrideResult, OverrideType

                action_type = quick_action["type"]
                actions = {}

                if action_type == "force_charge":
                    target_soc = quick_action.get("params", {}).get("target_soc", 100)
                    actions = {
                        "soc_target": int(target_soc),
                    }
                elif action_type == "force_export":
                    actions = {}
                elif action_type == "force_stop":
                    actions = {
                        "soc_target": 10,
                        "water_temp": self.config.water_heater.temp_off,
                    }
                elif action_type == "force_heat":
                    actions = {
                        "water_temp": self.config.water_heater.temp_boost,
                    }

                override = OverrideResult(
                    override_needed=True,
                    override_type=OverrideType(action_type),
                    priority=9.5,  # High priority, just below emergency
                    reason=quick_action.get("reason", f"User quick action: {action_type}"),
                    actions=actions,
                )
            elif water_boost:
                # Water Boost Logic with battery protection (Issue 2 fix)
                from .override import OverrideResult, OverrideType

                battery_cfg = self._full_config.get("battery", {})
                min_soc = float(battery_cfg.get("min_soc_percent", 10.0))
                min_boost_soc = min_soc + 10.0  # 10% buffer above min_soc

                if state.current_soc_percent < min_boost_soc:
                    # Battery too low - disable boost to protect battery
                    logger.warning(
                        "Water boost cancelled: SoC %.1f%% < required %.1f%%",
                        state.current_soc_percent,
                        min_boost_soc,
                    )
                    # Clear the boost
                    with self._lock:
                        self._water_boost_until = None
                    # Send notification
                    if self.dispatcher:
                        self.dispatcher._send_notification(  # type: ignore[protected-access]
                            f"Water boost cancelled - battery too low ({state.current_soc_percent:.0f}% < {min_boost_soc:.0f}%)",
                            title="Darkstar Water Boost",
                        )
                    override = OverrideResult(override_needed=False)
                else:
                    # Battery healthy - allow boost with SoC protection
                    protected_soc = max(int(state.current_soc_percent - 10), int(min_boost_soc))
                    override = OverrideResult(
                        override_needed=True,
                        override_type=OverrideType.FORCE_HEAT,
                        priority=8.0,
                        reason=f"Water Boost active until {water_boost['expires_at']}",
                        actions={
                            "soc_target": protected_soc,  # Protect from excessive drain
                            "water_temp": self.config.water_heater.temp_boost,
                        },
                    )
            else:
                # Normal override evaluation
                # Read override thresholds from config (with sensible defaults)
                battery_cfg = self._full_config.get("battery", {})

                override = evaluate_overrides(
                    state,
                    slot,
                    config={
                        "water_temp_boost": self.config.water_heater.temp_boost,
                        "water_temp_max": self.config.water_heater.temp_max,
                        "water_temp_off": self.config.water_heater.temp_off,
                    },
                )

            self.status.override_active = override.override_needed
            self.status.override_type = (
                override.override_type.value if override.override_needed else None
            )

            # Issue 3 fix: Only notify on override state transitions
            current_override_type = (
                override.override_type.value if override.override_needed else None
            )

            if override.override_needed:
                logger.info(
                    "Override active: %s - %s",
                    override.override_type.value,
                    override.reason,
                )
                result["override"] = {
                    "type": override.override_type.value,
                    "reason": override.reason,
                    "priority": override.priority,
                }
                # Only send notification on state transition (not every tick)
                if current_override_type != self._last_override_type and self.dispatcher:
                    await self.dispatcher.notify_override(
                        override.override_type.value, override.reason
                    )
                    logger.info("Override notification sent (state transition)")

            # Update state tracking
            self._last_override_type = current_override_type

            # 5. Make controller decision
            if slot is None:
                slot = SlotPlan()  # Use defaults if no slot

            # REV K25 Phase 5 + REV F76: EV Charging Logic with Actual Power Monitoring
            ev_charging_kw = slot.ev_charging_kw if slot else 0.0
            scheduled_ev_charging = ev_charging_kw > 0.1 if ev_charging_kw else False

            # REV F76 Phase 2: Get actual EV power from disaggregator
            actual_ev_power_kw: float = 0.0
            if self._has_ev_charger:
                try:
                    # Update load readings and get total EV power
                    await self._load_disaggregator.update_current_power()
                    actual_ev_power_kw = self._load_disaggregator.get_total_ev_power()
                    # REV F76 Phase 5 (Issue 1): Reset fail-safe flag on success
                    if self._ev_power_fetch_failed:
                        self._ev_power_fetch_failed = False
                        logger.info("EV power monitoring restored - fail-safe deactivated")
                except Exception as e:
                    # REV F76 Phase 5 (Issue 1): Fail-safe - block discharge on error
                    if not self._ev_power_fetch_failed:
                        logger.warning(
                            "EV power monitoring failed: %s - Fail-safe activated (blocking discharge)",
                            e,
                        )
                        self._ev_power_fetch_failed = True
                    actual_ev_power_kw = float("inf")  # Fail-safe: assume EV charging

            # Rev EVFIX: Separate switch control from source isolation
            actual_ev_charging: bool = actual_ev_power_kw > 0.1
            # Source isolation: Block discharge for both scheduled AND actual charging
            ev_should_charge_block: bool = scheduled_ev_charging or actual_ev_charging

            # Preserve original slot before EV source isolation may overwrite discharge_kw
            original_slot = slot
            ev_isolation_reason: str | None = None
            ev_charge_failed = False

            # Source Isolation: Block battery discharge when EV charging
            if ev_should_charge_block and self._has_battery:
                # Rev EVFIX: Updated logging to distinguish switch control vs source isolation
                if not self._ev_detected_last_tick:
                    # State transition: EV started charging
                    if self._ev_power_fetch_failed:
                        logger.warning(
                            "EV isolation active (fail-safe mode due to sensor failure) - Blocking battery discharge"
                        )
                    elif actual_ev_charging and not scheduled_ev_charging:
                        logger.info(
                            "EV charging detected: %.2f kW (not in schedule) - Source isolation active (blocking discharge), switch remains OFF",
                            actual_ev_power_kw,
                        )
                    else:
                        logger.info(
                            "EV charging active: %.1f kW scheduled, %.2f kW actual - Source isolation: Blocking battery discharge",
                            ev_charging_kw,
                            actual_ev_power_kw,
                        )
                    self._ev_detected_last_tick = True

                # Force zero discharge to prevent battery → EV energy flow
                slot = SlotPlan(
                    charge_kw=slot.charge_kw,
                    discharge_kw=0.0,  # Block discharge
                    export_kw=slot.export_kw,
                    load_kw=slot.load_kw,
                    water_kw=slot.water_kw,
                    ev_charging_kw=slot.ev_charging_kw,  # REV F76: Preserve EV data
                    soc_target=slot.soc_target,
                    soc_projected=slot.soc_projected,
                )

                # EV charge failure detection: track ticks with zero actual power
                if (
                    scheduled_ev_charging
                    and not actual_ev_charging
                    and not self._ev_power_fetch_failed
                ):
                    self._ev_zero_power_ticks += 1
                elif actual_ev_charging:
                    self._ev_zero_power_ticks = 0

                if self._ev_zero_power_ticks >= 5 and not self._ev_failure_notified:
                    error_msg = (
                        f"EV charge failure: {ev_charging_kw:.1f}kW scheduled, "
                        f"{actual_ev_power_kw:.2f}kW actual for {self._ev_zero_power_ticks} consecutive ticks"
                    )
                    logger.warning(error_msg)
                    if self.dispatcher:
                        await self.dispatcher.notify_error(error_msg)
                    self._ev_failure_notified = True
                    ev_charge_failed = True

                # Set isolation reason for execution record
                actual_for_reason = actual_ev_power_kw if not self._ev_power_fetch_failed else 0.0
                ev_isolation_reason = f"EV source isolation: {ev_charging_kw:.1f}kW scheduled, {actual_for_reason:.2f}kW actual"
            else:
                # REV F76 Phase 5 (Issue 4): Smart state-based logging
                if self._ev_detected_last_tick and not self._ev_power_fetch_failed:
                    # State transition: EV stopped charging
                    # Note: Skip if in fail-safe mode (sensor failure, not actual EV)
                    logger.info(
                        "EV charging ended - Source isolation: Resuming normal battery operation"
                    )
                self._ev_detected_last_tick = False

                # Reset EV failure detection when EV slot ends
                self._ev_zero_power_ticks = 0
                self._ev_failure_notified = False

            decision = make_decision(
                slot,
                state,
                override if override.override_needed else None,
                self.config.controller,
                self.config.inverter,
                self.config.water_heater,
                self.config.water_heater_devices,
                self.inverter_profile,
            )

            self.status.last_action = decision.reason

            # Control EV Charger Switch (per-device)
            if self._has_ev_charger and self.config.ev_chargers and not skip_writes:
                force_stop_ev = bool(quick_action and quick_action.get("type") == "force_stop")
                await self._control_ev_charger(original_slot, now, force_stop=force_stop_ev)

            # 6. Execute actions (skipped when manual_override_active — no inverter/EV/water writes)
            action_results: list[ActionResult] = []
            if self.dispatcher and not skip_writes:
                # REV UI11 Phase 7: Execute async actions
                try:
                    # Control Water Heater Temperature (per-device)
                    if self._has_water_heater:
                        if decision.water_temps and self.config.water_heater_devices:
                            # New multi-device format: control each heater independently
                            for device in self.config.water_heater_devices:
                                temp = decision.water_temps.get(
                                    device.id, self.config.water_heater.temp_off
                                )
                                water_result = await self.dispatcher.set_water_temp(
                                    temp, device.target_entity
                                )
                                action_results.append(water_result)
                        elif getattr(self.config.water_heater, "target_entity", None):
                            # Legacy fallback: old-format schedule or single heater
                            water_result = await self.dispatcher.set_water_temp(decision.water_temp)
                            action_results.append(water_result)

                    # Control Excess PV Custom Entity (7.2-7.4)
                    from executor.config import ExcessPVSinkType

                    if self.config.excess_pv.sink == ExcessPVSinkType.CUSTOM_ENTITY:
                        is_fallback = (
                            override.override_needed
                            and override.override_type.value == "slot_failure_fallback"
                        )
                        if is_fallback:
                            custom_value = self.config.excess_pv.custom_entity.off_value
                        else:
                            custom_value = (
                                self.config.excess_pv.custom_entity.on_value
                                if original_slot.custom_entity_active
                                else self.config.excess_pv.custom_entity.off_value
                            )
                        custom_result = await self.dispatcher.set_custom_entity(custom_value)
                        action_results.append(custom_result)

                    # Fix Issue 0: Await expected coroutine properly
                    profile_results = await self.dispatcher.execute(decision)
                    action_results.extend(profile_results)
                except Exception as e:
                    logger.error("Failed to execute async actions: %s", e)
                    # Append a failed result for the log (do not replace existing results)
                    action_results.append(
                        ActionResult(
                            action_type="execution_error",
                            success=False,
                            message=f"Async Execution Failed: {e!s}",
                        )
                    )

                # Phase 3: Capture errors from action results
                for r in action_results:
                    if not r.success and not r.skipped:
                        error_data = {
                            "timestamp": now_iso,
                            "type": r.action_type,
                            "message": r.message,
                            "error_details": r.error_details,  # REV F52 Phase 5: HA API error details
                        }
                        self.recent_errors.append(error_data)
                        # Broadcast error to WebSocket clients in real-time
                        try:
                            from backend.core.websockets import ws_manager

                            ws_manager.emit_sync("executor_error", error_data)
                        except Exception:
                            pass  # Silently fail if WebSocket not available

                result["actions"] = [
                    {
                        "type": r.action_type,
                        "success": r.success,
                        "message": r.message,
                        "skipped": r.skipped,
                        "error_details": r.error_details,  # REV F52 Phase 5: HA API error details
                    }
                    for r in action_results
                ]

            # 7. Log execution to history
            duration_ms = int((time.time() - start_time) * 1000)
            record = self._create_execution_record(
                now_iso=now_iso,
                slot=original_slot,
                slot_start=slot_start,
                state=state,
                decision=decision,
                override=override,
                action_results=action_results,
                success=(
                    not ev_charge_failed
                    and (all(r.success for r in action_results) if action_results else True)
                ),
                duration_ms=duration_ms,
                ev_isolation_reason=ev_isolation_reason,
            )
            self.history.log_execution(record)

            # Update slot_observations with executed action
            if slot_start:
                self.history.update_slot_observation(
                    slot_start,
                    {
                        "mode_intent": decision.mode_intent,
                        "soc_target": decision.soc_target,
                        "water_temp": decision.water_temp,
                        "source": decision.source,
                        "override_type": (
                            override.override_type.value if override.override_needed else None
                        ),
                    },
                )

            # Rev F1: Update battery cost based on charging activity
            await self._update_battery_cost(state, decision, slot)

            self.status.last_run_status = "success"
            logger.info("Executor tick completed in %dms", duration_ms)

            # Broadcast status update (Rev E1)
            try:
                from backend.events import emit_status_update

                emit_status_update(self.get_status())
            except Exception as e:
                logger.debug("Failed to emit status update: %s", e)

            # Broadcast water boost status (periodic + on change)
            self._emit_water_boost_status()

        except Exception as e:
            logger.exception("Executor tick failed: %s", e)
            result["success"] = False
            result["error"] = str(e)
            self.status.last_run_status = "error"
            self.status.last_error = str(e)

            if self.dispatcher:
                await self.dispatcher.notify_error(str(e))

            # Phase 3: Capture critical tick failure
            error_data = {
                "timestamp": now_iso,
                "type": "engine_tick",
                "message": str(e),
                "error_details": None,
            }
            self.recent_errors.append(error_data)
            # Broadcast error to WebSocket clients in real-time
            try:
                from backend.core.websockets import ws_manager

                ws_manager.emit_sync("executor_error", error_data)
            except Exception:
                pass  # Silently fail if WebSocket not available

        return result

    def _load_current_slot(self, now: datetime) -> tuple[SlotPlan | None, str | None]:
        """
        Load the current slot from schedule.json.

        Returns (SlotPlan, slot_start_iso) or (None, None) if not found.
        """
        schedule_path = self.config.schedule_path
        if not Path(schedule_path).exists():
            logger.warning("Schedule file not found: %s", schedule_path)
            return None, None

        try:
            with Path(schedule_path).open(encoding="utf-8") as f:
                payload: dict[str, Any] = json.load(f)
            schedule = payload.get("schedule", [])
        except Exception as e:
            logger.error("Failed to load schedule: %s", e)
            return None, None

        if not schedule:
            return None, None

        tz = pytz.timezone(self.config.timezone)

        # D3: Reject stale schedules — planner may be down
        self._stale_schedule_warning = None
        meta: dict[str, Any] = {}
        raw_meta = payload.get("meta")
        if isinstance(raw_meta, dict):
            meta = cast("dict[str, Any]", raw_meta)
        generated_at_str: str = str(meta.get("generated_at", "")) if meta else ""
        if generated_at_str:
            try:
                generated_at = datetime.fromisoformat(str(generated_at_str).replace("Z", "+00:00"))
                generated_at = (
                    tz.localize(generated_at)
                    if generated_at.tzinfo is None
                    else generated_at.astimezone(tz)
                )
                max_age = timedelta(hours=self.config.max_schedule_age_hours)
                age = now - generated_at
                if age > max_age:
                    age_hours = age.total_seconds() / 3600
                    msg = (
                        f"Schedule is stale ({age_hours:.1f}h old, "
                        f"max {self.config.max_schedule_age_hours}h) — holding"
                    )
                    logger.warning(msg)
                    self._stale_schedule_warning = msg
                    return None, None
            except Exception as e:
                logger.debug("Could not parse schedule generated_at: %s", e)

        # Find the slot that contains the current time
        for slot_data in schedule:
            start_str = slot_data.get("start_time")
            # Prefer end_time_kepler (correct) over end_time (sometimes has wrong TZ offset)
            end_str = slot_data.get("end_time_kepler") or slot_data.get("end_time")
            if not start_str:
                continue

            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                start = tz.localize(start) if start.tzinfo is None else start.astimezone(tz)

                if end_str:
                    end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    end = tz.localize(end) if end.tzinfo is None else end.astimezone(tz)
                    # Sanity check: if end <= start, use 15-min default
                    if end <= start:
                        logger.warning(
                            "Invalid end_time %s <= start_time %s, using 15min slot",
                            end,
                            start,
                        )
                        end = start + timedelta(minutes=15)
                else:
                    # Default 15-minute slot
                    end = start + timedelta(minutes=15)

                # Check if current time is within this slot
                if start <= now < end:
                    slot = self._parse_slot_plan(slot_data)
                    return slot, start.isoformat()

            except Exception as e:
                logger.warning("Failed to parse slot: %s", e)
                continue

        # No matching slot found
        return None, None

    def _parse_slot_plan(self, slot_data: dict[str, Any]) -> SlotPlan:
        """Parse a schedule slot into a SlotPlan object."""
        # Handle both kW and kWh fields
        charge_kw = float(slot_data.get("battery_charge_kw", 0.0) or 0.0)
        discharge_kw = float(slot_data.get("battery_discharge_kw", 0.0) or 0.0)
        export_kw = float(slot_data.get("export_kwh", 0.0) or 0.0) * 4  # kWh to kW
        # Load forecast: convert kWh per slot to kW (multiply by 4 for 15-min slots)
        load_kw = float(slot_data.get("load_forecast_kwh", 0.0) or 0.0) * 4
        water_kw = float(slot_data.get("water_heating_kw", 0.0) or 0.0)
        ev_charging_kw = float(slot_data.get("ev_charging_kw", 0.0) or 0.0)
        soc_target = int(slot_data.get("soc_target_percent", slot_data.get("soc_target", 50)) or 50)
        soc_projected = int(
            slot_data.get("projected_soc_percent", slot_data.get("soc_projected", 50)) or 50
        )

        # Parse per-device EV charger plans (new multi-device format)
        raw_ev_chargers = slot_data.get("ev_chargers")
        ev_charger_plans: dict[str, float] = {}
        if isinstance(raw_ev_chargers, dict):
            typed_chargers = cast("dict[str, Any]", raw_ev_chargers)
            ev_charger_plans = {
                str(k): float(cast("float | str", v)) for k, v in typed_chargers.items()
            }
        elif not raw_ev_chargers and ev_charging_kw > 0 and self.config.ev_chargers:
            # Backward compat: old-format schedule only has aggregate ev_charging_kw;
            # map it to the first configured charger so per-device control still works.
            ev_charger_plans = {self.config.ev_chargers[0].id: ev_charging_kw}

        # Parse per-device water heater plans (new multi-device format)
        raw_water_heaters = slot_data.get("water_heaters")
        water_heater_plans: dict[str, float] = {}
        if isinstance(raw_water_heaters, dict):
            for k, v in raw_water_heaters.items():  # type: ignore[union-attr]
                if isinstance(v, dict):
                    water_heater_plans[str(k)] = float(v.get("heating_kw", 0.0))  # type: ignore[arg-type]
                else:
                    water_heater_plans[str(k)] = float(v)  # type: ignore[arg-type]

        # Parse water heating boost flags
        raw_boost = slot_data.get("water_heating_boost")
        water_heating_boost: dict[str, bool] = {}
        if isinstance(raw_boost, dict):
            for k, v in raw_boost.items():  # type: ignore[union-attr]
                water_heating_boost[str(k)] = bool(v)  # type: ignore[arg-type]

        # Parse custom entity active flag
        custom_entity_active = bool(slot_data.get("custom_entity_active", False))

        return SlotPlan(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            export_kw=export_kw,
            load_kw=load_kw,
            water_kw=water_kw,
            ev_charging_kw=ev_charging_kw,
            soc_target=soc_target,
            soc_projected=soc_projected,
            ev_charger_plans=ev_charger_plans,
            water_heater_plans=water_heater_plans,
            water_heating_boost=water_heating_boost,
            custom_entity_active=custom_entity_active,
        )

    async def _gather_system_state(self) -> SystemState:
        """Gather current system state from Home Assistant."""
        state = SystemState()

        if not self.ha_client:
            return state

        from backend.core.ha_client import gather_sensor_reads

        # Get entity IDs from config (input_sensors section)
        input_sensors = self._full_config.get("input_sensors", {})
        soc_entity = input_sensors.get("battery_soc", "sensor.inverter_battery")
        pv_power_entity = input_sensors.get("pv_power", "sensor.inverter_pv_power")
        load_power_entity = input_sensors.get("load_power", "sensor.inverter_load_power")

        system_config = self._full_config.get("system", {})
        meter_type = system_config.get("grid_meter_type", "net")

        work_mode_entity: str | None = getattr(self.config.inverter, "work_mode_entity", None)
        grid_charging_entity: str | None = getattr(
            self.config.inverter, "grid_charging_entity", None
        )

        ha = self.ha_client

        # Build batch of independent sensor reads
        reads: list[tuple[str, Any]] = []

        if self.config.has_battery:
            reads.append(("soc", lambda e=soc_entity: ha.get_state_value(e)))
        if self.config.has_solar:
            reads.append(("pv_power", lambda e=pv_power_entity: ha.get_state_value(e)))

        reads.append(("load_power", lambda e=load_power_entity: ha.get_state_value(e)))

        import_entity: str | None = None
        export_entity: str | None = None
        if meter_type == "dual":
            import_entity = input_sensors.get("grid_import_power")
            export_entity = input_sensors.get("grid_export_power")
            if import_entity:
                reads.append(("grid_import", lambda e=import_entity: ha.get_state_value(e)))
            if export_entity:
                reads.append(("grid_export", lambda e=export_entity: ha.get_state_value(e)))

        if self.config.has_battery and work_mode_entity:
            reads.append(("work_mode", lambda e=work_mode_entity: ha.get_state_value(e)))

        if self.config.has_battery and grid_charging_entity:
            reads.append(("grid_charging", lambda e=grid_charging_entity: ha.get_state_value(e)))

        water_entity: str | None = None
        if self.config.has_water_heater:
            # Use first configured per-device target entity (or legacy global entity if present)
            if self.config.water_heater_devices:
                water_entity = self.config.water_heater_devices[0].target_entity
            elif hasattr(self.config.water_heater, "target_entity"):
                water_entity = self.config.water_heater.target_entity  # type: ignore[union-attr]
            if water_entity:
                reads.append(("water_temp", lambda e=water_entity: ha.get_state_value(e)))  # type: ignore[misc]

        if self.config.manual_override_entity:
            override_entity = self.config.manual_override_entity
            reads.append(("manual_override", lambda e=override_entity: ha.get_state_value(e)))

        try:
            results = await gather_sensor_reads(reads, context="executor_state")

            soc_str = results.get("soc")
            if soc_str and soc_str not in ("unknown", "unavailable"):
                state.current_soc_percent = float(soc_str)

            pv_str = results.get("pv_power")
            if pv_str and pv_str not in ("unknown", "unavailable"):
                state.current_pv_kw = float(pv_str) / 1000  # W to kW

            load_str = results.get("load_power")
            if load_str and load_str not in ("unknown", "unavailable"):
                state.current_load_kw = float(load_str) / 1000

            imp_str = results.get("grid_import")
            if imp_str and imp_str not in ("unknown", "unavailable"):
                state.current_import_kw = float(imp_str) / 1000

            exp_str = results.get("grid_export")
            if exp_str and exp_str not in ("unknown", "unavailable"):
                state.current_export_kw = float(exp_str) / 1000

            work_mode = results.get("work_mode")
            if work_mode:
                state.current_work_mode = work_mode

            grid_charge = results.get("grid_charging")
            if grid_charge is not None:
                state.grid_charging_enabled = grid_charge == "on"

            water_str = results.get("water_temp")
            if water_str:
                state.current_water_temp = float(water_str)

            # Pass water heater configuration to state
            state.has_water_heater = self._has_water_heater

            manual = results.get("manual_override")
            if manual is not None:
                state.manual_override_active = manual == "on"

        except Exception as e:
            logger.warning("Failed to gather some system state: %s", e)

        return state

    def _create_execution_record(
        self,
        now_iso: str,
        slot: SlotPlan,
        slot_start: str | None,
        state: SystemState,
        decision: ControllerDecision,
        override: OverrideResult,
        action_results: list[ActionResult],
        success: bool,
        duration_ms: int,
        ev_isolation_reason: str | None = None,
    ) -> ExecutionRecord:
        """Create an execution record for logging."""
        return ExecutionRecord(
            executed_at=now_iso,
            slot_start=slot_start or now_iso,
            # Planned values
            planned_charge_kw=slot.charge_kw,
            planned_discharge_kw=slot.discharge_kw,
            planned_export_kw=slot.export_kw,
            planned_water_kw=slot.water_kw,
            planned_soc_target=slot.soc_target,
            planned_soc_projected=slot.soc_projected,
            ev_charging_kw=slot.ev_charging_kw,
            ev_charger_plans=slot.ev_charger_plans if slot.ev_charger_plans else None,
            water_heater_plans=slot.water_heater_plans if slot.water_heater_plans else None,
            # Commanded values
            commanded_work_mode=decision.mode_intent,
            commanded_grid_charging=1 if decision.mode_intent == "charge" else 0,
            commanded_charge_current_a=decision.charge_value,
            commanded_discharge_current_a=decision.discharge_value,
            commanded_unit=self.config.inverter.control_unit,
            commanded_soc_target=decision.soc_target,
            commanded_water_temp=decision.water_temp,
            # State before
            before_soc_percent=state.current_soc_percent,
            before_work_mode=state.current_work_mode,
            before_water_temp=state.current_water_temp,
            before_pv_kw=state.current_pv_kw,
            before_load_kw=state.current_load_kw,
            # Override
            override_active=1 if override.override_needed else 0,
            override_type=(override.override_type.value if override.override_needed else None),
            override_reason=override.reason if override.override_needed else ev_isolation_reason,
            # Results (NEW: full detail for each controlled entity)
            action_results=[
                {
                    "type": r.action_type,
                    "success": r.success,
                    "message": r.message,
                    "entity_id": r.entity_id,
                    "previous_value": r.previous_value,
                    "new_value": r.new_value,
                    "verified_value": r.verified_value,
                    "verification_success": r.verification_success,
                    "skipped": r.skipped,
                    "error_details": r.error_details,  # REV F52 Phase 5: HA API error details
                }
                for r in action_results
            ],
            # Result
            success=1 if success else 0,
            duration_ms=duration_ms,
            source="native",
            executor_version=EXECUTOR_VERSION,
        )

    async def _update_battery_cost(
        self,
        state: SystemState,
        decision: ControllerDecision,
        slot: SlotPlan | None,
    ) -> None:
        """
        Update battery cost based on charging activity (Rev F1).

        Uses weighted average algorithm:
        - Grid charge: cost increases proportional to import price
        - PV charge: cost dilutes (free energy reduces avg cost)
        """
        if not self.config.has_battery:
            return

        try:
            from backend.battery_cost import BatteryCostTracker

            # Get battery capacity from config
            battery_cfg = self._full_config.get("battery", {})
            capacity_kwh = battery_cfg.get("capacity_kwh", 27.0)

            # Initialize tracker
            db_path = self._get_db_path()
            tracker = BatteryCostTracker(db_path, capacity_kwh)

            # Estimate charging this slot (5 min @ planned power)
            slot_duration_h = self.config.interval_seconds / 3600.0

            # Grid charge: if mode_intent is "charge" and charge value > 0
            grid_charge_kwh: float = 0.0
            is_grid_charging = decision.mode_intent == "charge"
            if is_grid_charging and decision.charge_value > 0:
                # Rough estimate: charge_value * voltage / 1000 * efficiency * duration
                voltage_v: float = getattr(self.config.controller, "system_voltage_v", 48.0) or 48.0
                efficiency: float = (
                    getattr(self.config.controller, "charge_efficiency", 0.92) or 0.92
                )
                charge_kw: float = (decision.charge_value * voltage_v / 1000.0) * efficiency
                grid_charge_kwh = charge_kw * slot_duration_h

            # PV charge: if PV exceeds load, surplus goes to battery
            pv_charge_kwh = 0.0
            if state.current_pv_kw and state.current_load_kw:
                pv_surplus_kw = max(0.0, state.current_pv_kw - state.current_load_kw)
                pv_charge_kwh = pv_surplus_kw * slot_duration_h * 0.95  # 95% efficiency

            # Get current import price
            import_price = 0.5  # Default fallback
            try:
                from backend.core.prices import get_nordpool_data

                prices = await get_nordpool_data("config.yaml")

                if prices:
                    # Get current slot's price
                    import pytz

                    tz = pytz.timezone(self.config.timezone)
                    now = datetime.now(tz)
                    for p in prices:
                        st = p.get("start_time")
                        if st and st <= now < st + timedelta(hours=1):
                            import_price = p.get("import_price_sek_kwh", 0.5)
                            break
            except Exception as e:
                logger.debug("Failed to fetch import price: %s", e)

            # Always update to keep energy state synced (cost only changes during charge)
            tracker.update_cost(
                current_soc_percent=state.current_soc_percent or 50.0,
                grid_charge_kwh=grid_charge_kwh,
                pv_charge_kwh=pv_charge_kwh,
                import_price_sek=import_price,
            )

        except Exception as e:
            logger.debug("Battery cost update skipped: %s", e)

    async def _control_ev_charger(
        self, slot: "SlotPlan | None", now: datetime, force_stop: bool = False
    ) -> None:
        """
        Control all configured EV charger switches per-device.

        Each charger gets independent switch control and safety timeout based
        on its per-device plan from slot.ev_charger_plans.

        force_stop: when True, commands all chargers off regardless of the plan.
        """
        if not self.dispatcher or not self.ha_client:
            return

        for charger_cfg in self.config.ev_chargers:
            switch_entity = charger_cfg.switch_entity
            if not switch_entity:
                continue

            charger_id = charger_cfg.id
            charger_plan_kw = slot.ev_charger_plans.get(charger_id, 0.0) if slot else 0.0
            should_charge = charger_plan_kw > 0.1

            # D2: force_stop quick action overrides the plan
            if force_stop:
                should_charge = False

            # Get or create per-device state
            if charger_id not in self._ev_charger_states:
                self._ev_charger_states[charger_id] = EVChargerState()
            dev_state = self._ev_charger_states[charger_id]

            try:
                current_state = await self.ha_client.get_state_value(switch_entity)
                is_currently_on = current_state == "on" if current_state else False

                # Safety timeout: stop if plan expired
                if is_currently_on and not should_charge and dev_state.charging_started_at:
                    elapsed = (now - dev_state.charging_started_at).total_seconds() / 60
                    if elapsed > 30:
                        logger.warning(
                            "EV charger %s safety timeout: Auto-stopping after %d minutes",
                            charger_id,
                            int(elapsed),
                        )
                        should_charge = False

                if should_charge and not is_currently_on:
                    result = await self.dispatcher.set_ev_charger_switch(
                        switch_entity, turn_on=True, charging_kw=charger_plan_kw
                    )
                    if result.success:
                        dev_state.charging_active = True
                        dev_state.charging_started_at = now
                        dev_state.charging_slot_end = now + timedelta(minutes=15)
                        self.history.log_execution(
                            ExecutionRecord(
                                executed_at=now.isoformat(),
                                slot_start=now.isoformat(),
                                commanded_work_mode="ev_charge_start",
                                before_soc_percent=0,
                                success=1 if not result.skipped else 0,
                                source="ev_charger",
                                duration_ms=result.duration_ms,
                                action_results=[
                                    {
                                        "type": result.action_type,
                                        "success": result.success,
                                        "message": result.message,
                                        "entity_id": result.entity_id,
                                        "charger_id": charger_id,
                                        "previous_value": result.previous_value,
                                        "new_value": result.new_value,
                                        "verified_value": result.verified_value,
                                        "verification_success": result.verification_success,
                                        "skipped": result.skipped,
                                        "error_details": result.error_details,
                                    }
                                ],
                            )
                        )

                elif not should_charge and is_currently_on:
                    result = await self.dispatcher.set_ev_charger_switch(
                        switch_entity, turn_on=False, charging_kw=0.0
                    )
                    if result.success:
                        dev_state.charging_active = False
                        dev_state.charging_started_at = None
                        dev_state.charging_slot_end = None
                        self.history.log_execution(
                            ExecutionRecord(
                                executed_at=now.isoformat(),
                                slot_start=now.isoformat(),
                                commanded_work_mode="ev_charge_stop",
                                before_soc_percent=0,
                                success=1 if not result.skipped else 0,
                                source="ev_charger",
                                duration_ms=result.duration_ms,
                                action_results=[
                                    {
                                        "type": result.action_type,
                                        "success": result.success,
                                        "message": result.message,
                                        "entity_id": result.entity_id,
                                        "charger_id": charger_id,
                                        "previous_value": result.previous_value,
                                        "new_value": result.new_value,
                                        "verified_value": result.verified_value,
                                        "verification_success": result.verification_success,
                                        "skipped": result.skipped,
                                        "error_details": result.error_details,
                                    }
                                ],
                            )
                        )

                elif should_charge and is_currently_on:
                    dev_state.charging_slot_end = now + timedelta(minutes=15)

            except Exception as e:
                logger.error("Failed to control EV charger %s: %s", charger_id, e)
