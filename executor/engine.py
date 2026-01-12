"""
Executor Engine

The main executor loop that orchestrates:
1. Reading the current slot from schedule.json
2. Gathering system state from Home Assistant
3. Evaluating overrides
4. Making controller decisions
5. Executing actions
6. Logging execution history
"""

import contextlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytz

# import yaml
# Import existing HA config loader
from inputs import load_home_assistant_config

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
class ExecutorStatus:
    """Current status of the executor."""

    enabled: bool = False
    shadow_mode: bool = False
    last_run_at: str | None = None
    last_run_status: str = "pending"
    last_error: str | None = None
    next_run_at: str | None = None
    current_slot: str | None = None
    last_action: str | None = None
    override_active: bool = False
    override_type: str | None = None


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

        # Initialize components
        self.history = ExecutionHistory(
            db_path=self._get_db_path(),
            timezone=self.config.timezone,
        )

        self.ha_client: HAClient | None = None
        self.dispatcher: ActionDispatcher | None = None

        # Status tracking
        self.status = ExecutorStatus(
            enabled=self.config.enabled,
            shadow_mode=self.config.shadow_mode,
        )

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

        # System profile toggles (Rev O1)
        system_cfg = self._full_config.get("system", {})
        self._has_solar = system_cfg.get("has_solar", True)
        self._has_battery = system_cfg.get("has_battery", True)
        self._has_water_heater = system_cfg.get("has_water_heater", True)

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
            return False

        base_url = ha_config.get("url", "")
        token = ha_config.get("token", "")

        if not base_url or not token:
            logger.error("Missing HA URL or token in secrets")
            return False

        self.ha_client = HAClient(base_url, token)
        self.dispatcher = ActionDispatcher(
            self.ha_client,
            self.config,
            shadow_mode=self.config.shadow_mode,
        )
        return True

    def reload_config(self) -> None:
        """Reload configuration from config.yaml."""
        with self._lock:
            self.config = load_executor_config(self.config_path)
            self.status.enabled = self.config.enabled
            self.status.shadow_mode = self.config.shadow_mode
            if self.dispatcher:
                self.dispatcher.shadow_mode = self.config.shadow_mode
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
                current_slot_plan = {
                    "slot_start": slot_start,
                    "charge_kw": slot.charge_kw,
                    "export_kw": slot.export_kw,
                    "water_kw": slot.water_kw,
                    "soc_target": slot.soc_target,
                    "soc_projected": slot.soc_projected,
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
                "last_run_at": self.status.last_run_at,
                "last_run_status": self.status.last_run_status,
                "last_error": self.status.last_error,
                "next_run_at": self.status.next_run_at,
                "current_slot": self.status.current_slot,
                "current_slot_plan": current_slot_plan,
                "last_action": self.status.last_action,
                "override_active": self.status.override_active,
                "override_type": self.status.override_type,
                "quick_action": quick_action_status,
                "paused": pause_status,
                "water_boost": water_boost_status,
                "version": EXECUTOR_VERSION,
            }

    def get_stats(self, days: int = 7) -> dict[str, Any]:
        """Get execution statistics."""
        return self.history.get_stats(days=days)

    def get_live_metrics(self) -> dict[str, Any]:
        """
        Get live system metrics for API.

        Returns a snapshot of current system power flows and state.
        """
        # Start with standard system state
        state = self._gather_system_state()

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
                val = self.ha_client.get_state_value(batt_pwr_entity)
                if val and val not in ("unknown", "unavailable"):
                    with contextlib.suppress(ValueError):
                        metrics["battery_kw"] = float(val) / 1000.0  # W to kW

            # Water Heater Power
            water_pwr_entity = input_sensors.get("water_power")
            if water_pwr_entity:
                val = self.ha_client.get_state_value(water_pwr_entity)
                if val and val not in ("unknown", "unavailable"):
                    with contextlib.suppress(ValueError):
                        metrics["water_kw"] = float(val) / 1000.0  # W to kW

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
        self, action_type: str, duration_minutes: int, params: dict[str, Any] | None = None
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
        Pause the executor - enters idle mode.

        Idle mode: zero export, min_soc target, no grid charging, no water heating.
        A reminder will be scheduled based on configuration or duration.
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
            # Rev update: You could store duration_minutes here if you wanted dynamic reminders
            # For now just accepting the arg avoids the 500 error.

        logger.info("Executor PAUSED at %s - entering idle mode", now.isoformat())

        # Immediately execute a tick to apply idle mode
        if self.ha_client:
            try:
                self._apply_idle_mode()
            except Exception as e:
                logger.error("Failed to apply idle mode: %s", e)

        return {
            "success": True,
            "paused_at": now.isoformat(),
            "message": "Executor paused - idle mode active",
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

        logger.info("Executor RESUMED after %.1f minutes paused", paused_duration)

        # Trigger immediate tick to apply scheduled action without waiting
        try:
            self._tick()
            logger.info("Immediate tick executed after resume")
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

    def _apply_idle_mode(self) -> None:
        """Apply idle mode settings to Home Assistant."""
        if not self.dispatcher:
            return

        from .controller import ControllerDecision

        # Idle mode: Zero export, no grid charging, min SoC target, no water heat
        idle_decision = ControllerDecision(
            work_mode=self.config.inverter.work_mode_zero_export,
            grid_charging=False,
            charge_current_a=0,
            discharge_current_a=50,  # Allow discharge to power house
            soc_target=10,  # Min SoC
            water_temp=self.config.water_heater.temp_off,
            source="pause_idle",
            reason="Executor paused - idle mode",
        )

        self.dispatcher.execute(idle_decision)
        logger.info("Idle mode applied: zero export, no grid charge, water off")

    def _check_pause_reminder(self) -> None:
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
            self._send_pause_reminder(paused_at)

    def _send_pause_reminder(self, paused_at: datetime) -> None:
        """Send pause reminder notification with resume action."""
        if not self.dispatcher:
            return

        try:
            message = (
                f"⚠️ Executor has been paused for {self.config.pause_reminder_minutes} minutes. "
                f"Paused since {paused_at.strftime('%H:%M')}."
            )

            # Send via ActionDispatcher
            self.send_notification(
                "Darkstar Executor Paused",
                message,
                data={
                    "notification_type": "pause_reminder",
                    "actions": [{"action": "RESUME_EXECUTOR", "title": "ACTIVATE"}],
                },
            )
            logger.info("Pause reminder notification sent")
        except Exception as e:
            logger.error("Failed to send pause reminder: %s", e)

    def send_notification(
        self, title: str, message: str, data: dict[str, Any] | None = None
    ) -> bool:
        """Send a notification via the configured service."""
        if not self.dispatcher:
            return False

        try:
            self.dispatcher._send_notification(message, title=title)
            # If data is provided, we might need a more direct HA call since _send_notification is simplified
            if data:
                self.ha_client.send_notification(
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
            return {"success": False, "error": "No water heater configured in system profile"}

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
                self.dispatcher.set_water_temp(self.config.water_heater.temp_boost)
            except Exception as e:
                logger.error("Failed to apply water boost: %s", e)

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
                    self.dispatcher.set_water_temp(self.config.water_heater.temp_off)
                except Exception as e:
                    logger.error("Failed to reset water temp: %s", e)

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

            remaining = (self._water_boost_until - now).total_seconds() / 60
            return {
                "expires_at": self._water_boost_until.isoformat(),
                "remaining_minutes": round(remaining, 1),
                "temp_target": self.config.water_heater.temp_boost,
            }

    def start(self) -> None:
        """Start the executor loop in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Executor already running")
            return

        if not self.init_ha_client():
            logger.error("Failed to initialize HA client, executor not started")
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

    def run_once(self) -> dict[str, Any]:
        """
        Run a single execution tick synchronously.

        Returns the execution result.
        """
        if not self.ha_client and not self.init_ha_client():
            return {"success": False, "error": "Failed to initialize HA client"}

        return self._tick()

    def _run_loop(self) -> None:
        """Main execution loop running in background thread."""
        tz = pytz.timezone(self.config.timezone)
        logger.info("Executor background loop started")

        while not self._stop_event.is_set():
            # Reload config to get latest settings
            self.reload_config()

            # Check if enabled
            if not self.config.enabled:
                logger.debug("Executor disabled, waiting 10s...")
                self._stop_event.wait(10)  # Check every 10s
                continue

            # Calculate next run time
            now = datetime.now(tz)
            next_run = self._compute_next_run(now)
            self.status.next_run_at = next_run.isoformat()

            # Wait until next run time
            wait_seconds = (next_run - now).total_seconds()
            if wait_seconds > 1:  # Only wait if more than 1s
                logger.debug(
                    "Waiting %.1fs until next run at %s", wait_seconds, next_run.isoformat()
                )
                if self._stop_event.wait(wait_seconds):
                    break  # Stop event was set during wait
                # Re-check current time after waiting
                now = datetime.now(tz)

            # Prevent double execution - check if we ran recently
            if self.status.last_run_at:
                try:
                    last_run = datetime.fromisoformat(
                        self.status.last_run_at.replace("Z", "+00:00")
                    )
                    if last_run.tzinfo is None:
                        last_run = tz.localize(last_run)
                    # Skip if we ran within the last interval minus a buffer
                    min_interval = self.config.interval_seconds - 30  # 30s buffer
                    seconds_since_last = (now - last_run).total_seconds()
                    if seconds_since_last < min_interval:
                        logger.debug(
                            "Skipping - already ran %.0fs ago (min interval: %ds)",
                            seconds_since_last,
                            min_interval,
                        )
                        # Don't tight-loop - wait until next boundary
                        continue  # Will recalculate next_run on next iteration
                except Exception as e:
                    logger.debug("Could not parse last_run_at: %s", e)

            # Execute tick
            try:
                tick_start = datetime.now(tz)
                logger.info("Executing scheduled tick at %s", tick_start.isoformat())
                self._tick()
                tick_duration = (datetime.now(tz) - tick_start).total_seconds()
                logger.debug("Tick completed in %.2fs", tick_duration)
            except Exception as e:
                logger.exception("Executor tick failed: %s", e)
                self.status.last_run_status = "error"
                self.status.last_error = str(e)

            # No fixed sleep - next iteration will calculate proper wait time
            # This eliminates drift and ensures alignment to interval boundaries

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

    def _tick(self) -> dict[str, Any]:
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
        self.status.last_run_at = now_iso

        result: dict[str, Any] = {
            "success": True,
            "executed_at": now_iso,
            "slot_start": None,
            "actions": [],
            "override": None,
            "error": None,
        }

        try:
            # 0. Check pause state first - if paused, apply idle mode and check reminder
            if self.is_paused:
                logger.info("Executor is PAUSED - applying idle mode")
                self._check_pause_reminder()
                self._apply_idle_mode()
                self.status.last_run_status = "paused"
                result["success"] = True
                result["actions"] = [{"type": "skip", "reason": "paused_idle_mode"}]
                return result

            # 1. Check automation toggle
            if self.ha_client:
                toggle_state = self.ha_client.get_state_value(self.config.automation_toggle_entity)
                if toggle_state != "on":
                    logger.info("Automation toggle is off, skipping execution")
                    self.status.last_run_status = "skipped"
                    result["success"] = True
                    result["actions"] = [{"type": "skip", "reason": "automation_disabled"}]
                    return result

            # 2. Load current slot from schedule.json
            slot, slot_start = self._load_current_slot(now)
            result["slot_start"] = slot_start

            if slot:
                self.status.current_slot = slot_start
            else:
                logger.warning("No valid slot found for current time")

            # 3. Gather system state
            state = self._gather_system_state()

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

            # 4. Check for active quick action first (user-initiated override)
            quick_action = self._get_quick_action_status()
            if quick_action:
                # Quick action takes priority
                from .override import OverrideResult, OverrideType

                action_type = quick_action["type"]
                actions = {}

                if action_type == "force_charge":
                    # allow target_soc from params (default 100)
                    target_soc = quick_action.get("params", {}).get("target_soc", 100)
                    actions = {
                        "work_mode": self.config.inverter.work_mode_zero_export,
                        "grid_charging": True,
                        "soc_target": int(target_soc),
                    }
                elif action_type == "force_export":
                    actions = {
                        "work_mode": self.config.inverter.work_mode_export,
                        "grid_charging": False,
                    }
                elif action_type == "force_stop":
                    actions = {
                        "work_mode": self.config.inverter.work_mode_zero_export,
                        "grid_charging": False,
                        "soc_target": 10,  # Minimal activity
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
            else:
                # Normal override evaluation
                override = evaluate_overrides(
                    state,
                    slot,
                    config={
                        "min_soc_floor": 10.0,
                        "low_soc_threshold": 20.0,
                        "excess_pv_threshold_kw": 2.0,
                        "water_temp_boost": self.config.water_heater.temp_boost,
                        "water_temp_max": self.config.water_heater.temp_max,
                        "water_temp_off": self.config.water_heater.temp_off,
                    },
                )

            self.status.override_active = override.override_needed
            self.status.override_type = (
                override.override_type.value if override.override_needed else None
            )

            if override.override_needed:
                logger.info(
                    "Override active: %s - %s", override.override_type.value, override.reason
                )
                result["override"] = {
                    "type": override.override_type.value,
                    "reason": override.reason,
                    "priority": override.priority,
                }
                if self.dispatcher:
                    self.dispatcher.notify_override(override.override_type.value, override.reason)

            # 5. Make controller decision
            if slot is None:
                slot = SlotPlan()  # Use defaults if no slot

            decision = make_decision(
                slot,
                state,
                override if override.override_needed else None,
                self.config.controller,
                self.config.water_heater,
            )

            self.status.last_action = decision.reason

            # 6. Execute actions
            action_results: list[ActionResult] = []
            if self.dispatcher:
                action_results = self.dispatcher.execute(decision)
                result["actions"] = [
                    {
                        "type": r.action_type,
                        "success": r.success,
                        "message": r.message,
                        "skipped": r.skipped,
                    }
                    for r in action_results
                ]

            # 7. Log execution to history
            duration_ms = int((time.time() - start_time) * 1000)
            record = self._create_execution_record(
                now_iso=now_iso,
                slot=slot,
                slot_start=slot_start,
                state=state,
                decision=decision,
                override=override,
                success=all(r.success for r in action_results) if action_results else True,
                duration_ms=duration_ms,
            )
            self.history.log_execution(record)

            # Update slot_observations with executed action
            if slot_start:
                self.history.update_slot_observation(
                    slot_start,
                    {
                        "work_mode": decision.work_mode,
                        "grid_charging": decision.grid_charging,
                        "soc_target": decision.soc_target,
                        "water_temp": decision.water_temp,
                        "source": decision.source,
                        "override_type": (
                            override.override_type.value if override.override_needed else None
                        ),
                    },
                )

            # Rev F1: Update battery cost based on charging activity
            self._update_battery_cost(state, decision, slot)

            self.status.last_run_status = "success"
            logger.info("Executor tick completed in %dms", duration_ms)

            # Broadcast status update (Rev E1)
            try:
                from backend.events import emit_status_update

                emit_status_update(self.get_status())
            except Exception as e:
                logger.debug("Failed to emit status update: %s", e)

        except Exception as e:
            logger.exception("Executor tick failed: %s", e)
            result["success"] = False
            result["error"] = str(e)
            self.status.last_run_status = "error"
            self.status.last_error = str(e)

            if self.dispatcher:
                self.dispatcher.notify_error(str(e))

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
                payload = json.load(f)
            schedule = payload.get("schedule", [])
        except Exception as e:
            logger.error("Failed to load schedule: %s", e)
            return None, None

        if not schedule:
            return None, None

        tz = pytz.timezone(self.config.timezone)

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
                            "Invalid end_time %s <= start_time %s, using 15min slot", end, start
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
        water_kw = float(slot_data.get("water_heating_kw", 0.0) or 0.0)
        soc_target = int(slot_data.get("soc_target_percent", slot_data.get("soc_target", 50)) or 50)
        soc_projected = int(
            slot_data.get("projected_soc_percent", slot_data.get("soc_projected", 50)) or 50
        )

        return SlotPlan(
            charge_kw=charge_kw,
            discharge_kw=discharge_kw,
            export_kw=export_kw,
            water_kw=water_kw,
            soc_target=soc_target,
            soc_projected=soc_projected,
        )

    def _gather_system_state(self) -> SystemState:
        """Gather current system state from Home Assistant."""
        state = SystemState()

        if not self.ha_client:
            return state

        # Get entity IDs from config (input_sensors section)
        input_sensors = self._full_config.get("input_sensors", {})
        soc_entity = input_sensors.get("battery_soc", "sensor.inverter_battery")
        pv_power_entity = input_sensors.get("pv_power", "sensor.inverter_pv_power")
        load_power_entity = input_sensors.get("load_power", "sensor.inverter_load_power")

        try:
            # Get SoC (Rev O1)
            if self.config.has_battery:
                soc_str = self.ha_client.get_state_value(soc_entity)
                if soc_str and soc_str not in ("unknown", "unavailable"):
                    state.current_soc_percent = float(soc_str)

            # Get PV power (Rev O1)
            if self.config.has_solar:
                pv_str = self.ha_client.get_state_value(pv_power_entity)
                if pv_str and pv_str not in ("unknown", "unavailable"):
                    state.current_pv_kw = float(pv_str) / 1000  # W to kW

            # Get load power
            load_str = self.ha_client.get_state_value(load_power_entity)
            if load_str and load_str not in ("unknown", "unavailable"):
                state.current_load_kw = float(load_str) / 1000

            # Get grid import/export (Rev E1)
            import_entity = input_sensors.get("grid_import_power")
            export_entity = input_sensors.get("grid_export_power")

            if import_entity:
                imp_str = self.ha_client.get_state_value(import_entity)
                if imp_str and imp_str not in ("unknown", "unavailable"):
                    state.current_import_kw = float(imp_str) / 1000

            if export_entity:
                exp_str = self.ha_client.get_state_value(export_entity)
                if exp_str and exp_str not in ("unknown", "unavailable"):
                    state.current_export_kw = float(exp_str) / 1000

            # Get current work mode
            if self.config.has_battery:
                work_mode = self.ha_client.get_state_value(self.config.inverter.work_mode_entity)
                if work_mode:
                    state.current_work_mode = work_mode

                # Get grid charging state
                grid_charge = self.ha_client.get_state_value(
                    self.config.inverter.grid_charging_entity
                )
                state.grid_charging_enabled = grid_charge == "on"

            # Get water heater temp (Rev O1)
            if self.config.has_water_heater:
                water_str = self.ha_client.get_state_value(self.config.water_heater.target_entity)
                if water_str:
                    state.current_water_temp = float(water_str)

            # Check manual override toggle (optional - don't fail if missing)
            if self.config.manual_override_entity:
                manual = self.ha_client.get_state_value(self.config.manual_override_entity)
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
        success: bool,
        duration_ms: int,
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
            # Commanded values
            commanded_work_mode=decision.work_mode,
            commanded_grid_charging=1 if decision.grid_charging else 0,
            commanded_charge_current_a=decision.charge_current_a,
            commanded_discharge_current_a=decision.discharge_current_a,
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
            override_type=override.override_type.value if override.override_needed else None,
            override_reason=override.reason if override.override_needed else None,
            # Result
            success=1 if success else 0,
            duration_ms=duration_ms,
            source="native",
            executor_version=EXECUTOR_VERSION,
        )

    def _update_battery_cost(
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

            # Grid charge: if grid charging is enabled and charge current > 0
            grid_charge_kwh = 0.0
            if decision.grid_charging and decision.charge_current_a > 0:
                # Rough estimate: charge_current_a * voltage / 1000 * efficiency * duration
                voltage_v = self.config.controller.system_voltage_v or 48.0
                efficiency = self.config.controller.charge_efficiency or 0.92
                charge_kw = (decision.charge_current_a * voltage_v / 1000.0) * efficiency
                grid_charge_kwh = charge_kw * slot_duration_h

            # PV charge: if PV exceeds load, surplus goes to battery
            pv_charge_kwh = 0.0
            if state.current_pv_kw and state.current_load_kw:
                pv_surplus_kw = max(0.0, state.current_pv_kw - state.current_load_kw)
                pv_charge_kwh = pv_surplus_kw * slot_duration_h * 0.95  # 95% efficiency

            # Get current import price
            import_price = 0.5  # Default fallback
            try:
                from inputs import get_nordpool_data

                prices = get_nordpool_data("config.yaml")
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
            except Exception:
                pass

            # Always update to keep energy state synced (cost only changes during charge)
            tracker.update_cost(
                current_soc_percent=state.current_soc_percent or 50.0,
                grid_charge_kwh=grid_charge_kwh,
                pv_charge_kwh=pv_charge_kwh,
                import_price_sek=import_price,
            )

        except Exception as e:
            logger.debug("Battery cost update skipped: %s", e)
