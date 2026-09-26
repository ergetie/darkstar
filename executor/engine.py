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
import os
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz

# import yaml
from backend.core.ev_live_state import (
    EVPlugState,
    consume_soc_recoveries,
    read_ev_live_state,
    stale_soc_episodes,
)
from backend.core.ev_plug import is_unreachable_state
from backend.core.ha_timestamps import reading_timestamp

# Import existing HA config loader
from backend.core.secrets import load_home_assistant_config
from backend.loads.service import LoadDisaggregator

from .actions import ActionDispatcher, ActionResult, HAClient
from .config import (
    BalancedLoadType,
    EVChargerDeviceConfig,
    heal_give_way_order,
    load_executor_config,
    load_yaml,
)
from .controller import ControllerDecision, make_decision
from .ev_surplus import (
    EVSurplusController,
    PhaseModeController,
    one_phase_min_kw,
    three_phase_min_kw,
)
from .goal_risk import pause_puts_goal_at_risk
from .history import ExecutionHistory, ExecutionRecord
from .load_balancer import (
    EVBalancerInput,
    EVBalancerOutput,
    LoadBalancer,
    LoadBalancerStatus,
    ShedLoadInput,
    classify_phase_sensor_unit,
    planned_kw_to_amps,
    power_to_current_a,
)
from .override import (
    OverrideResult,
    SlotPlan,
    SystemState,
    evaluate_overrides,
)

logger = logging.getLogger(__name__)

EXECUTOR_VERSION = "1.0.0"

# Marker substring appended to the tick reason text when a charger is held on
# solely via keep_on_after_target (no planned kW) — set regardless of whether
# battery source isolation triggers, so battery-less systems still surface it.
# Frontend history rows match this exact string to render the standby badge
# (task 2.9/4.4) — keep it a documented literal shared by both, since there is
# no DB column.
EV_KEEP_ON_REASON_MARKER = "EV keep-on active"

# Consecutive-tick threshold before a command-failure push; deterministic
# rejections, so lower than the EV zero-power threshold (5).
ACTION_FAILURE_NOTIFY_STREAK = 3


# Minimum gap between EV charge failure/recovery replans (ev-charge-failure-detection).
EV_FAILURE_REPLAN_COOLDOWN_S = 300


@dataclass
class EVChargerState:
    """Per-device EV charger runtime state."""

    charging_active: bool = False
    charging_slot_end: datetime | None = None

    # universal-load-balancing: phases the car is actually drawing on this
    # session, measured from the charger's own per-phase sensors. None until
    # the first measurement (callers fall back to the configured `phases`).
    active_phases: list[int] | None = None
    # Last commanded ampere setpoint for type="current" chargers (None = stopped/paused)
    current_setpoint_a: int | None = None
    # When current_setpoint_a last changed value (None = stopped/paused).
    setpoint_changed_at: datetime | None = None
    # ev-measured-draw: amps per phase the car actually draws this tick
    # (None = no trustworthy measurement).
    measured_draw_a: float | None = None
    # ev-missed-goal-recovery: the charger's switch entity last read
    # unavailable/unknown (charger unreachable, not unplugged).
    unreachable: bool = False


@dataclass
class ManualCharge:
    """A user-started "charge now to target SoC" on one charger (ev-manual-charge)."""

    target_soc: int
    current_a: int | None  # None = charger's max_current_a (always None for binary)
    started_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_soc": self.target_soc,
            "current_a": self.current_a,
            "started_at": self.started_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ManualCharge | None":
        """Parse a persisted entry; None when malformed."""
        if not isinstance(data, dict):
            return None
        raw = cast("dict[str, Any]", data)
        try:
            started_at = datetime.fromisoformat(str(raw["started_at"]))
            if started_at.tzinfo is None:
                return None
            current_raw = raw.get("current_a")
            return cls(
                target_soc=int(raw["target_soc"]),
                current_a=int(current_raw) if current_raw is not None else None,
                started_at=started_at,
            )
        except (KeyError, TypeError, ValueError):
            return None


# Safety timeout for a manual EV charge whose end condition never fires.
EV_MANUAL_CHARGE_TIMEOUT = timedelta(hours=24)
# Key of the manual charge inside a charger's ev_multi_day_state.json entry.
EV_MANUAL_CHARGE_STATE_KEY = "manual_charge"
# Safety timeout for the battery Top Up (force_charge) quick action.
FORCE_CHARGE_TIMEOUT = timedelta(hours=24)


@dataclass
class _EVWriteBackoff:
    """Per-charger failure backoff after a failed EV write."""

    desired_key: str
    failures: int
    until: datetime


@dataclass
class _EVFailureDedup:
    """Last recorded EV failure for one (charger, action) pair."""

    signature: tuple[str, str]
    first_at: datetime
    suppressed: int = 0


EV_FAILURE_DEDUP_WINDOW = timedelta(minutes=5)
EV_BACKOFF_BASE_S = 60
EV_BACKOFF_MAX_S = 600


# Thresholds for treating a charger's per-phase sensor reading as "drawing power"
_EV_PHASE_ACTIVE_THRESHOLD_A = 0.5
_EV_PHASE_ACTIVE_THRESHOLD_W = 100.0

# Seconds a new setpoint must stand before the car's measured draw is trusted
# as the baseline for further amps adjustments (the car needs time to follow).
EV_DRAW_SETTLE_S = 30
# After a commanded phase switch, the charger's measured active phases may
# still describe the old mode for a while; the balancer attributes the union
# of measured and commanded phases during this window (protective).
PHASE_SWITCH_SETTLE_S = 60

# Sentinel: no load-balancer override present for this charger this tick —
# _control_ev_charger_current computes its own target from the plan.
_NO_BALANCER_OVERRIDE = object()


