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

import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import pytz
# import yaml

# Import existing HA config loader
from inputs import load_home_assistant_config, _load_yaml

from .actions import ActionDispatcher, ActionResult, HAClient
from .config import load_executor_config
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
    last_run_at: Optional[str] = None
    last_run_status: str = "pending"
    last_error: Optional[str] = None
    next_run_at: Optional[str] = None
    current_slot: Optional[str] = None
    last_action: Optional[str] = None
    override_active: bool = False
    override_type: Optional[str] = None


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
        self._full_config = _load_yaml(config_path)

        # Initialize components
        self.history = ExecutionHistory(
            db_path=self._get_db_path(),
            timezone=self.config.timezone,
        )

        self.ha_client: Optional[HAClient] = None
        self.dispatcher: Optional[ActionDispatcher] = None

        # Status tracking
        self.status = ExecutorStatus(
            enabled=self.config.enabled,
            shadow_mode=self.config.shadow_mode,
        )

        # Threading
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Quick action storage (user-initiated time-limited overrides)
        self._quick_action: Optional[Dict[str, Any]] = None  # {type, expires_at, reason}

    def _get_db_path(self) -> str:
        """Get the path to the learning database."""
        # Use the same database as the learning engine
        return os.path.join("data", "planner_learning.db")

    def _init_ha_client(self) -> bool:
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

    def get_status(self) -> Dict[str, Any]:
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

        # Get quick action status BEFORE acquiring lock (it has its own lock)
        quick_action_status = self._get_quick_action_status()

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
                "version": EXECUTOR_VERSION,
            }

    def _get_quick_action_status(self) -> Optional[Dict[str, Any]]:
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
            }

    def set_quick_action(self, action_type: str, duration_minutes: int) -> Dict[str, Any]:
        """
        Set a time-limited quick action override.

        Args:
            action_type: One of 'force_charge', 'force_export', 'force_stop'
            duration_minutes: How long the override should last (15, 30, 60)

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

    def clear_quick_action(self) -> Dict[str, Any]:
        """Clear any active quick action."""
        with self._lock:
            was_active = self._quick_action is not None
            self._quick_action = None

        if was_active:
            logger.info("Quick action cleared by user")

        return {"success": True, "was_active": was_active}

    def get_active_quick_action(self) -> Optional[Dict[str, Any]]:
        """Get the currently active quick action, if any and not expired."""
        return self._get_quick_action_status()

    def start(self) -> None:
        """Start the executor loop in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Executor already running")
            return

        if not self._init_ha_client():
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

    def run_once(self) -> Dict[str, Any]:
        """
        Run a single execution tick synchronously.

        Returns the execution result.
        """
        if not self.ha_client and not self._init_ha_client():
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
                    break  # Stop event was set
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
                    if (now - last_run).total_seconds() < min_interval:
                        logger.debug(
                            "Skipping - already ran %.0fs ago", (now - last_run).total_seconds()
                        )
                        self._stop_event.wait(30)
                        continue
                except Exception as e:
                    logger.debug("Could not parse last_run_at: %s", e)

            # Execute tick
            try:
                logger.info("Executing scheduled tick...")
                self._tick()
            except Exception as e:
                logger.exception("Executor tick failed: %s", e)
                self.status.last_run_status = "error"
                self.status.last_error = str(e)

            # Wait a bit before next iteration
            self._stop_event.wait(5)

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

    def _tick(self) -> Dict[str, Any]:
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

        result = {
            "success": True,
            "executed_at": now_iso,
            "slot_start": None,
            "actions": [],
            "override": None,
            "error": None,
        }

        try:
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
                    actions = {
                        "work_mode": self.config.inverter.work_mode_zero_export,
                        "grid_charging": True,
                        "soc_target": 100,  # Charge to max
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
            )

            self.status.last_action = decision.reason

            # 6. Execute actions
            action_results: List[ActionResult] = []
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

            self.status.last_run_status = "success"
            logger.info("Executor tick completed in %dms", duration_ms)

        except Exception as e:
            logger.exception("Executor tick failed: %s", e)
            result["success"] = False
            result["error"] = str(e)
            self.status.last_run_status = "error"
            self.status.last_error = str(e)

            if self.dispatcher:
                self.dispatcher.notify_error(str(e))

        return result

    def _load_current_slot(self, now: datetime) -> tuple[Optional[SlotPlan], Optional[str]]:
        """
        Load the current slot from schedule.json.

        Returns (SlotPlan, slot_start_iso) or (None, None) if not found.
        """
        schedule_path = self.config.schedule_path
        if not os.path.exists(schedule_path):
            logger.warning("Schedule file not found: %s", schedule_path)
            return None, None

        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
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
                if start.tzinfo is None:
                    start = tz.localize(start)
                else:
                    start = start.astimezone(tz)

                if end_str:
                    end = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                    if end.tzinfo is None:
                        end = tz.localize(end)
                    else:
                        end = end.astimezone(tz)
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

    def _parse_slot_plan(self, slot_data: Dict[str, Any]) -> SlotPlan:
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
            # Get SoC
            soc_str = self.ha_client.get_state_value(soc_entity)
            if soc_str and soc_str not in ("unknown", "unavailable"):
                state.current_soc_percent = float(soc_str)

            # Get PV power
            pv_str = self.ha_client.get_state_value(pv_power_entity)
            if pv_str and pv_str not in ("unknown", "unavailable"):
                state.current_pv_kw = float(pv_str) / 1000  # W to kW

            # Get load power
            load_str = self.ha_client.get_state_value(load_power_entity)
            if load_str and load_str not in ("unknown", "unavailable"):
                state.current_load_kw = float(load_str) / 1000

            # Get current work mode
            work_mode = self.ha_client.get_state_value(self.config.inverter.work_mode_entity)
            if work_mode:
                state.current_work_mode = work_mode

            # Get grid charging state
            grid_charge = self.ha_client.get_state_value(self.config.inverter.grid_charging_entity)
            state.grid_charging_enabled = grid_charge == "on"

            # Get water heater temp
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
        slot_start: Optional[str],
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