def _values_equal(state: Any, expected: Any) -> bool:
    """Case/whitespace-insensitive comparison of an HA state to a target value."""
    return state is not None and str(state).strip().casefold() == str(expected).strip().casefold()


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
        self._tick_lock = threading.Lock()

        # Quick action storage (user-initiated time-limited overrides)
        self._quick_action: dict[str, Any] | None = None  # {type, expires_at, reason}

        # Pause state (idle mode with reminder)
        self._paused_at: datetime | None = None
        self._pause_reminder_sent: bool = False

        # Water boost state
        self._water_boost_until: dict[str, datetime] = {}
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
        # Per-charger write failure backoff and per-(charger, action) failure dedup
        self._ev_write_backoff: dict[str, _EVWriteBackoff] = {}
        self._ev_failure_dedup: dict[tuple[str, str], _EVFailureDedup] = {}
        # ev-manual-charge: active manual charges per charger id, persisted in
        # data/ev_multi_day_state.json so a restart resumes them.
        self._ev_manual_charge: dict[str, ManualCharge] = self._load_ev_manual_charges()
        self._ev_manual_replan_pending: bool = False

        # excess-pv-priority-dispatch: per-charger surplus feedback + phase-mode
        # controllers, and this tick's surplus-computed ampere targets (consumed
        # by _run_load_balancer / _control_ev_charger in place of the plan-derived
        # target for surplus-eligible chargers).
        self._ev_surplus_controllers: dict[str, EVSurplusController] = {}
        # Latest schedule.json meta (ev_goal_diagnostics for pause notifications).
        self._last_schedule_meta: dict[str, Any] = {}
        # Why each charger was last switched to 1-phase for overload relief
        # (status surface, e.g. "1-phase on L1 — relieving L3").
        self._ev_relief_reason: dict[str, str] = {}
        self._ev_phase_controllers: dict[str, PhaseModeController] = {}
        self._ev_surplus_targets: dict[str, int | None] = {}
        self._last_surplus_state: dict[str, str] = {}
        self._last_phase_mode: dict[str, str] = {}
        # This tick's per-charger surplus state, for the execution-log
        # throttle (task 3.8) and the synthetic "ev_surplus" history entry.
        self._ev_surplus_status: dict[str, dict[str, str]] = {}
        self._last_logged_surplus_states: dict[str, str] = {}
        self._last_measured_surplus_kw: float | None = None

        # Real-time per-phase load balancer (universal-load-balancing)
        self._load_balancer = LoadBalancer(self.config.load_balancing)
        self._last_balancer_status: LoadBalancerStatus | None = None
        self._last_balancer_planned_targets: dict[str, int | None] = {}

        # Sustained-throttle early replan (load-balancing-completion 4.x):
        # per-charger start of the continuous balancer-constrained period,
        # and the last balancer-triggered replan (global rate limit).
        self._balancer_throttled_since: dict[str, datetime] = {}
        self._last_balancer_replan_at: datetime | None = None

        # Intervention notifications (load-balancing-completion 5.x): previous
        # per-device balancer states, to notify once per qualifying transition.
        self._notified_ev_states: dict[str, str] = {}
        self._notified_shed_states: dict[str, bool] = {}

        # Execution-log throttling state (5.2): log only on change or once per
        # 15-min slot heartbeat, so high-frequency ticks don't flood the DB.
        self._last_logged_mode_intent: str | None = None
        self._last_logged_override_type: str | None = None
        self._last_logged_balancer_state: str | None = None
        self._last_heartbeat_slot_bucket: str | None = None

        # REV F76 Phase 5: Smart logging state tracking (Issue 4 fix)
        self._ev_detected_last_tick = False

        # REV F76 Phase 5: Fail-safe error tracking (Issue 1 fix)
        self._ev_power_fetch_failed = False

        # EV charge failure detection
        self._ev_zero_power_ticks: int = 0
        self._ev_failure_notified: bool = False
        # A failure fired this commanded period; the first >0.1kW afterwards
        # requests a recovery replan (ev-charge-failure-detection).
        self._ev_failure_recovery_pending: bool = False
        # Own cooldown for failure/recovery replans, separate from the
        # balancer's once-per-interval limit so a recovery soon after a
        # failure is not dropped.
        self._last_ev_failure_replan_at: datetime | None = None

        # Command-failure streak tracking, per action type
        self._action_fail_counts: dict[str, int] = {}
        self._action_fail_notified: set[str] = set()

        # Recent errors tracking (Phase 3)
        self.recent_errors: collections.deque[dict[str, Any]] = collections.deque(maxlen=10)

        # Load disaggregator for EV power monitoring (REV F76)
        self._load_disaggregator = LoadDisaggregator(self._full_config)

        # Async background tasks reference (RUF006 fix)
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # ev-plug-in-reminder dedupe: charger_id -> start of the window reminded for
        self._plug_in_reminder_sent: dict[str, datetime] = {}
        # ev-soc-staleness: chargers already notified in their current stale episode
        self._soc_stale_notified: set[str] = set()

        # Config and profile mtime caching
        self._config_mtime: float | None = None
        self._profile_mtime: float | None = None

    def _get_db_path(self) -> str:
        """Get the path to the learning database."""
        # Use the same database as the learning engine. Honour DB_PATH so it
        # stays consistent with main.py / Alembic (and lets tests redirect to a
        # throwaway DB), falling back to the shared default.
        return os.getenv("DB_PATH") or str(Path("data") / "planner_learning.db")

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
            self._load_balancer.config = self.config.load_balancing
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
                    "ev_keep_on": slot.ev_keep_on,
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
            action_type: One of 'force_charge', 'force_stop'
            duration_minutes: How long the override should last (15, 30, 60)
            params: Optional parameters (e.g., {'target_soc': 80})

        Returns:
            Status dict with expires_at
        """
        valid_types = ["force_charge", "force_stop", "force_heat"]
        if action_type not in valid_types:
            raise ValueError(f"Invalid action type: {action_type}. Must be one of {valid_types}")

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        if action_type == "force_charge":
            # Top Up runs until the battery reaches target_soc (ended in the
            # tick); the expiry is only a safety timeout, so the duration list
            # does not apply.
            target_soc = self._validate_force_charge_target(params or {})
            params = {**(params or {}), "target_soc": target_soc}
            expires_at = now + FORCE_CHARGE_TIMEOUT
            reason = f"User activated Top Up to {target_soc}%"
        else:
            if duration_minutes not in [15, 30, 60]:
                raise ValueError(
                    f"Invalid duration: {duration_minutes}. Must be 15, 30, or 60 minutes"
                )
            expires_at = now + timedelta(minutes=duration_minutes)
            reason = f"User activated {action_type} for {duration_minutes} minutes"

        with self._lock:
            self._quick_action = {
                "type": action_type,
                "expires_at": expires_at.isoformat(),
                "reason": reason,
                "created_at": now.isoformat(),
                "params": params or {},
            }

        logger.info("Quick action set: %s (expires %s)", reason, expires_at.isoformat())

        return {
            "success": True,
            "type": action_type,
            "duration_minutes": duration_minutes,
            "expires_at": expires_at.isoformat(),
        }

    def _validate_force_charge_target(self, params: dict[str, Any]) -> int:
        """Validate a Top Up target against min SoC, 100% and the live battery SoC."""
        try:
            target_soc = int(params.get("target_soc", 100))
        except (TypeError, ValueError) as e:
            raise ValueError("Target SoC must be a whole number") from e

        battery_raw: Any = self._full_config.get("battery")
        battery_cfg: dict[str, Any] = (
            cast("dict[str, Any]", battery_raw) if isinstance(battery_raw, dict) else {}
        )
        min_soc = float(battery_cfg.get("min_soc_percent", 10.0))
        if not min_soc <= target_soc <= 100:
            raise ValueError(f"Target SoC must be between {min_soc:.0f} and 100%")

        state = self._last_system_state
        if state is None:
            raise ValueError("Battery SoC is unknown")
        if state.current_soc_percent >= target_soc:
            raise ValueError(
                f"Target already reached (battery SoC {state.current_soc_percent:.0f}% "
                f"≥ {target_soc}%)"
            )
        return target_soc

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

    def set_water_boost(
        self, duration_minutes: int, heater_ids: list[str] | None = None
    ) -> dict[str, Any]:
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

        configured_ids = [device.id for device in self.config.water_heater_devices]
        selected_ids = configured_ids if heater_ids is None else list(dict.fromkeys(heater_ids))
        unknown_ids = [heater_id for heater_id in selected_ids if heater_id not in configured_ids]
        if unknown_ids:
            return {
                "success": False,
                "error": f"Unknown water heater id: {unknown_ids[0]}",
                "unknown_heater_ids": unknown_ids,
            }
        # Preserve the legacy single-heater boost when no entity-array devices exist.
        if not selected_ids and self._has_water_heater:
            selected_ids = ["__legacy__"]
        if not selected_ids:
            return {"success": False, "error": "No water heater control entity configured"}

        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)
        expires_at = now + timedelta(minutes=duration_minutes)

        with self._lock:
            for heater_id in selected_ids:
                self._water_boost_until[heater_id] = expires_at

        logger.info(
            "Water boost started for %d minutes for %s (until %s)",
            duration_minutes,
            ", ".join(selected_ids),
            expires_at.isoformat(),
        )

        # Emit WebSocket event
        self._emit_water_boost_status(force=True)

        return {
            "success": True,
            "expires_at": expires_at.isoformat(),
            "duration_minutes": duration_minutes,
            "heater_ids": selected_ids,
            "temp_target": self.config.water_heater.temp_boost,
        }

    def clear_water_boost(self, heater_ids: list[str] | None = None) -> dict[str, Any]:
        """Cancel active water boost for selected heaters."""
        configured_ids = [device.id for device in self.config.water_heater_devices]
        selected_ids = list(dict.fromkeys(configured_ids if heater_ids is None else heater_ids))
        unknown_ids = [heater_id for heater_id in selected_ids if heater_id not in configured_ids]
        if unknown_ids:
            return {
                "success": False,
                "error": f"Unknown water heater id: {unknown_ids[0]}",
                "unknown_heater_ids": unknown_ids,
            }
        if not selected_ids and self._has_water_heater:
            selected_ids = ["__legacy__"]

        with self._lock:
            was_active = any(heater_id in self._water_boost_until for heater_id in selected_ids)
            for heater_id in selected_ids:
                self._water_boost_until.pop(heater_id, None)

        if was_active:
            logger.info("Water boost cancelled by user for %s", ", ".join(selected_ids))
            self._emit_water_boost_status(force=True)

        return {"success": True, "was_active": was_active, "heater_ids": selected_ids}

    def get_water_boost_status(self) -> dict[str, Any]:
        """Get per-heater water boost status with remaining time."""
        tz = pytz.timezone(self.config.timezone)
        now = datetime.now(tz)

        with self._lock:
            expired = [
                heater_id
                for heater_id, expires_at in self._water_boost_until.items()
                if now >= expires_at
            ]
            for heater_id in expired:
                self._water_boost_until.pop(heater_id, None)

            heaters = {
                heater_id: {
                    "expires_at": expires_at.isoformat(),
                    "remaining_seconds": int((expires_at - now).total_seconds()),
                }
                for heater_id, expires_at in self._water_boost_until.items()
            }
            latest_expiry = max(
                (expires_at for expires_at in self._water_boost_until.values()), default=None
            )
            return {
                "active": bool(heaters),
                "heaters": heaters,
                "expires_at": latest_expiry.isoformat() if latest_expiry else None,
                "remaining_seconds": int((latest_expiry - now).total_seconds())
                if latest_expiry
                else 0,
                "temp_target": self.config.water_heater.temp_boost,
            }

    def _emit_water_boost_status(self, force: bool = False) -> None:
        """Emit water boost status via WebSocket if changed or forced."""
        from backend.core.websockets import ws_manager

        current_status = self.get_water_boost_status()

        # Build event payload
        heaters = current_status.get("heaters", {})
        payload = {
            "active": bool(current_status.get("active")),
            "heaters": heaters,
            "expires_at": current_status.get("expires_at"),
            "remaining_seconds": current_status.get("remaining_seconds", 0),
        }

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

    # --- EV Manual Charge (ev-manual-charge) ---

    def _load_ev_manual_charges(self) -> dict[str, ManualCharge]:
        """Restore persisted manual charges for configured chargers."""
        from backend.core.ev_state import read_ev_state

        try:
            state = read_ev_state()
        except Exception as e:
            logger.warning("Could not restore EV manual charges: %s", e)
            return {}

        configured_ids = {c.id for c in self.config.ev_chargers}
        restored: dict[str, ManualCharge] = {}
        for charger_id, entry in cast("dict[str, Any]", state).items():
            raw = (
                cast("dict[str, Any]", entry).get(EV_MANUAL_CHARGE_STATE_KEY)
                if isinstance(entry, dict)
                else None
            )
            if raw is None:
                continue
            manual = ManualCharge.from_dict(raw)
            if manual is None:
                logger.warning("Ignoring malformed persisted manual charge for %s", charger_id)
                continue
            if charger_id not in configured_ids:
                logger.warning(
                    "Ignoring persisted manual charge for unknown/disabled charger %s", charger_id
                )
                continue
            restored[charger_id] = manual
            logger.info(
                "Resumed manual charge on %s: target %d%% (started %s)",
                charger_id,
                manual.target_soc,
                manual.started_at.isoformat(),
            )
        return restored

    @staticmethod
    def _persist_ev_manual_charge(charger_id: str, manual: ManualCharge | None) -> None:
        """Write (or remove, when None) a charger's manual charge; goal fields untouched."""
        from backend.core.ev_state import update_ev_state

        def _mutate(state: dict[str, dict[str, Any]]) -> None:
            entry = state.get(charger_id)
            if manual is None:
                if not isinstance(entry, dict):
                    return
                entry.pop(EV_MANUAL_CHARGE_STATE_KEY, None)
                if not entry:
                    state.pop(charger_id, None)
                return
            if not isinstance(entry, dict):
                entry = {}
            entry[EV_MANUAL_CHARGE_STATE_KEY] = manual.to_dict()
            state[charger_id] = entry

        try:
            update_ev_state(_mutate)
        except Exception as e:
            logger.error("Failed to persist manual charge for %s: %s", charger_id, e)

    def _ev_charger_cfg(self, charger_id: str) -> EVChargerDeviceConfig | None:
        return next((c for c in self.config.ev_chargers if c.id == charger_id), None)

    @staticmethod
    def _ev_charger_controllable(charger_cfg: EVChargerDeviceConfig) -> bool:
        """Whether Darkstar can actuate this charger (see _control_ev_charger)."""
        if charger_cfg.type == "current":
            return bool(charger_cfg.current_entity and charger_cfg.switch_entity)
        return bool(charger_cfg.switch_entity)

    def set_ev_manual_charge(
        self,
        charger_id: str,
        target_soc: int,
        current_a: int | None = None,
        *,
        current_soc_percent: float | None,
        plug_state: EVPlugState,
    ) -> dict[str, Any]:
        """Start a manual charge to ``target_soc`` on one charger.

        ``current_soc_percent``/``plug_state`` are the car's live readings from
        ``read_ev_live_state``, supplied by the caller. Raises ValueError with a user-facing message
        when the request is not allowed.
        """
        charger_cfg = self._ev_charger_cfg(charger_id)
        if charger_cfg is None:
            raise ValueError(f"Unknown or disabled EV charger: {charger_id}")
        if not self._ev_charger_controllable(charger_cfg):
            raise ValueError(f"EV charger {charger_id} is not controlled by Darkstar")
        if not 1 <= target_soc <= 100:
            raise ValueError("Target SoC must be between 1 and 100%")
        if current_a is not None:
            if charger_cfg.type != "current":
                raise ValueError("A charging current can only be set on current-type chargers")
            max_current_a = charger_cfg.max_current_a or charger_cfg.min_current_a
            if not charger_cfg.min_current_a <= current_a <= max_current_a:
                raise ValueError(
                    f"Charging current must be between {charger_cfg.min_current_a} "
                    f"and {max_current_a} A"
                )
        if plug_state == "unplugged":
            raise ValueError("The car is not connected")
        if plug_state == "unknown":
            raise ValueError("The car's plug state is unknown (charger unreachable)")
        if current_soc_percent is None:
            raise ValueError("The car's SoC is unknown")
        if current_soc_percent >= target_soc:
            raise ValueError(
                f"Target already reached (car SoC {current_soc_percent:.0f}% ≥ {target_soc}%)"
            )

        tz = pytz.timezone(self.config.timezone)
        manual = ManualCharge(
            target_soc=target_soc, current_a=current_a, started_at=datetime.now(tz)
        )
        with self._lock:
            self._ev_manual_charge[charger_id] = manual
        self._persist_ev_manual_charge(charger_id, manual)

        logger.info(
            "Manual charge started on %s: target %d%%%s (car SoC %.0f%%)",
            charger_id,
            target_soc,
            f" at {current_a} A" if current_a is not None else "",
            current_soc_percent,
        )
        self._emit_ev_manual_charge_status()
        return {"success": True, "charger_id": charger_id, **manual.to_dict()}

    def clear_ev_manual_charge(
        self, charger_id: str, reason: str = "stopped by user"
    ) -> dict[str, Any]:
        """End a charger's manual charge; the plan takes over on the next tick."""
        with self._lock:
            manual = self._ev_manual_charge.pop(charger_id, None)
        if manual is None:
            return {"success": True, "was_active": False}

        self._persist_ev_manual_charge(charger_id, None)
        # Replan from the next tick (rate-limited there), so control returns
        # to a plan that knows the car's new SoC.
        self._ev_manual_replan_pending = True
        logger.info("Manual charge on %s ended: %s", charger_id, reason)
        self._emit_ev_manual_charge_status()
        return {"success": True, "was_active": True}

    def get_ev_manual_charge_status(self) -> dict[str, dict[str, Any]]:
        """Active manual charges per charger id."""
        with self._lock:
            return {
                charger_id: {
                    **manual.to_dict(),
                    "expires_at": (manual.started_at + EV_MANUAL_CHARGE_TIMEOUT).isoformat(),
                }
                for charger_id, manual in self._ev_manual_charge.items()
            }

    def _ev_manual_charge_active(self, charger_id: str) -> bool:
        return charger_id in self._ev_manual_charge

    def _ev_manual_target_a(self, charger_cfg: EVChargerDeviceConfig) -> int | None:
        """Requested amps for a current-type charger under manual charge, else None."""
        manual = self._ev_manual_charge.get(charger_cfg.id)
        if manual is None:
            return None
        if manual.current_a is not None:
            return manual.current_a
        return charger_cfg.max_current_a or charger_cfg.min_current_a

    def _emit_ev_manual_charge_status(self) -> None:
        from backend.core.websockets import ws_manager

        try:
            ws_manager.emit_sync(
                "ev_manual_charge_updated", {"chargers": self.get_ev_manual_charge_status()}
            )
        except Exception as e:
            logger.warning("Failed to emit EV manual charge status: %s", e)

    async def _check_ev_manual_charge_end(self, now: datetime) -> None:
        """End manual charges whose car reached target, was unplugged, or timed out.

        SoC and plug come from the shared ``read_ev_live_state``. An unknown SoC
        or plug reading keeps the charge running (until the reading returns or
        the safety timeout elapses).
        """
        with self._lock:
            active = dict(self._ev_manual_charge)

        for charger_id, manual in active.items():
            charger_cfg = self._ev_charger_cfg(charger_id)
            if charger_cfg is None:
                self.clear_ev_manual_charge(charger_id, "charger no longer configured")
                continue
            if now - manual.started_at >= EV_MANUAL_CHARGE_TIMEOUT:
                self.clear_ev_manual_charge(charger_id, "24 h safety timeout")
                continue
            if not self.ha_client:
                continue

            live = await read_ev_live_state(
                charger_id,
                self.ha_client.get_state_value,
                soc_sensor=charger_cfg.soc_sensor,
                plug_sensor=charger_cfg.plug_sensor,
                plugged_in_states=charger_cfg.plugged_in_states,
            )
            if live.soc_percent is not None and live.soc_percent >= manual.target_soc:
                self.clear_ev_manual_charge(
                    charger_id,
                    f"target reached ({live.soc_percent:.0f}% ≥ {manual.target_soc}%)",
                )
                continue
            if live.plug == "unplugged":
                self.clear_ev_manual_charge(charger_id, "car unplugged")

    def _maybe_request_ev_manual_replan(self, now: datetime) -> None:
        """Replan once after a manual charge ended, subject to the executor's
        replan rate limit (a skipped request is covered by the next scheduled run)."""
        if not self._ev_manual_replan_pending:
            return
        self._ev_manual_replan_pending = False
        if not self._executor_replan_allowed(now):
            logger.debug("Manual charge ended — replan skipped (rate limit)")
            return
        logger.info("Manual charge ended — requesting replan")
        self._request_balancer_replan()

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
        if not self._tick_lock.acquire(blocking=False):
            logger.warning("Executor tick already running, skipping concurrent request")
            self.status.last_run_status = "skipped"
            self.status.last_skip_reason = "tick_already_running"
            return {"success": False, "skipped": True, "reason": "tick_already_running"}

        try:
            return await self._tick_unlocked()
        finally:
            self._tick_lock.release()

    async def _tick_unlocked(self) -> dict[str, Any]:
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
        # execution_log.executed_at is local ISO with offset (this tz), unlike
        # slot_plans.created_at (naive UTC) — compare only after converting to a common tz.
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

            # Update state with slot validity
            state.slot_exists = slot is not None
            state.slot_valid = slot is not None

            # D1: Honor manual override — skip all writes but keep telemetry
            skip_writes = state.manual_override_active

            # ev-manual-charge: end manual charges whose condition fired, before
            # any EV decision this tick, then replan if one ended.
            if self._ev_manual_charge:
                await self._check_ev_manual_charge_end(now)
            self._maybe_request_ev_manual_replan(now)

            # ev-goal-lifecycle-feedback D7/D8: planned EV charging is only
            # actionable for chargers that are live-plugged (the plan may include
            # assumed-plugged slots for a car that is away). Gate the slot once
            # so switch control, source isolation, surplus and the balancer all
            # see the same actionable plan; remind the user to plug in.
            if slot is not None and self._has_ev_charger and self.config.ev_chargers:
                plug_states = await self._read_ev_plug_states()
                await self._check_plug_in_reminders(now, plug_states)
                slot = self._gate_ev_plan_on_plug_state(slot, plug_states)
            if self._has_ev_charger and self.config.ev_chargers:
                await self._check_ev_soc_stale()

            # 4. Check for active Quick Action OR Water Boost
            quick_action = self._get_quick_action_status()
            if quick_action and quick_action["type"] == "force_charge":
                target_soc = float(quick_action.get("params", {}).get("target_soc", 100))
                if state.current_soc_percent >= target_soc:
                    logger.info(
                        "Top Up target reached (SoC %.1f%% >= %.0f%%) - following schedule",
                        state.current_soc_percent,
                        target_soc,
                    )
                    with self._lock:
                        self._quick_action = None
                    quick_action = None
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
            elif water_boost.get("active"):
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
                        self._water_boost_until.clear()
                    # Send notification
                    if self.dispatcher:
                        await self.dispatcher._send_notification(  # type: ignore[protected-access]
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
                            "water_temps": {
                                heater_id: self.config.water_heater.temp_boost
                                for heater_id in water_boost["heaters"]
                                if heater_id != "__legacy__"
                            },
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
            slot_keep_on_active = bool(slot and any(slot.ev_keep_on.values()))
            # An active manual charge counts as scheduled so source isolation
            # blocks battery discharge from its first tick.
            scheduled_ev_charging = (
                (ev_charging_kw > 0.1 if ev_charging_kw else False)
                or slot_keep_on_active
                or bool(self._ev_manual_charge)
            )

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
            # excess-pv-priority-dispatch 3.4: surplus slots have ev_charging_kw=0
            # (surplus is eligibility, not a scheduled plan), so isolation must
            # also trigger on surplus eligibility directly — waiting for the
            # actual-power sensor to catch up would leave a brief window where
            # the battery could discharge into the EV during surplus charging.
            surplus_eligible: bool = bool(
                slot and any(v > 0.01 for v in slot.ev_surplus_kw.values())
            )
            # Source isolation: Block discharge for scheduled, actual, or surplus-eligible charging
            ev_should_charge_block: bool = (
                scheduled_ev_charging or actual_ev_charging or surplus_eligible
            )

            # Preserve original slot before EV source isolation may overwrite discharge_kw
            original_slot = slot
            ev_isolation_reason: str | None = None
            ev_charge_failed = False

            # Charger IDs on solely via the keep-on flag (no planned power).
            # Computed unconditionally (not gated on _has_battery) so the tick
            # reason text names them even on battery-less systems, where there
            # is no discharge to isolate but the switch is still held on.
            keep_on_charger_ids = sorted(
                charger_id
                for charger_id, active in original_slot.ev_keep_on.items()
                if active and original_slot.ev_charger_plans.get(charger_id, 0.0) <= 0.1
            )

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
                    ev_keep_on=slot.ev_keep_on,  # Preserve for _follow_plan's keep-on idle check
                )

                # Set isolation/keep-on reason for execution record
                actual_for_reason = actual_ev_power_kw if not self._ev_power_fetch_failed else 0.0
                ev_isolation_reason = self._build_ev_reason_note(
                    True, ev_charging_kw, actual_for_reason, keep_on_charger_ids
                )
            else:
                # REV F76 Phase 5 (Issue 4): Smart state-based logging
                if self._ev_detected_last_tick and not self._ev_power_fetch_failed:
                    # State transition: EV stopped charging
                    # Note: Skip if in fail-safe mode (sensor failure, not actual EV)
                    logger.info(
                        "EV charging ended - Source isolation: Resuming normal battery operation"
                    )
                self._ev_detected_last_tick = False

                # No battery to isolate (or isolation didn't trigger), but a
                # charger may still be held on solely via keep-on — surface it
                # in the reason text regardless (battery-less systems).
                ev_isolation_reason = self._build_ev_reason_note(
                    False, ev_charging_kw, actual_ev_power_kw, keep_on_charger_ids
                )

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

            # excess-pv-priority-dispatch 3.2/3.3/3.5: surplus feedback + phase-mode
            # state machines run first, populating self._ev_surplus_targets —
            # consumed by _run_load_balancer below in place of the plan-derived
            # target for surplus-eligible chargers (order: surplus feedback
            # proposes amps -> phase-mode may adjust mode/conversion -> balancer
            # cap clamps -> dispatch; the balancer clamp is authoritative).
            ev_surplus_phase_mode_results: list[ActionResult] = []
            if not skip_writes:
                ev_surplus_phase_mode_results = await self._update_ev_surplus_and_phase_mode(
                    state, original_slot, now
                )
            else:
                # Manual override active — no writes, and no stale surplus
                # targets from a previous tick should leak into the balancer.
                self._ev_surplus_targets = {}
                # Nor a stale measured draw from a previous tick.
                for ev_state in self._ev_charger_states.values():
                    ev_state.measured_draw_a = None

            # Real-time per-phase load balancing (universal-load-balancing 4.7):
            # runs after the controller decision, before dispatch; a no-op
            # (enabled=False, empty outputs) unless load_balancing.enabled and
            # prerequisites are configured.
            balancer_status = self._run_load_balancer(state, original_slot, now)
            self._last_balancer_status = balancer_status
            ev_surplus_phase_mode_results.extend(
                await self._apply_balancer_relief(
                    balancer_status, now, writes_allowed=not skip_writes
                )
            )

            # Sustained-throttle early replan + intervention notifications
            # (load-balancing-completion 4.x/5.x)
            self._track_balancer_throttling(balancer_status, now)
            await self._notify_balancer_interventions(balancer_status, original_slot, now)

            # Emit live metrics for UI sparklines (Rev E1) + balancer status (6.1)
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
                        "load_balancing": self.get_load_balancer_status(),
                    }
                )
            except Exception as e:
                logger.debug("Failed to emit live metrics: %s", e)

            balancer_ev_targets: dict[str, int | None] | None = None
            shed_water_heater_ids: set[str] = set()
            shed_binary_charger_ids: set[str] = set()
            if balancer_status.enabled:
                balancer_ev_targets = {
                    out.charger_id: out.target_a for out in balancer_status.ev_outputs
                }
                for shed_out in balancer_status.shed_outputs:
                    if not shed_out.shed:
                        continue
                    if shed_out.device_type == "water_heater":
                        shed_water_heater_ids.add(shed_out.load_id)
                    elif shed_out.device_type == "ev_charger":
                        shed_binary_charger_ids.add(shed_out.load_id)
            elif self._ev_surplus_targets:
                # excess-pv-priority-dispatch 3.3: the fuse balancer is off or
                # unconfigured, but surplus-eligible chargers still need their
                # feedback-computed target dispatched (there is no fuse cap to
                # clamp it against, so it is used verbatim — same as the fuse
                # balancer's own "disabled = zero behavior change" contract for
                # everything else).
                balancer_ev_targets = dict(self._ev_surplus_targets)

            # Control EV Charger Switch (per-device)
            if self._has_ev_charger and self.config.ev_chargers and not skip_writes:
                force_stop_ev = bool(quick_action and quick_action.get("type") == "force_stop")
                await self._control_ev_charger(
                    original_slot,
                    now,
                    force_stop=force_stop_ev,
                    balancer_ev_targets=balancer_ev_targets,
                    shed_binary_charger_ids=shed_binary_charger_ids,
                )

                # EV charge failure detection (5.1): based on the commanded
                # level (post-balancer), not the raw scheduled kW.
                commanded_active = any(
                    self._ev_charger_states[c.id].charging_active
                    for c in self.config.ev_chargers
                    if c.id in self._ev_charger_states
                )
                if await self._check_ev_charge_failure(
                    commanded_active, actual_ev_power_kw, now=now
                ):
                    ev_charge_failed = True
            elif self._has_ev_charger:
                self._ev_zero_power_ticks = 0
                self._ev_failure_notified = False
                self._ev_failure_recovery_pending = False

            # 6. Execute actions (skipped when manual_override_active — no inverter/EV/water writes)
            action_results: list[ActionResult] = list(ev_surplus_phase_mode_results)
            if self.dispatcher and not skip_writes:
                # REV UI11 Phase 7: Execute async actions
                try:
                    # Control Water Heater Temperature (per-device)
                    if self._has_water_heater:
                        if (
                            decision.water_temps or shed_water_heater_ids
                        ) and self.config.water_heater_devices:
                            # New multi-device format: control each heater independently
                            for device in self.config.water_heater_devices:
                                try:
                                    if not device.target_entity:
                                        continue
                                    temp = decision.water_temps.get(
                                        device.id, self.config.water_heater.temp_off
                                    )
                                    if device.id in shed_water_heater_ids:
                                        # Load-balancer shed takes precedence over the schedule
                                        temp = self.config.water_heater.temp_off
                                    if device.control_type == "switch":
                                        water_result = await self.dispatcher.set_water_switch(
                                            device.target_entity,
                                            temp > self.config.water_heater.temp_off,
                                        )
                                    else:
                                        water_result = await self.dispatcher.set_water_temp(
                                            temp, device.target_entity
                                        )
                                    action_results.append(water_result)
                                except Exception as exc:
                                    logger.exception(
                                        "Water heater '%s' dispatch failed; continuing with other heaters: %s",
                                        device.id,
                                        exc,
                                    )
                        elif getattr(self.config.water_heater, "target_entity", None):
                            # Legacy fallback: old-format schedule or single heater
                            water_result = await self.dispatcher.set_water_temp(decision.water_temp)
                            action_results.append(water_result)

                    # Load-balancer shed/restore: custom_entity loads (universal-load-balancing 4.5)
                    if balancer_status.enabled:
                        for shed_out in balancer_status.shed_outputs:
                            if shed_out.device_type != BalancedLoadType.CUSTOM_ENTITY.value:
                                continue
                            load_cfg = next(
                                (
                                    ld
                                    for ld in self.config.load_balancing.loads
                                    if ld.device_id == shed_out.load_id
                                ),
                                None,
                            )
                            if not load_cfg or not load_cfg.entity:
                                continue
                            value = load_cfg.off_value if shed_out.shed else load_cfg.on_value
                            shed_result = await self.dispatcher.set_balanced_entity(
                                load_cfg.entity, value
                            )
                            action_results.append(shed_result)

                    # Control Excess PV Custom Entity sinks (7.2-7.4, generalized to
                    # the priority list — excess-pv-priority-dispatch 3.7). Keyed by
                    # rank (index in excess_pv.priority[]), matching the solver's
                    # per-entry output (task 2.7).
                    is_fallback = (
                        override.override_needed
                        and override.override_type.value == "slot_failure_fallback"
                    )
                    for rank, entry in enumerate(self.config.excess_pv.priority):
                        if entry.type != "custom_entity" or not entry.entity:
                            continue
                        rank_key = str(rank)
                        if is_fallback:
                            custom_value = entry.off_value
                        else:
                            custom_value = (
                                entry.on_value
                                if original_slot.custom_entity_active.get(rank_key, False)
                                else entry.off_value
                            )
                        custom_result = await self.dispatcher.set_balanced_entity(
                            entry.entity, custom_value
                        )
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
                        except Exception as ws_err:
                            logger.debug("WebSocket broadcast failed: %s", ws_err)

                        # Command-failure streak notification (mirrors EV pattern)
                        count = self._action_fail_counts.get(r.action_type, 0) + 1
                        self._action_fail_counts[r.action_type] = count
                        if (
                            count >= ACTION_FAILURE_NOTIFY_STREAK
                            and r.action_type not in self._action_fail_notified
                        ):
                            fail_msg = (
                                f"Command failure: {r.action_type} failed {count}x — {r.message}"
                            )
                            if self.dispatcher:
                                await self.dispatcher.notify_error(fail_msg)
                            self._action_fail_notified.add(r.action_type)

                # Reset the failure streak for action types that succeeded (or were
                # skipped) this tick, so a future streak can notify again.
                for r in action_results:
                    if r.success or r.skipped:
                        self._action_fail_counts.pop(r.action_type, None)
                        self._action_fail_notified.discard(r.action_type)

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

            should_log, log_reasons = self._should_log_execution(
                now, decision, action_results, override, balancer_status, bool(record.success)
            )
            if balancer_status.enabled:
                # 4.5/5.2: balancer transitions are always logged with a reason
                # that includes per-phase currents, embedded in action_results
                # (no schema change — see impact notes in the change proposal).
                record.action_results = (record.action_results or []) + [
                    {
                        "type": "load_balancer",
                        "success": True,
                        "message": balancer_status.reason,
                        "state": balancer_status.state,
                        "phase_current_a": balancer_status.phase_current_a,
                        "phase_headroom_a": balancer_status.phase_headroom_a,
                        "skipped": False,
                        "error_details": None,
                    }
                ]
            if self._ev_surplus_status:
                # excess-pv-priority-dispatch 3.8: surplus transitions are
                # always auditable, same treatment as the balancer above.
                record.action_results = (record.action_results or []) + [
                    {
                        "type": "ev_surplus",
                        "success": True,
                        "message": info["reason"],
                        "charger_id": charger_id,
                        "state": info["state"],
                        "skipped": False,
                        "error_details": None,
                    }
                    for charger_id, info in self._ev_surplus_status.items()
                ]
            if should_log:
                self.history.log_execution(record)
                logger.debug("Execution logged: %s", "; ".join(log_reasons))

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
            except Exception as ws_err:
                logger.debug("WebSocket broadcast failed: %s", ws_err)

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
        # Kept for goal-at-risk pause notifications (ev_goal_diagnostics).
        self._last_schedule_meta = meta
        generated_at_str: str = str(meta.get("generated_at", "")) if meta else ""
        generated_at: datetime | None = None
        if generated_at_str:
            try:
                generated_at = datetime.fromisoformat(str(generated_at_str).replace("Z", "+00:00"))
                generated_at = (
                    tz.localize(generated_at)
                    if generated_at.tzinfo is None
                    else generated_at.astimezone(tz)
                )
            except Exception as e:
                logger.debug("Could not parse schedule generated_at: %s", e)
                generated_at = None

        if generated_at is None:
            msg = "Schedule has no generated_at — holding"
            logger.warning(msg)
            self._stale_schedule_warning = msg
            return None, None

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

        # Parse per-entry custom entity active flags (keyed by priority-list rank)
        raw_custom_entity_active = slot_data.get("custom_entity_active")
        custom_entity_active: dict[str, bool] = {}
        if isinstance(raw_custom_entity_active, dict):
            for k, v in raw_custom_entity_active.items():  # type: ignore[union-attr]
                custom_entity_active[str(k)] = bool(v)  # type: ignore[arg-type]

        # Parse per-charger EV surplus-eligible kW (excess-pv-priority-dispatch 3.1)
        raw_ev_surplus_kw = slot_data.get("ev_surplus_kw")
        ev_surplus_kw: dict[str, float] = {}
        if isinstance(raw_ev_surplus_kw, dict):
            for k, v in raw_ev_surplus_kw.items():  # type: ignore[union-attr]
                ev_surplus_kw[str(k)] = float(v)  # type: ignore[arg-type]

        # Parse per-charger keep-on-after-target flags (switch held on, no planned energy)
        raw_ev_keep_on = slot_data.get("ev_keep_on")
        ev_keep_on: dict[str, bool] = {}
        if isinstance(raw_ev_keep_on, dict):
            for k, v in raw_ev_keep_on.items():  # type: ignore[union-attr]
                ev_keep_on[str(k)] = bool(v)  # type: ignore[arg-type]

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
            ev_surplus_kw=ev_surplus_kw,
            ev_keep_on=ev_keep_on,
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
        net_grid_entity: str | None = None
        if meter_type == "dual":
            import_entity = input_sensors.get("grid_import_power")
            export_entity = input_sensors.get("grid_export_power")
            if import_entity:
                reads.append(("grid_import", lambda e=import_entity: ha.get_state_value(e)))
            if export_entity:
                reads.append(("grid_export", lambda e=export_entity: ha.get_state_value(e)))
        else:
            # excess-pv-priority-dispatch: net-meter surplus tracking needs
            # current_import_kw/current_export_kw populated too (design D3), so
            # read the single bidirectional grid_power sensor here.
            net_grid_entity = input_sensors.get("grid_power")
            if net_grid_entity:
                reads.append(("grid_power", lambda e=net_grid_entity: ha.get_state_value(e)))

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

        # Per-phase grid current/power sensors (universal-load-balancing,
        # load-balancing-power-sensors). Read full state (not just value) so
        # unit/device_class can be inspected and staleness judged from the
        # reading-freshness timestamp (last_reported, see ha_timestamps).
        phase_entities: dict[int, str] = {}
        for phase, key in ((1, "grid_current_l1"), (2, "grid_current_l2"), (3, "grid_current_l3")):
            entity = input_sensors.get(key)
            if entity:
                phase_entities[phase] = entity
                reads.append((f"grid_current_l{phase}", lambda e=entity: ha.get_state(e)))

        voltage_entities: dict[int, str] = {}
        for phase, key in (
            (1, "grid_voltage_l1"),
            (2, "grid_voltage_l2"),
            (3, "grid_voltage_l3"),
        ):
            entity = input_sensors.get(key)
            if entity:
                voltage_entities[phase] = entity
                reads.append((f"grid_voltage_l{phase}", lambda e=entity: ha.get_state(e)))

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

            net_str = results.get("grid_power")
            if net_str and net_str not in ("unknown", "unavailable"):
                grid_net_kw = float(net_str) / 1000
                if input_sensors.get("grid_power_inverted", False):
                    grid_net_kw = -grid_net_kw
                state.current_import_kw = max(0.0, grid_net_kw)
                state.current_export_kw = max(0.0, -grid_net_kw)

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

            if phase_entities:
                nominal_voltage_v = self.config.load_balancing.nominal_voltage_v
                grid_current_a: dict[int, float] = {}
                grid_current_updated_at: dict[int, datetime] = {}
                for phase in phase_entities:
                    phase_state = results.get(f"grid_current_l{phase}")
                    if not isinstance(phase_state, dict):
                        continue
                    phase_state = cast("dict[str, Any]", phase_state)
                    value_str = phase_state.get("state")
                    if value_str is None or value_str in ("unknown", "unavailable"):
                        continue
                    try:
                        raw_value = abs(float(value_str))
                    except (TypeError, ValueError):
                        continue

                    attributes = cast("dict[str, Any]", phase_state.get("attributes") or {})
                    unit_of_measurement = cast("str | None", attributes.get("unit_of_measurement"))
                    device_class = cast("str | None", attributes.get("device_class"))
                    kind = classify_phase_sensor_unit(unit_of_measurement, device_class)
                    power_updated_at = reading_timestamp(phase_state)

                    if kind == "current":
                        grid_current_a[phase] = raw_value
                        if power_updated_at is not None:
                            grid_current_updated_at[phase] = power_updated_at
                        continue

                    if kind not in ("power_w", "power_kw"):
                        logger.warning(
                            "Phase L%d sensor %s has unrecognized unit %r; skipping reading",
                            phase,
                            phase_entities[phase],
                            unit_of_measurement,
                        )
                        continue

                    power_w = raw_value * 1000 if kind == "power_kw" else raw_value
                    voltage_entity = voltage_entities.get(phase)
                    if voltage_entity:
                        voltage_state = results.get(f"grid_voltage_l{phase}")
                        if not isinstance(voltage_state, dict):
                            # Configured-but-missing voltage entity: skip this phase
                            # entirely (no grid_current_a entry) so the balancer's
                            # _is_stale treats it as missing → stale fail-safe fires
                            # (force min_current_a, then pause). Never substitute the
                            # nominal voltage for a configured-but-unreadable sensor.
                            continue
                        voltage_state = cast("dict[str, Any]", voltage_state)
                        v_value_str = voltage_state.get("state")
                        if v_value_str is None or v_value_str in ("unknown", "unavailable"):
                            continue
                        try:
                            voltage_v = float(v_value_str)
                        except (TypeError, ValueError):
                            continue
                        voltage_updated_at = reading_timestamp(voltage_state)
                        if power_updated_at is None or voltage_updated_at is None:
                            reading_updated_at = None
                        else:
                            reading_updated_at = min(power_updated_at, voltage_updated_at)
                    else:
                        voltage_v = nominal_voltage_v
                        reading_updated_at = power_updated_at

                    if voltage_v <= 0:
                        continue

                    grid_current_a[phase] = power_to_current_a(power_w, voltage_v)
                    if reading_updated_at is not None:
                        grid_current_updated_at[phase] = reading_updated_at

                state.grid_current_a = grid_current_a or None
                state.grid_current_updated_at = grid_current_updated_at or None

        except Exception as e:
            logger.warning("Failed to gather some system state: %s", e)

        return state

    def _should_log_execution(
        self,
        now: datetime,
        decision: ControllerDecision,
        action_results: list[ActionResult],
        override: OverrideResult,
        balancer_status: LoadBalancerStatus,
        record_success: bool = True,
    ) -> tuple[bool, list[str]]:
        """Execution-log throttling (5.2): log on change, else at most once per
        15-minute slot (heartbeat). Keeps 5s ticks from writing ~17k identical
        rows/day while preserving the audit trail history views read.
        """
        reasons: list[str] = []

        if not record_success:
            # A failed tick (e.g. ev_charge_failed, which sets success=0 without
            # necessarily producing a non-skipped/failed action_result) must
            # never be silently dropped by the heartbeat throttle.
            reasons.append("execution failed")

        if decision.mode_intent != self._last_logged_mode_intent:
            reasons.append(f"mode_intent -> {decision.mode_intent}")

        if any(not r.skipped for r in action_results):
            reasons.append("action dispatched")

        current_override_type = override.override_type.value if override.override_needed else None
        if current_override_type != self._last_logged_override_type:
            reasons.append(f"override -> {current_override_type}")

        if balancer_status.state != self._last_logged_balancer_state:
            reasons.append(f"balancer -> {balancer_status.state}")

        # excess-pv-priority-dispatch 3.8: surplus mode enter/exit, pause/resume,
        # and entity-unavailable fallback are always logged, mirroring the
        # balancer's own always-log-transitions treatment above.
        current_surplus_states = {
            charger_id: info["state"] for charger_id, info in self._ev_surplus_status.items()
        }
        if current_surplus_states != self._last_logged_surplus_states:
            for charger_id, state_val in current_surplus_states.items():
                if self._last_logged_surplus_states.get(charger_id) != state_val:
                    reasons.append(f"ev_surplus[{charger_id}] -> {state_val}")
            for charger_id in self._last_logged_surplus_states:
                if charger_id not in current_surplus_states:
                    reasons.append(f"ev_surplus[{charger_id}] -> inactive")

        slot_minute = (now.minute // 15) * 15
        slot_bucket = now.replace(minute=slot_minute, second=0, microsecond=0).isoformat()
        heartbeat_due = slot_bucket != self._last_heartbeat_slot_bucket

        should_log = bool(reasons) or heartbeat_due
        if not reasons and heartbeat_due:
            reasons.append("heartbeat")

        if should_log:
            self._last_logged_mode_intent = decision.mode_intent
            self._last_logged_override_type = current_override_type
            self._last_logged_balancer_state = balancer_status.state
            self._last_logged_surplus_states = current_surplus_states
            self._last_heartbeat_slot_bucket = slot_bucket

        return should_log, reasons

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
        error_message: str | None = None
        if not success:
            failed = [r for r in action_results if not r.success and not r.skipped]
            if failed:
                error_message = "; ".join(f"{r.action_type}: {r.message}" for r in failed)[:500]

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
            error_message=error_message,
            duration_ms=duration_ms,
            source="native",
            executor_version=EXECUTOR_VERSION,
        )

    def _resolve_active_phase_count(
        self,
        charger_cfg: EVChargerDeviceConfig,
        dev_state: EVChargerState,
        phase_ctrl: PhaseModeController,
    ) -> int:
        """kW<->A conversions use the commanded phase count, falling back to the
        configured `phases` count; once the charger's measured per-phase draw
        shows fewer active phases than commanded, use the measured count
        (task 3.6) — a car that only ever draws 1-phase makes 3-phase mode
        pointless, and measurement catches that.
        """
        if charger_cfg.phase_switching_enabled and phase_ctrl.commanded_mode is not None:
            commanded_count = phase_ctrl.commanded_mode
        else:
            commanded_count = len(charger_cfg.phases or [1, 2, 3]) or 1
        measured_count = len(dev_state.active_phases) if dev_state.active_phases else None
        if measured_count is not None and measured_count < commanded_count:
            return measured_count
        return commanded_count

    async def _apply_phase_mode_decision(
        self,
        charger_cfg: EVChargerDeviceConfig,
        phase_ctrl: PhaseModeController,
        target_power_kw: float,
        now: datetime,
    ) -> ActionResult | None:
        """Run the phase-mode state machine for one charger and dispatch a
        switch if warranted (design D5, task 3.5). Returns the write's
        ActionResult when a switch was attempted, else None.
        """
        entity = charger_cfg.phase_mode_entity
        if not charger_cfg.phase_switching_enabled or not entity or not self.dispatcher:
            return None

        if phase_ctrl.failed and self.ha_client:
            # Fail-safe recovery check: only re-arm once the entity reads back
            # as available again — never blindly retry every tick.
            current_val = await self.ha_client.get_state_value(entity)
            if current_val is None or current_val in ("unknown", "unavailable"):
                return None
            phase_ctrl.on_entity_recovered()

        # load-balancer-graceful-degradation D4: while 1-phase is held for
        # overload relief, 3-phase must fit the averaged target margin too.
        three_phase_fits = True
        if phase_ctrl.relief_hold:
            dev_state = self._ev_charger_states.get(charger_cfg.id)
            three_phase_fits = self._load_balancer.three_phase_fits(
                charger_cfg.phases or [1, 2, 3],
                [charger_cfg.phase_1_line],
                float((dev_state.current_setpoint_a if dev_state else None) or 0),
                charger_cfg.min_current_a,
                now,
            )
        decision = phase_ctrl.decide(
            now=now,
            target_power_kw=target_power_kw,
            three_phase_min_kw_value=three_phase_min_kw(
                charger_cfg.min_current_a, self.config.ev_nominal_voltage_v
            ),
            hysteresis_kw=charger_cfg.phase_switch_hysteresis_kw,
            min_dwell_s=charger_cfg.phase_switch_min_dwell_s,
            enabled=True,
            entity_configured=True,
            is_binary=False,
            three_phase_fits=three_phase_fits,
        )
        if not decision.should_switch or decision.commanded_mode is None:
            return None
        return await self._write_phase_mode(charger_cfg, phase_ctrl, decision.commanded_mode, now)

    async def _write_phase_mode(
        self,
        charger_cfg: EVChargerDeviceConfig,
        phase_ctrl: PhaseModeController,
        mode: int,
        now: datetime,
        relief: bool = False,
    ) -> ActionResult:
        """Write a commanded phase mode and update the controller (the single
        owner of the contactor, its dwell and its fail-safe latch)."""
        assert self.dispatcher is not None
        entity = charger_cfg.phase_mode_entity
        assert entity

        phase_option = charger_cfg.phase_1_value if mode == 1 else charger_cfg.phase_3_value
        result = await self.dispatcher.set_ev_phase_mode(entity, mode, phase_option)
        self._log_ev_action(charger_cfg.id, result, "ev_phase_mode", now)
        if result.success:
            phase_ctrl.on_switch_success(mode, now, relief=relief)
        else:
            phase_ctrl.on_entity_unavailable()
            logger.warning(
                "EV charger %s: phase-mode write failed (%s) — disabling further "
                "switch attempts until the entity recovers",
                charger_cfg.id,
                result.error_details or result.message,
            )
        return result

    async def _update_ev_surplus_and_phase_mode(
        self, state: SystemState, slot: "SlotPlan | None", now: datetime
    ) -> list[ActionResult]:
        """Surplus feedback + phase-mode state machines for every type="current"
        EV charger (excess-pv-priority-dispatch 3.2/3.3/3.5).

        Populates self._ev_surplus_targets for surplus-eligible chargers this
        tick; _run_load_balancer consumes it in place of the plan-derived
        target. Returns ActionResults for any phase-mode writes attempted
        (folded into the tick's action_results so switches always surface in
        the execution log, never silently throttled away — task 3.8).
        """
        self._ev_surplus_targets = {}
        self._ev_surplus_status = {}
        action_results: list[ActionResult] = []
        if not self.config.ev_chargers:
            return action_results

        surplus_kw = state.current_export_kw - state.current_import_kw
        self._last_measured_surplus_kw = surplus_kw
        ev_entries_by_charger = {
            entry.charger_id: entry
            for entry in self.config.excess_pv.priority
            if entry.type == "ev" and entry.charger_id
        }

        for charger_cfg in self.config.ev_chargers:
            if charger_cfg.type != "current":
                continue
            charger_id = charger_cfg.id
            dev_state = self._ev_charger_states.setdefault(charger_id, EVChargerState())
            phase_ctrl = self._ev_phase_controllers.setdefault(charger_id, PhaseModeController())
            await self._update_ev_measured_draw(charger_cfg, dev_state, phase_ctrl)

            # ev-manual-charge: excluded from surplus targeting (which could
            # only lower the requested current) while a manual charge runs.
            manual_target_a = self._ev_manual_target_a(charger_cfg)
            surplus_entry = ev_entries_by_charger.get(charger_id)
            surplus_eligible = bool(
                manual_target_a is None
                and surplus_entry
                and slot
                and slot.ev_surplus_kw.get(charger_id, 0.0) > 0
            )

            charger_plan_kw = slot.ev_charger_plans.get(charger_id, 0.0) if slot else 0.0
            keep_on_only = (
                manual_target_a is None
                and not surplus_eligible
                and charger_plan_kw <= 0.1
                and self._charger_should_be_on(slot, charger_id)
            )
            if manual_target_a is not None:
                target_power_kw = (
                    manual_target_a
                    * self.config.ev_nominal_voltage_v
                    * len(charger_cfg.phases or [1, 2, 3])
                    / 1000.0
                )
            elif surplus_eligible:
                target_power_kw = surplus_kw
            elif keep_on_only:
                # Keep-on-only: no planned energy, target the smallest
                # representable "on" state (1-phase minimum current) for
                # phase-mode selection (D3) rather than 0, which would read
                # as "should be off".
                target_power_kw = one_phase_min_kw(
                    charger_cfg.min_current_a, self.config.ev_nominal_voltage_v
                )
            else:
                target_power_kw = charger_plan_kw

            phase_result = await self._apply_phase_mode_decision(
                charger_cfg, phase_ctrl, target_power_kw, now
            )
            if phase_result is not None:
                action_results.append(phase_result)
                self._log_ev_transition(
                    charger_id,
                    "phase_mode",
                    f"{phase_ctrl.commanded_mode}-phase"
                    if phase_result.success
                    else "write_failed",
                )

            if not surplus_eligible:
                self._log_ev_transition(charger_id, "surplus", "inactive")
                continue

            assert surplus_entry is not None
            active_phase_count = self._resolve_active_phase_count(
                charger_cfg, dev_state, phase_ctrl
            )
            phase_switch_can_lower_floor = (
                charger_cfg.phase_switching_enabled
                and bool(charger_cfg.phase_mode_entity)
                and not phase_ctrl.failed
                and phase_ctrl.commanded_mode != 1
            )

            surplus_ctrl = self._ev_surplus_controllers.setdefault(
                charger_id, EVSurplusController()
            )
            max_current_a = charger_cfg.max_current_a or charger_cfg.min_current_a
            result = surplus_ctrl.tick(
                now=now,
                surplus_kw=surplus_kw,
                deadband_kw=surplus_entry.surplus_deadband_kw,
                current_setpoint_a=dev_state.current_setpoint_a,
                baseline_a=self._effective_baseline_a(charger_cfg, dev_state, now),
                min_current_a=charger_cfg.min_current_a,
                max_current_a=max_current_a,
                active_phase_count=active_phase_count,
                increase_step_a=self.config.load_balancing.increase_step_a,
                resume_delay_s=self.config.load_balancing.resume_delay_s,
                resume_margin_percent=self.config.load_balancing.target_margin_percent,
                phase_switch_can_lower_floor=phase_switch_can_lower_floor,
                voltage_v=self.config.ev_nominal_voltage_v,
            )
            self._ev_surplus_targets[charger_id] = result.target_a
            self._ev_surplus_status[charger_id] = {"state": result.state, "reason": result.reason}
            self._log_ev_transition(charger_id, "surplus", result.state, result.reason)

        return action_results

    def _log_ev_transition(
        self, charger_id: str, kind: str, new_state: str, reason: str = ""
    ) -> None:
        """Log surplus-mode/phase-mode state transitions once, on change only
        (task 3.8) — mirrors the always-log-transitions shape used by
        universal-load-balancing's intervention notifications.
        """
        tracker = self._last_surplus_state if kind == "surplus" else self._last_phase_mode
        key = f"{kind}:{charger_id}"
        if tracker.get(key) == new_state:
            return
        tracker[key] = new_state
        logger.info(
            "EV charger %s: %s -> %s%s",
            charger_id,
            kind,
            new_state,
            f" ({reason})" if reason else "",
        )

    def _run_load_balancer(
        self, state: SystemState, slot: "SlotPlan | None", now: datetime
    ) -> LoadBalancerStatus:
        """Build ordered balancer inputs from give_way_order and run one tick.

        Uses each EV's active_phases as measured as of the *start* of this
        tick (last tick's reading) rather than re-fetching from HA here, to
        avoid a duplicate sensor read — _control_ev_charger refreshes it a
        moment later before actuation.
        """
        lb_cfg = self.config.load_balancing
        # Idempotent runtime self-heal: guarantees every current-type charger
        # and every loads[] entry has a position even if the config object was
        # built without give_way_order (tests, partial reloads).
        heal_give_way_order(lb_cfg, [c.id for c in self.config.ev_chargers if c.type == "current"])

        ev_inputs_by_id: dict[str, EVBalancerInput] = {}
        for charger_cfg in self.config.ev_chargers:
            if charger_cfg.type != "current":
                continue

            charger_id = charger_cfg.id
            dev_state = self._ev_charger_states.get(charger_id)
            phase_ctrl = self._ev_phase_controllers.get(charger_id)
            phases = self._balancer_phases(charger_cfg, dev_state, phase_ctrl, now)
            max_current_a = charger_cfg.max_current_a or charger_cfg.min_current_a

            manual_target_a = self._ev_manual_target_a(charger_cfg)
            if manual_target_a is not None:
                # ev-manual-charge: the user's requested current (default
                # max_current_a); the balancer below still clamps it.
                planner_target_a = manual_target_a
            elif charger_id in self._ev_surplus_targets:
                # excess-pv-priority-dispatch 3.3: surplus-eligible this slot —
                # use the feedback controller's proposed amps (already
                # deadband/ramp/pause-aware) instead of the plan-derived target,
                # so the fuse balancer clamps the *surplus* proposal.
                planner_target_a = self._ev_surplus_targets[charger_id]
            else:
                charger_plan_kw = slot.ev_charger_plans.get(charger_id, 0.0) if slot else 0.0
                should_charge = self._charger_should_be_on(slot, charger_id)
                if charger_plan_kw > 0.1:
                    planner_target_a = planned_kw_to_amps(
                        charger_plan_kw,
                        len(phases),
                        charger_cfg.min_current_a,
                        max_current_a,
                        self.config.ev_nominal_voltage_v,
                    )
                elif should_charge:
                    # Keep-on-only: no planned energy, hold the relay closed at
                    # the charger's configured minimum current (D3) rather than
                    # a computed target — the balancer may still shed it.
                    planner_target_a = charger_cfg.min_current_a
                else:
                    planner_target_a = None
            ev_inputs_by_id[charger_id] = EVBalancerInput(
                charger_id=charger_id,
                phases=phases,
                current_setpoint_a=dev_state.current_setpoint_a if dev_state else None,
                planner_target_a=planner_target_a,
                min_current_a=charger_cfg.min_current_a,
                max_current_a=max_current_a,
                effective_draw_a=(
                    self._effective_baseline_a(charger_cfg, dev_state, now) if dev_state else None
                ),
                phase_1_line=charger_cfg.phase_1_line,
                relief_available=bool(
                    charger_cfg.phase_switching_enabled
                    and charger_cfg.phase_mode_entity
                    and self.dispatcher is not None
                    and charger_cfg.phase_1_line in (charger_cfg.phases or [1, 2, 3])
                    and (phase_ctrl or PhaseModeController()).relief_available(
                        now, charger_cfg.phase_switch_min_dwell_s
                    )
                ),
            )

        shed_inputs_by_id = {
            ld.device_id: ShedLoadInput(
                load_id=ld.device_id,
                device_type=ld.device_type.value,
                phases=ld.phases,
            )
            for ld in lb_cfg.loads
        }

        entries: list[EVBalancerInput | ShedLoadInput] = []
        for order_entry in lb_cfg.give_way_order:
            if order_entry.kind == "charger" and order_entry.id in ev_inputs_by_id:
                entries.append(ev_inputs_by_id[order_entry.id])
            elif order_entry.kind == "shed" and order_entry.id in shed_inputs_by_id:
                entries.append(shed_inputs_by_id[order_entry.id])

        # Stashed for the status surface (6.1): planned target per charger,
        # to report "setpoint vs planned target" alongside the final decision.
        self._last_balancer_planned_targets = {
            ev.charger_id: ev.planner_target_a for ev in ev_inputs_by_id.values()
        }

        return self._load_balancer.tick(
            now,
            state.grid_current_a,
            state.grid_current_updated_at,
            entries,
        )

    @staticmethod
    def _balancer_phases(
        charger_cfg: EVChargerDeviceConfig,
        dev_state: EVChargerState | None,
        phase_ctrl: PhaseModeController | None,
        now: datetime,
    ) -> list[int]:
        """Phases the balancer attributes a charger's draw to.

        Measured active phases win (ev-measured-draw). Otherwise a charger
        commanded to 1-phase draws on its phase_1_line only, else on its
        configured phases. For PHASE_SWITCH_SETTLE_S after a commanded switch
        the measurement may still describe the old mode, so the union of both
        is used — more phases is always the protective attribution.
        """
        configured = list(charger_cfg.phases or [1, 2, 3])
        commanded = configured
        if (
            charger_cfg.phase_switching_enabled
            and phase_ctrl is not None
            and phase_ctrl.commanded_mode == 1
        ):
            commanded = [charger_cfg.phase_1_line]
        measured = list(dev_state.active_phases) if dev_state and dev_state.active_phases else None
        if measured is None:
            return commanded
        if (
            phase_ctrl is not None
            and phase_ctrl.last_switch_time is not None
            and (now - phase_ctrl.last_switch_time).total_seconds() < PHASE_SWITCH_SETTLE_S
        ):
            return sorted(set(measured) | set(commanded))
        return measured

    async def _apply_balancer_relief(
        self, status: LoadBalancerStatus, now: datetime, writes_allowed: bool = True
    ) -> list[ActionResult]:
        """Degradation-ladder step 2 (load-balancer-graceful-degradation D4/D5):
        command 1-phase for chargers the balancer asked to relieve, after the
        balancer and before the setpoint write. The controller still enforces
        dwell and its fail-safe; a refused or failed switch leaves the charger
        at its floor this tick and the balancer pauses it on the next.
        Relief switches never notify.

        A quick re-fit from a pause into 1-phase (D17, refit_from_pause) is
        only safe once the switch is applied: when it is refused or fails,
        the charger's output is replaced with a pause so it never starts on
        the phases that did not fit. With writes_allowed=False (manual
        override) nothing is written and every such re-fit is aborted.
        """
        results: list[ActionResult] = []
        if not status.enabled:
            return results
        cfg_by_id = {c.id: c for c in self.config.ev_chargers}
        for idx, out in enumerate(status.ev_outputs):
            if not out.relief_1p_requested:
                continue
            applied = False
            charger_cfg = cfg_by_id.get(out.charger_id)
            if (
                writes_allowed
                and charger_cfg is not None
                and charger_cfg.phase_mode_entity
                and self.dispatcher
            ):
                phase_ctrl = self._ev_phase_controllers.setdefault(
                    out.charger_id, PhaseModeController()
                )
                decision = phase_ctrl.decide_relief(
                    now=now,
                    min_dwell_s=charger_cfg.phase_switch_min_dwell_s,
                    enabled=charger_cfg.phase_switching_enabled,
                    entity_configured=True,
                    is_binary=charger_cfg.type != "current",
                )
                if not decision.should_switch:
                    logger.info(
                        "EV charger %s: 1-phase relief not applied (%s)",
                        out.charger_id,
                        decision.reason,
                    )
                else:
                    result = await self._write_phase_mode(
                        charger_cfg, phase_ctrl, 1, now, relief=True
                    )
                    results.append(result)
                    applied = result.success
                    if result.success:
                        self._ev_relief_reason[out.charger_id] = out.reason
                    self._log_ev_transition(
                        out.charger_id,
                        "phase_mode",
                        "1-phase (relief)" if result.success else "write_failed",
                        out.reason,
                    )
            if not applied and out.refit_from_pause:
                self._load_balancer.abort_refit(out.charger_id, now)
                status.ev_outputs[idx] = EVBalancerOutput(
                    out.charger_id,
                    None,
                    "paused",
                    "Waiting to resume — the 1-phase switch could not be applied",
                )
                status.state = "paused"
        return results

    def _track_balancer_throttling(self, status: LoadBalancerStatus, now: datetime) -> None:
        """Sustained-throttle early replan (load-balancing-completion 4.1/4.2).

        Tracks, per charger, the continuous duration the balancer holds the
        setpoint below the planner target (or paused) while the slot plans
        charging. Planner-intended low targets never count: the comparison is
        against the planner-derived target itself. Fires one replan when the
        duration exceeds replan_after_throttled_s, rate-limited to one
        balancer-triggered replan per planner interval.
        """
        if not status.enabled:
            self._balancer_throttled_since.clear()
            return

        threshold = self.config.load_balancing.replan_after_throttled_s
        for out in status.ev_outputs:
            planner_target = self._last_balancer_planned_targets.get(out.charger_id)
            if planner_target is None:
                # Slot doesn't plan charging for this charger — reset.
                self._balancer_throttled_since.pop(out.charger_id, None)
                continue
            constrained = out.target_a is None or out.target_a < planner_target
            if not constrained:
                # Target reached — reset.
                self._balancer_throttled_since.pop(out.charger_id, None)
                continue
            since = self._balancer_throttled_since.setdefault(out.charger_id, now)
            if (now - since).total_seconds() >= threshold:
                self._maybe_fire_balancer_replan(out.charger_id, now)

    def _maybe_fire_balancer_replan(self, charger_id: str, now: datetime) -> None:
        """Fire one balancer-triggered replan, at most one per planner interval."""
        if not self._executor_replan_allowed(now):
            return  # rate limit: keep the tracker running, retry when rearmed

        self._balancer_throttled_since.pop(charger_id, None)  # reset on fire
        logger.info(
            "Load balancer has constrained charger '%s' for over %ss — requesting one early replan",
            charger_id,
            self.config.load_balancing.replan_after_throttled_s,
        )
        self._request_balancer_replan()

    def _executor_replan_allowed(self, now: datetime) -> bool:
        """Rate limit for balancer-triggered replans: at most one per planner
        interval. Consumes the slot when it returns True."""
        automation_raw: Any = self._full_config.get("automation", {})
        automation_cfg: dict[str, Any] = (
            cast("dict[str, Any]", automation_raw) if isinstance(automation_raw, dict) else {}
        )
        schedule_raw: Any = automation_cfg.get("schedule", {})
        schedule_cfg: dict[str, Any] = (
            cast("dict[str, Any]", schedule_raw) if isinstance(schedule_raw, dict) else {}
        )
        try:
            interval_minutes = int(schedule_cfg.get("every_minutes", 60))
        except (TypeError, ValueError):
            interval_minutes = 60

        last = self._last_balancer_replan_at
        if last is not None and (now - last).total_seconds() < interval_minutes * 60:
            return False

        self._last_balancer_replan_at = now
        return True

    def _request_balancer_replan(self) -> None:
        """Request a planner run via the shared replan dispatch helper."""
        try:
            from backend.services.scheduler_service import ReplanReason, request_replan

            request_replan(ReplanReason.LOAD_BALANCER)
        except Exception as e:
            logger.error("Failed to request balancer-triggered replan: %s", e)

    async def _notify_balancer_interventions(
        self,
        status: LoadBalancerStatus,
        slot: "SlotPlan | None" = None,
        now: datetime | None = None,
    ) -> None:
        """Intervention notifications (load-balancing-completion 5.1,
        load-balancer-graceful-degradation D7).

        Notifies once per qualifying transition — a load is shed or the
        stale-sensor fail-safe engages — with the same human-readable reason
        as the execution log. A charger pause notifies only when it puts an
        active EV goal at risk; other pauses are in the execution log only.
        Routine throttle/ramp adjustments and 1-phase relief switches never
        notify. State maps update even while the toggle is off, so enabling
        it later doesn't fire for pre-existing states.
        """
        if not status.enabled:
            self._notified_ev_states.clear()
            self._notified_shed_states.clear()
            return

        dispatcher = self.dispatcher if self.config.load_balancing.notify_interventions else None
        charger_names = {ev.id: (ev.name or ev.id) for ev in self.config.ev_chargers}

        for out in status.ev_outputs:
            prev = self._notified_ev_states.get(out.charger_id)
            if (
                out.state in ("paused", "stale_fallback")
                and out.state != prev
                and dispatcher is not None
            ):
                name = charger_names.get(out.charger_id, out.charger_id)
                if out.state == "paused":
                    at_risk, why = self._pause_goal_risk(out.charger_id, slot, now)
                    if at_risk:
                        await dispatcher.notify_balancer_intervention(
                            f"{name}: charging paused, goal at risk ({why}) — {out.reason}"
                        )
                    else:
                        logger.info(
                            "EV charger %s paused by the load balancer, not notifying (%s): %s",
                            out.charger_id,
                            why,
                            out.reason,
                        )
                else:
                    await dispatcher.notify_balancer_intervention(
                        f"{name}: stale-sensor fail-safe engaged — {out.reason}"
                    )
            self._notified_ev_states[out.charger_id] = out.state

        for shed_out in status.shed_outputs:
            prev_shed = self._notified_shed_states.get(shed_out.load_id, False)
            if shed_out.shed and not prev_shed and dispatcher is not None:
                await dispatcher.notify_balancer_intervention(
                    f"Load '{shed_out.load_id}' switched off — {shed_out.reason}"
                )
            self._notified_shed_states[shed_out.load_id] = shed_out.shed

    def _pause_goal_risk(
        self, charger_id: str, slot: "SlotPlan | None", now: datetime | None
    ) -> tuple[bool, str]:
        """Whether a balancer pause puts the charger's active goal at risk.
        Any failure to evaluate fails open (at risk)."""
        try:
            from backend.core.ev_state import read_ev_state

            goal = read_ev_state().get(charger_id)
            diagnostics_all: Any = self._last_schedule_meta.get("ev_goal_diagnostics") or {}
            diagnostics_raw: Any = (
                cast("dict[str, Any]", diagnostics_all).get(charger_id)
                if isinstance(diagnostics_all, dict)
                else None
            )
            planned_kw = slot.ev_charger_plans.get(charger_id, 0.0) if slot else 0.0
            return pause_puts_goal_at_risk(
                goal,
                cast("dict[str, Any]", diagnostics_raw)
                if isinstance(diagnostics_raw, dict)
                else None,
                planned_kw,
                now or datetime.now(UTC),
            )
        except Exception as e:
            logger.warning("Could not evaluate EV goal risk for %s: %s", charger_id, e)
            return True, "goal status unknown"

    def get_load_balancer_status(self) -> dict[str, Any]:
        """Serialize the latest balancer tick for the status surface (6.1/6.2),
        plus per-charger EV-surplus/phase-mode fields (excess-pv-priority-
        dispatch 4.1) — additive fields only. Surplus/phase-mode status must
        surface even when the fuse balancer itself is disabled/unconfigured,
        so the charger list is the union of chargers with a balancer decision
        this tick and chargers with surplus/phase-mode state this tick.
        """
        status = self._last_balancer_status
        charger_names = {ev.id: (ev.name or ev.id) for ev in self.config.ev_chargers}
        cfg_by_id = {ev.id: ev for ev in self.config.ev_chargers}
        planned = getattr(self, "_last_balancer_planned_targets", {})
        balancer_outputs_by_id = {o.charger_id: o for o in status.ev_outputs} if status else {}

        charger_ids: list[str] = list(balancer_outputs_by_id.keys())
        for charger_id in {**self._ev_surplus_status, **self._ev_phase_controllers}:
            if charger_id not in charger_ids:
                charger_ids.append(charger_id)

        ev_list: list[dict[str, Any]] = []
        for charger_id in charger_ids:
            balancer_out = balancer_outputs_by_id.get(charger_id)
            dev_state = self._ev_charger_states.get(charger_id)
            surplus_info = self._ev_surplus_status.get(charger_id)
            phase_ctrl = self._ev_phase_controllers.get(charger_id)
            # load-balancer-graceful-degradation 6.4: 1-phase held (or being
            # requested this tick) to relieve an overloaded phase.
            relief_requested = balancer_out is not None and balancer_out.relief_1p_requested
            relief_held = (
                phase_ctrl is not None and phase_ctrl.relief_hold and phase_ctrl.commanded_mode == 1
            )
            relief_active = relief_requested or relief_held
            relief_reason: str | None = None
            if relief_requested and balancer_out is not None:
                relief_reason = balancer_out.reason
            elif relief_held:
                relief_reason = self._ev_relief_reason.get(charger_id)
            ev_list.append(
                {
                    "charger_id": charger_id,
                    "charger_name": charger_names.get(charger_id, charger_id),
                    "setpoint_a": (
                        balancer_out.target_a
                        if balancer_out is not None
                        else (dev_state.current_setpoint_a if dev_state else None)
                    ),
                    "planned_target_a": planned.get(charger_id),
                    # ev-measured-draw: amps per phase the car actually draws
                    "measured_a": (
                        round(dev_state.measured_draw_a, 1)
                        if dev_state and dev_state.measured_draw_a is not None
                        else None
                    ),
                    "state": balancer_out.state if balancer_out is not None else "idle",
                    "reason": balancer_out.reason if balancer_out is not None else "",
                    # excess-pv-priority-dispatch 4.1: additive surplus-mode fields
                    "surplus_mode": surplus_info is not None,
                    "surplus_state": surplus_info["state"] if surplus_info else None,
                    "surplus_reason": surplus_info["reason"] if surplus_info else None,
                    "phase_mode": phase_ctrl.commanded_mode if phase_ctrl else None,
                    # load-balancer-graceful-degradation 6.4: 1-phase held (or
                    # being requested this tick) to relieve an overloaded phase.
                    "relief_1p": relief_active,
                    "relief_reason": relief_reason,
                    "phase_1_line": (
                        cfg_by_id[charger_id].phase_1_line if charger_id in cfg_by_id else None
                    ),
                    "paused": bool(surplus_info and surplus_info["state"] == "paused"),
                }
            )

        if status is None or not status.enabled:
            return {
                "enabled": False,
                "state": "disabled",
                "reason": status.reason if status else "Load balancing disabled or unconfigured",
                "main_fuse_a": status.main_fuse_a if status else None,
                "target_margin_percent": self.config.load_balancing.target_margin_percent,
                "tick_interval_s": self.config.interval_seconds,
                "phase_current_a": {},
                "phase_headroom_a": {},
                "measured_surplus_kw": self._last_measured_surplus_kw,
                "ev": ev_list,
                "shed": [],
            }

        return {
            "enabled": True,
            "state": status.state,
            "reason": status.reason,
            "main_fuse_a": status.main_fuse_a,
            "target_margin_percent": self.config.load_balancing.target_margin_percent,
            "tick_interval_s": self.config.interval_seconds,
            "phase_current_a": status.phase_current_a,
            "phase_headroom_a": status.phase_headroom_a,
            "measured_surplus_kw": self._last_measured_surplus_kw,
            "ev": ev_list,
            "shed": [
                {
                    "load_id": o.load_id,
                    "device_type": o.device_type,
                    "shed": o.shed,
                    "reason": o.reason,
                }
                for o in status.shed_outputs
            ],
        }

    async def _check_ev_charge_failure(
        self,
        commanded_active: bool,
        actual_ev_power_kw: float,
        now: datetime | None = None,
    ) -> bool:
        """EV charge failure detection based on the commanded level (5.1).

        Counts consecutive ticks where at least one charger is commanded to
        charge (switch ON, or an ampere setpoint at/above its floor — after
        any balancer capping/pausing) but actual EV power stays below 0.1kW.
        Balancer-initiated pause/throttle never increments the counter because
        it also un-commands the charger (commanded_active becomes False).

        Returns True the tick the failure notification fires (once per
        commanded session).

        The first failure in a commanded period, and the first tick with
        actual power above 0.1kW after it, each request a replan so the
        remaining time is re-planned. Both use their own short cooldown
        (EV_FAILURE_REPLAN_COOLDOWN_S), independent of the balancer replan
        rate limit; at most one failure and one recovery replan fire per
        commanded period anyway. A recovery inside the cooldown stays pending
        and fires on the first charging tick after the cooldown ends.
        """
        if not commanded_active:
            self._ev_zero_power_ticks = 0
            self._ev_failure_notified = False
            self._ev_failure_recovery_pending = False
            return False

        if now is None:
            now = datetime.now(pytz.timezone(self.config.timezone))

        if actual_ev_power_kw < 0.1 and not self._ev_power_fetch_failed:
            self._ev_zero_power_ticks += 1
        else:
            self._ev_zero_power_ticks = 0
            # Stays pending until the replan actually fires, so a recovery
            # inside the cooldown is retried on a later tick, not dropped.
            if (
                self._ev_failure_recovery_pending
                and actual_ev_power_kw >= 0.1
                and self._request_ev_failure_replan(
                    now, f"EV charging resumed ({actual_ev_power_kw:.2f}kW) after a failure"
                )
            ):
                self._ev_failure_recovery_pending = False

        if self._ev_zero_power_ticks >= 5 and not self._ev_failure_notified:
            error_msg = (
                "EV charge failure: charger(s) commanded to charge but "
                f"{actual_ev_power_kw:.2f}kW actual for "
                f"{self._ev_zero_power_ticks} consecutive ticks"
            )
            logger.warning(error_msg)
            if self.dispatcher:
                await self.dispatcher.notify_error(error_msg)
            self._ev_failure_notified = True
            self._ev_failure_recovery_pending = True
            self._request_ev_failure_replan(now, "EV charge failure detected")
            return True

        return False

    def _request_ev_failure_replan(self, now: datetime, reason: str) -> bool:
        """Request a replan for an EV charge failure/recovery, unless one was
        requested within EV_FAILURE_REPLAN_COOLDOWN_S. Returns True if requested."""
        last = self._last_ev_failure_replan_at
        if last is not None and (now - last).total_seconds() < EV_FAILURE_REPLAN_COOLDOWN_S:
            logger.debug("%s — replan deferred (failure replan cooldown)", reason)
            return False
        self._last_ev_failure_replan_at = now
        logger.info("%s — requesting replan of the remaining charging time", reason)
        self._request_balancer_replan()
        return True

    @staticmethod
    def _build_ev_reason_note(
        isolating: bool,
        ev_charging_kw: float,
        actual_ev_power_kw: float,
        keep_on_charger_ids: list[str],
    ) -> str | None:
        """Build the tick's EV-related reason/log text (task 2.9).

        ``isolating`` selects the source-isolation framing (battery discharge
        being blocked); the keep-on marker is appended/returned regardless of
        that, so battery-less systems (where isolation never triggers) still
        surface which charger(s) are held on solely via the flag. Single
        implementation shared by both branches so the two texts can't diverge.
        """
        if isolating:
            reason = (
                f"EV source isolation: {ev_charging_kw:.1f}kW scheduled, "
                f"{actual_ev_power_kw:.2f}kW actual"
            )
            if keep_on_charger_ids:
                reason += f" | {EV_KEEP_ON_REASON_MARKER}: {', '.join(keep_on_charger_ids)}"
            return reason
        if keep_on_charger_ids:
            return f"{EV_KEEP_ON_REASON_MARKER}: {', '.join(keep_on_charger_ids)}"
        return None

    def _first_planned_ev_starts(self, now: datetime) -> dict[str, datetime]:
        """Start of each charger's first current-or-upcoming slot with planned kW > 0.1.

        Read from schedule.json (the plan the executor follows). A slot already
        in progress counts, so a car still away at the start is reminded.
        """
        try:
            with Path(self.config.schedule_path).open(encoding="utf-8") as f:
                payload: Any = json.load(f)
        except (OSError, ValueError):
            return {}
        schedule_raw: Any = (
            cast("dict[str, Any]", payload).get("schedule", []) if isinstance(payload, dict) else []
        )
        if not isinstance(schedule_raw, list):
            return {}
        tz = pytz.timezone(self.config.timezone)
        starts: dict[str, datetime] = {}
        for item in cast("list[Any]", schedule_raw):
            if not isinstance(item, dict):
                continue
            slot_data = cast("dict[str, Any]", item)
            start_str = slot_data.get("start_time")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            except ValueError:
                continue
            start = tz.localize(start) if start.tzinfo is None else start.astimezone(tz)
            end = start + timedelta(minutes=15)
            end_str = slot_data.get("end_time_kepler") or slot_data.get("end_time")
            if end_str:
                try:
                    parsed_end = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
                    parsed_end = (
                        tz.localize(parsed_end)
                        if parsed_end.tzinfo is None
                        else parsed_end.astimezone(tz)
                    )
                    if parsed_end > start:
                        end = parsed_end
                except ValueError:
                    pass
            if end <= now:
                continue
            plan = self._parse_slot_plan(slot_data)
            for charger_id, kw in plan.ev_charger_plans.items():
                if kw > 0.1 and charger_id not in starts:
                    starts[charger_id] = start
        return starts

    async def _check_plug_in_reminders(
        self, now: datetime, plug_states: dict[str, EVPlugState]
    ) -> None:
        """Notify once per charging window when charging is planned soon but the
        car is not plugged in (ev-plug-in-reminder). Plugging in resets it."""
        notif = self.config.notifications
        if not notif.on_ev_plug_in_reminder or not self.dispatcher:
            return
        lead = timedelta(minutes=int(notif.ev_plug_in_reminder_minutes))
        starts: dict[str, datetime] | None = None
        for charger in self.config.ev_chargers:
            plug = plug_states.get(charger.id, "unknown")
            if plug == "plugged":
                self._plug_in_reminder_sent.pop(charger.id, None)
                continue
            if starts is None:
                starts = self._first_planned_ev_starts(now)
            start = starts.get(charger.id)
            if start is None:
                continue
            if now < start - lead or self._plug_in_reminder_sent.get(charger.id) == start:
                continue
            self._plug_in_reminder_sent[charger.id] = start
            message = (
                f"{charger.name or charger.id}: charging planned at {start.strftime('%H:%M')} "
                "but the car isn't plugged in"
            )
            logger.info("Plug-in reminder: %s", message)
            try:
                await self.dispatcher.notify_plug_in_reminder(message)
            except Exception as e:
                logger.warning("Failed to send plug-in reminder: %s", e)

    async def _check_ev_soc_stale(self) -> None:
        """Notify once per stale-SoC episode (ev-soc-staleness).

        Episodes are tracked by the shared SoC resolver: a plugged charger whose
        SoC sensor has had no valid reading for longer than its
        ``soc_stale_after_minutes`` (goal charging suspended). The episode, and
        with it the dedupe, ends on the next valid reading or unplug. Gated on
        ``notifications.on_ev_soc_stale``; planning is suspended regardless.

        When an episode ends with a valid reading (recovery), one immediate
        replan is requested so the suspended goal resumes without waiting for
        the next scheduled run.
        """
        self._request_soc_recovery_replan()
        episodes = stale_soc_episodes()
        self._soc_stale_notified &= set(episodes)
        if not episodes or not self.dispatcher:
            return
        names = {c.id: c.name or c.id for c in self.config.ev_chargers}
        for charger_id, age in episodes.items():
            if charger_id in self._soc_stale_notified or charger_id not in names:
                continue
            self._soc_stale_notified.add(charger_id)
            if not self.config.notifications.on_ev_soc_stale:
                continue
            since = f"for {age:.0f} min" if age is not None else "since startup"
            message = (
                f"{names[charger_id]}: SoC reading unavailable {since} - "
                "goal charging suspended until it returns"
            )
            logger.info("Stale SoC notification: %s", message)
            try:
                await self.dispatcher.notify_ev_soc_stale(message)
            except Exception as e:
                logger.warning("Failed to send stale-SoC notification: %s", e)

    def _request_soc_recovery_replan(self) -> None:
        """Replan once per stale-SoC episode that ended with a valid reading."""
        configured = {c.id for c in self.config.ev_chargers}
        recovered = sorted(consume_soc_recoveries() & configured)
        if not recovered:
            return
        logger.info("EV SoC reading recovered for %s - requesting replan", ", ".join(recovered))
        try:
            from backend.services.scheduler_service import ReplanReason, request_replan

            request_replan(ReplanReason.SOC_RECOVERED, charger_ids=recovered)
        except Exception as e:
            logger.error("Failed to request SoC-recovery replan: %s", e)

    async def _read_ev_plug_states(self) -> dict[str, EVPlugState]:
        """Live plug state per configured charger (shared ``read_ev_live_state``).

        A charger without a plug sensor reads as plugged (same assumption as the
        planner); an unreadable/unreachable plug reads as ``unknown``. Empty when
        there is no HA client (nothing can be switched then anyway).
        """
        states: dict[str, EVPlugState] = {}
        if not self.ha_client:
            return states
        for charger in self.config.ev_chargers:
            live = await read_ev_live_state(
                charger.id,
                self.ha_client.get_state_value,
                soc_sensor=None,
                plug_sensor=charger.plug_sensor,
                plugged_in_states=charger.plugged_in_states,
            )
            states[charger.id] = live.plug
        return states

    def _gate_ev_plan_on_plug_state(
        self, slot: SlotPlan, plug_states: dict[str, EVPlugState]
    ) -> SlotPlan:
        """Drop planned kW, keep-on and surplus flags of chargers not live-plugged.

        Unknown plug state counts as not plugged. Manual charge is handled
        separately (it checks the plug itself) and the measured-EV-draw
        fail-safe for source isolation is unaffected. Without an HA client the
        slot is returned unchanged.
        """
        if not self.ha_client:
            return slot
        charger_ids = set(slot.ev_charger_plans) | set(slot.ev_keep_on) | set(slot.ev_surplus_kw)
        blocked = {cid for cid in charger_ids if plug_states.get(cid, "unknown") != "plugged"}
        blocked_active = {
            cid
            for cid in blocked
            if slot.ev_charger_plans.get(cid, 0.0) > 0.1
            or slot.ev_keep_on.get(cid, False)
            or slot.ev_surplus_kw.get(cid, 0.0) > 0.01
        }
        if not blocked_active:
            return slot
        removed_kw = sum(slot.ev_charger_plans.get(cid, 0.0) for cid in blocked)
        logger.info(
            "EV plan not actionable for %s (charger not plugged in) - ignoring planned charging",
            ", ".join(sorted(blocked_active)),
        )
        return replace(
            slot,
            ev_charging_kw=max(0.0, slot.ev_charging_kw - removed_kw),
            ev_charger_plans={
                cid: (0.0 if cid in blocked else kw) for cid, kw in slot.ev_charger_plans.items()
            },
            ev_keep_on={
                cid: (False if cid in blocked else on) for cid, on in slot.ev_keep_on.items()
            },
            ev_surplus_kw={
                cid: (0.0 if cid in blocked else kw) for cid, kw in slot.ev_surplus_kw.items()
            },
        )

    def _charger_should_be_on(self, slot: "SlotPlan | None", charger_id: str) -> bool:
        """True when a charger has planned power, is held on via
        keep_on_after_target, or has an active manual charge.

        Single source of truth for "should this charger be on?" across the
        switch-close decision, load balancer, and surplus/phase-mode target —
        keep-on plans no energy but still needs the switch/relay closed.
        """
        if self._ev_manual_charge_active(charger_id):
            return True
        if slot is None:
            return False
        plan_kw = slot.ev_charger_plans.get(charger_id, 0.0)
        return plan_kw > 0.1 or slot.ev_keep_on.get(charger_id, False)

    async def _control_ev_charger(
        self,
        slot: "SlotPlan | None",
        now: datetime,
        force_stop: bool = False,
        balancer_ev_targets: dict[str, int | None] | None = None,
        shed_binary_charger_ids: set[str] | None = None,
    ) -> None:
        """
        Control all configured EV charger switches per-device.

        Each charger gets independent switch control based on its per-device
        plan from slot.ev_charger_plans; stopping follows directly from the plan.

        force_stop: when True, commands all chargers off regardless of the plan.
        balancer_ev_targets: when the load balancer is enabled, the final capped
            ampere setpoint per type="current" charger id (None = pause/stop).
            When None (balancer disabled/unconfigured), current-type chargers
            compute their target from the plan exactly as before (universal-
            load-balancing 4.7: zero behavior change while disabled).
        shed_binary_charger_ids: type="binary" chargers the balancer wants shed
            this tick (declared in load_balancing.loads), forced off regardless
            of the plan.
        """
        if not self.dispatcher or not self.ha_client:
            return

        for charger_cfg in self.config.ev_chargers:
            is_current_type = charger_cfg.type == "current"
            switch_entity = charger_cfg.switch_entity

            if is_current_type:
                if not charger_cfg.current_entity:
                    continue
            elif not switch_entity:
                continue

            charger_id = charger_cfg.id
            charger_plan_kw = slot.ev_charger_plans.get(charger_id, 0.0) if slot else 0.0
            should_charge = self._charger_should_be_on(slot, charger_id)

            # D2: force_stop quick action overrides the plan
            if force_stop:
                should_charge = False

            # Get or create per-device state
            if charger_id not in self._ev_charger_states:
                self._ev_charger_states[charger_id] = EVChargerState()
            dev_state = self._ev_charger_states[charger_id]

            if is_current_type:
                balancer_target = (
                    balancer_ev_targets.get(charger_id)
                    if balancer_ev_targets is not None and charger_id in balancer_ev_targets
                    else _NO_BALANCER_OVERRIDE
                )
                await self._control_ev_charger_current(
                    charger_cfg, dev_state, charger_plan_kw, should_charge, now, balancer_target
                )
                continue

            if shed_binary_charger_ids and charger_id in shed_binary_charger_ids:
                should_charge = False

            if not switch_entity:
                continue

            try:
                current_state = await self.ha_client.get_state_value(switch_entity)
                enabled_value, disabled_value = self._charger_switch_values(charger_cfg)
                is_currently_on = _values_equal(current_state, enabled_value)
                is_at_desired_state = _values_equal(
                    current_state, enabled_value if should_charge else disabled_value
                )

                desired_key = "on" if should_charge else "off"
                if self._ev_backoff_active(charger_id, desired_key, now):
                    continue

                if should_charge and not is_currently_on:
                    result = await self._set_charger_switch(
                        charger_cfg, turn_on=True, charging_kw=charger_plan_kw
                    )
                    self._log_ev_action(charger_id, result, "ev_charge_start", now)
                    self._ev_record_write_outcome(charger_id, desired_key, result, now)
                    if result.success:
                        dev_state.charging_active = True
                        dev_state.charging_slot_end = now + timedelta(minutes=15)

                elif not should_charge and not is_at_desired_state:
                    result = await self._set_charger_switch(charger_cfg, turn_on=False)
                    self._log_ev_action(charger_id, result, "ev_charge_stop", now)
                    self._ev_record_write_outcome(charger_id, desired_key, result, now)
                    if result.success:
                        dev_state.charging_active = False
                        dev_state.charging_slot_end = None

                elif should_charge and is_currently_on:
                    dev_state.charging_slot_end = now + timedelta(minutes=15)

            except Exception as e:
                logger.error("Failed to control EV charger %s: %s", charger_id, e)

    @staticmethod
    def _charger_switch_values(charger_cfg: EVChargerDeviceConfig) -> tuple[str, str]:
        """(enabled, disabled) values for a charger's `switch_entity`.

        Select-like entities use the configured option values; switch-like
        entities use on/off.
        """
        switch_entity = charger_cfg.switch_entity or ""
        domain = switch_entity.split(".", 1)[0] if "." in switch_entity else ""
        if domain in {"select", "input_select"}:
            return charger_cfg.charge_enabled_value, charger_cfg.charge_disabled_value
        return "on", "off"

    async def _set_charger_switch(
        self,
        charger_cfg: EVChargerDeviceConfig,
        turn_on: bool,
        charging_kw: float = 0.0,
    ) -> ActionResult:
        """Set a charger's `switch_entity` to its enabled/disabled value (idempotent)."""
        assert self.dispatcher is not None
        assert charger_cfg.switch_entity
        result = await self.dispatcher.set_ev_charger_switch(
            charger_cfg.switch_entity,
            turn_on=turn_on,
            charging_kw=charging_kw if turn_on else 0.0,
            enabled_value=charger_cfg.charge_enabled_value,
            disabled_value=charger_cfg.charge_disabled_value,
        )
        dev_state = self._ev_charger_states.get(charger_cfg.id)
        if dev_state is not None:
            unreachable = is_unreachable_state(getattr(result, "previous_value", None))
            if unreachable != dev_state.unreachable:
                if unreachable:
                    logger.warning(
                        "EV %s: charger unreachable (switch %s is %s)",
                        charger_cfg.id,
                        charger_cfg.switch_entity,
                        result.previous_value,
                    )
                else:
                    logger.info("EV %s: charger reachable again", charger_cfg.id)
            dev_state.unreachable = unreachable
        return result

    def _ev_backoff_active(self, charger_id: str, desired_key: str, now: datetime) -> bool:
        """True while a charger is in write-failure backoff for this desired state.

        A change of desired state (e.g. charge -> stop) clears the backoff so
        the new command is attempted immediately.
        """
        backoff = self._ev_write_backoff.get(charger_id)
        if backoff is None:
            return False
        if backoff.desired_key != desired_key:
            del self._ev_write_backoff[charger_id]
            return False
        return now < backoff.until

    def _ev_record_write_outcome(
        self, charger_id: str, desired_key: str, result: ActionResult, now: datetime
    ) -> None:
        """Reset the charger's backoff on success, or extend it on failure:
        min(60 s * 2^(n-1), 600 s) after the n-th consecutive failure."""
        if result.success:
            self._ev_write_backoff.pop(charger_id, None)
            return
        previous = self._ev_write_backoff.get(charger_id)
        failures = (
            previous.failures + 1
            if previous is not None and previous.desired_key == desired_key
            else 1
        )
        delay_s = min(EV_BACKOFF_BASE_S * 2 ** (failures - 1), EV_BACKOFF_MAX_S)
        self._ev_write_backoff[charger_id] = _EVWriteBackoff(
            desired_key=desired_key,
            failures=failures,
            until=now + timedelta(seconds=delay_s),
        )
        logger.warning(
            "EV charger %s: write failed (%d consecutive) — backing off for %ds",
            charger_id,
            failures,
            delay_s,
        )

    def _log_ev_action(
        self, charger_id: str, result: ActionResult, mode: str, now: datetime
    ) -> None:
        """Write an execution record for an EV dispatch result, success or failure.

        Results skipped because the entity was already at target (or shadow
        mode) are not recorded. An identical consecutive failure (same value
        and error) within EV_FAILURE_DEDUP_WINDOW is suppressed; the number of
        suppressed repeats is stated in the next record for that action.
        """
        if result.skipped:
            return

        key = (charger_id, mode)
        previous = self._ev_failure_dedup.get(key)
        error = result.error_details or ("" if result.success else result.message)
        signature = (str(result.new_value), error)

        if (
            not result.success
            and previous is not None
            and previous.signature == signature
            and now - previous.first_at < EV_FAILURE_DEDUP_WINDOW
        ):
            previous.suppressed += 1
            return

        repeat_count = previous.suppressed if previous is not None else 0
        if result.success:
            self._ev_failure_dedup.pop(key, None)
        else:
            self._ev_failure_dedup[key] = _EVFailureDedup(signature=signature, first_at=now)

        message = result.message
        if repeat_count:
            message = f"{message} (previous failure repeated {repeat_count} times)"

        self.history.log_execution(
            ExecutionRecord(
                executed_at=now.isoformat(),
                slot_start=now.isoformat(),
                commanded_work_mode=mode,
                before_soc_percent=0,
                success=1 if result.success else 0,
                error_message=None if result.success else (error or result.message),
                source="ev_charger",
                duration_ms=result.duration_ms,
                action_results=[
                    {
                        "type": result.action_type,
                        "success": result.success,
                        "message": message,
                        "entity_id": result.entity_id,
                        "charger_id": charger_id,
                        "previous_value": result.previous_value,
                        "new_value": result.new_value,
                        "verified_value": result.verified_value,
                        "verification_success": result.verification_success,
                        "skipped": result.skipped,
                        "error_details": result.error_details,
                        "repeat_count": repeat_count,
                    }
                ],
            )
        )

    async def _update_ev_measured_draw(
        self,
        charger_cfg: EVChargerDeviceConfig,
        dev_state: EVChargerState,
        phase_ctrl: PhaseModeController,
    ) -> None:
        """Derive the car's measured draw per phase (A) for this tick
        (ev-measured-draw), before surplus feedback and load balancing run.

        Source order: the charger's per-phase sensors (max across phases) →
        the charger's total power reading from the load disaggregator,
        divided by system.grid.nominal_voltage_v x active phase count → None. The per-phase read also
        refreshes dev_state.active_phases, so it happens once per tick.
        """
        phase_amps = await self._update_ev_active_phases(charger_cfg, dev_state)
        if phase_amps:
            dev_state.measured_draw_a = max(phase_amps)
            return

        dev_state.measured_draw_a = None
        # Only trust the disaggregator when it was read this tick and the EV
        # power fail-safe is not active.
        if not self._has_ev_charger or self._ev_power_fetch_failed:
            return
        load = self._load_disaggregator.get_load_by_id(charger_cfg.id)
        if load is None or not load.is_healthy:
            return
        phase_count = self._resolve_active_phase_count(charger_cfg, dev_state, phase_ctrl)
        dev_state.measured_draw_a = (
            abs(load.current_power_kw) * 1000 / (self.config.ev_nominal_voltage_v * phase_count)
        )

    @staticmethod
    def _effective_baseline_a(
        charger_cfg: EVChargerDeviceConfig, dev_state: EVChargerState, now: datetime
    ) -> int | None:
        """Baseline for amps adjustments: the car's settled measured draw,
        capped at the commanded setpoint and floored at min_current_a.
        Falls back to the commanded setpoint when there is no measurement or
        the setpoint changed less than EV_DRAW_SETTLE_S ago.
        """
        setpoint = dev_state.current_setpoint_a
        measured = dev_state.measured_draw_a
        changed_at = dev_state.setpoint_changed_at
        if setpoint is None or measured is None:
            return setpoint
        if changed_at is not None and (now - changed_at).total_seconds() < EV_DRAW_SETTLE_S:
            return setpoint
        return max(charger_cfg.min_current_a, min(setpoint, round(measured)))

    async def _update_ev_active_phases(
        self, charger_cfg: EVChargerDeviceConfig, dev_state: EVChargerState
    ) -> list[float]:
        """Measure which phases the EV is drawing on this session (2.2).

        Reads the charger's own per-phase power/current sensors, if configured.
        Only overwrites dev_state.active_phases when at least one phase reads
        above threshold, so a momentary all-zero reading doesn't blank out a
        known session; callers fall back to charger_cfg.phases until the first
        successful measurement (dev_state.active_phases is None).

        Returns the readable phases' values in amps (W/kW converted at the nominal grid voltage);
        empty when no per-phase sensor is configured or readable.
        """
        if not self.ha_client:
            return []

        phase_sensors = {
            1: charger_cfg.phase_sensor_l1,
            2: charger_cfg.phase_sensor_l2,
            3: charger_cfg.phase_sensor_l3,
        }
        configured = {phase: entity for phase, entity in phase_sensors.items() if entity}
        if not configured:
            return []

        voltage_v = self.config.ev_nominal_voltage_v
        active: list[int] = []
        amps: list[float] = []
        for phase, entity in configured.items():
            raw_state = await self.ha_client.get_state(entity)
            if not raw_state:
                continue
            value_str = raw_state.get("state")
            if value_str in (None, "unknown", "unavailable"):
                continue
            try:
                value = abs(float(value_str))
            except (TypeError, ValueError):
                continue
            unit = str(raw_state.get("attributes", {}).get("unit_of_measurement", "")).upper()
            if unit == "W":
                is_active = value > _EV_PHASE_ACTIVE_THRESHOLD_W
                amps.append(value / voltage_v)
            elif unit == "KW":
                is_active = value * 1000 > _EV_PHASE_ACTIVE_THRESHOLD_W
                amps.append(value * 1000 / voltage_v)
            else:
                is_active = value > _EV_PHASE_ACTIVE_THRESHOLD_A
                amps.append(value)
            if is_active:
                active.append(phase)

        if active:
            dev_state.active_phases = active
        return amps

    async def _control_ev_charger_current(
        self,
        charger_cfg: EVChargerDeviceConfig,
        dev_state: EVChargerState,
        charger_plan_kw: float,
        should_charge: bool,
        now: datetime,
        balancer_target_a: Any = _NO_BALANCER_OVERRIDE,
    ) -> None:
        """Actuate a type="current" EV charger via ampere setpoint + switch.

        Start: write the clamped setpoint, then set `switch_entity` to its
        enabled value. Stop/pause: set `switch_entity` to its disabled value
        only — never write 0 A or anything below `min_current_a`. The switch
        is re-checked every tick so external changes are corrected.

        balancer_target_a: when the load balancer is active, its final decision
        for this charger this tick (None = pause/stop) — used verbatim instead
        of recomputing from the plan. Pass the module sentinel
        `_NO_BALANCER_OVERRIDE` (the default) to compute the target from the
        plan directly, matching pre-balancer behavior exactly.
        """
        current_entity = charger_cfg.current_entity
        if not current_entity or not charger_cfg.switch_entity or not self.dispatcher:
            return

        charger_id = charger_cfg.id

        if balancer_target_a is not _NO_BALANCER_OVERRIDE:
            target_a: int | None = cast("int | None", balancer_target_a)
        else:
            active_phase_count = (
                len(dev_state.active_phases)
                if dev_state.active_phases
                else len(charger_cfg.phases or [1, 2, 3])
            ) or 1
            target_a = None
            manual_target_a = self._ev_manual_target_a(charger_cfg)
            if should_charge:
                if manual_target_a is not None:
                    target_a = manual_target_a
                elif charger_plan_kw > 0.1:
                    max_current_a = charger_cfg.max_current_a or charger_cfg.min_current_a
                    target_a = planned_kw_to_amps(
                        charger_plan_kw,
                        active_phase_count,
                        charger_cfg.min_current_a,
                        max_current_a,
                        self.config.ev_nominal_voltage_v,
                    )
                else:
                    # Keep-on-only (no balancer active): hold the relay closed
                    # at the configured minimum current (D3).
                    target_a = charger_cfg.min_current_a

        # Never command below the floor: a sub-minimum target is a pause.
        if target_a is not None and target_a < charger_cfg.min_current_a:
            target_a = None

        desired_key = "stop" if target_a is None else f"charge:{target_a}"
        if self._ev_backoff_active(charger_id, desired_key, now):
            return

        try:
            if target_a is None:
                await self._stop_current_charger(charger_cfg, dev_state, now, desired_key)
                return

            # Always go through the dispatcher: it compares against the live HA
            # state and skips the write when the charger already holds target_a,
            # so an external change (e.g. the go-e app) is corrected every tick.
            result = await self.dispatcher.set_ev_charger_current(current_entity, target_a)
            self._log_ev_action(charger_id, result, "ev_charge_current", now)
            self._ev_record_write_outcome(charger_id, desired_key, result, now)
            if not result.success:
                return
            if dev_state.current_setpoint_a != target_a:
                dev_state.setpoint_changed_at = now
            dev_state.current_setpoint_a = target_a

            result = await self._set_charger_switch(
                charger_cfg, turn_on=True, charging_kw=charger_plan_kw
            )
            self._log_ev_action(charger_id, result, "ev_charge_start", now)
            self._ev_record_write_outcome(charger_id, desired_key, result, now)
            if not result.success:
                return
            dev_state.charging_active = True
            dev_state.charging_slot_end = now + timedelta(minutes=15)

        except Exception as e:
            logger.error("Failed to control EV charger %s (current): %s", charger_id, e)

    async def _stop_current_charger(
        self,
        charger_cfg: EVChargerDeviceConfig,
        dev_state: EVChargerState,
        now: datetime,
        desired_key: str = "stop",
    ) -> bool:
        """Stop/pause a type="current" charger via its `switch_entity`.

        Sets the switch to `charge_disabled_value` (select-like) or `off`
        (switch-like). The ampere setpoint is left untouched — a later start
        overwrites it. Idempotent: no write when already disabled.
        """
        result = await self._set_charger_switch(charger_cfg, turn_on=False)
        self._log_ev_action(charger_cfg.id, result, "ev_charge_stop", now)
        self._ev_record_write_outcome(charger_cfg.id, desired_key, result, now)
        if not result.success:
            return False
        dev_state.charging_active = False
        dev_state.charging_slot_end = None
        dev_state.current_setpoint_a = None
        dev_state.setpoint_changed_at = None
        dev_state.active_phases = None
        return True
