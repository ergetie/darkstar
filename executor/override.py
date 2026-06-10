"""
Override Logic

Real-time override detection and handling, ported from the n8n
Helios Executor "Override" code node.

Overrides take precedence over the scheduled plan when real-time
conditions require immediate action (e.g., low SoC protection).
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OverrideType(Enum):
    """Types of overrides that can be activated."""

    NONE = "none"
    SLOT_FAILURE_FALLBACK = "slot_failure_fallback"
    MANUAL_OVERRIDE = "manual_override"
    # User-initiated quick actions
    FORCE_CHARGE = "force_charge"
    FORCE_EXPORT = "force_export"
    FORCE_STOP = "force_stop"
    FORCE_HEAT = "force_heat"


@dataclass
class OverrideResult:
    """Result of override evaluation."""

    override_needed: bool = False
    override_type: OverrideType = OverrideType.NONE
    priority: float = 0.0
    reason: str = ""
    actions: dict[str, Any] | None = None

    def __post_init__(self):
        if self.actions is None:
            self.actions = {}


@dataclass
class SystemState:
    """Current system state for override evaluation.

    Note: min_soc_percent is a planning/optimization target, not a safety limit.
    The battery BMS has a hard safety limit below Darkstar's soft limit.
    """

    # SoC
    current_soc_percent: float = 50.0
    min_soc_percent: float = 10.0

    # Power flows
    current_pv_kw: float = 0.0
    current_load_kw: float = 0.0
    current_export_kw: float = 0.0
    current_import_kw: float = 0.0

    # Inverter state
    current_work_mode: str = ""
    grid_charging_enabled: bool = False

    # Water heater
    has_water_heater: bool = True
    current_water_temp: float = 50.0
    water_temp_target: float = 60.0

    # Price info
    current_import_price: float = 0.0
    current_export_price: float = 0.0

    # Slot info
    slot_exists: bool = True
    slot_valid: bool = True

    # Manual override toggle
    manual_override_active: bool = False


@dataclass
class SlotPlan:
    """The current slot's planned values."""

    charge_kw: float = 0.0
    discharge_kw: float = 0.0
    export_kw: float = 0.0
    load_kw: float = 0.0
    water_kw: float = 0.0
    ev_charging_kw: float = 0.0
    soc_target: int = 50
    soc_projected: int = 50
    ev_charger_plans: dict[str, float] = field(default_factory=lambda: {})
    water_heater_plans: dict[str, float] = field(default_factory=lambda: {})
    water_heating_boost: dict[str, bool] = field(default_factory=lambda: {})
    custom_entity_active: bool = False


class OverrideEvaluator:
    """
    Evaluates real-time conditions and determines if overrides are needed.

    Ported from n8n Helios Executor "Override" JavaScript node.

    NOTE: Emergency charge override was removed in REV E6.
    The battery BMS has a hard safety limit below Darkstar's soft planning limit.
    min_soc_percent is a planning/optimization target, not a safety floor.
    """

    def __init__(
        self,
        water_temp_boost: int = 70,
        water_temp_max: int = 85,
        water_temp_off: int = 40,
    ):
        self.water_temp_boost = water_temp_boost
        self.water_temp_max = water_temp_max
        self.water_temp_off = water_temp_off

    def evaluate(self, state: SystemState, slot: SlotPlan | None = None) -> OverrideResult:
        """
        Evaluate current state and slot plan for override conditions.

        Overrides are evaluated in priority order (highest first):
        1. Manual override (user explicitly took control) - Priority 10
        2. Slot failure fallback - Priority 8
        """
        # Priority 10: Manual override
        if state.manual_override_active:
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.MANUAL_OVERRIDE,
                priority=10.0,
                reason="Manual override is active - executor will not change settings",
                actions={},  # No actions, let user control
            )

        # Priority 8: Slot failure fallback
        # If no valid slot exists, preserve current battery state
        if not state.slot_exists or not state.slot_valid:
            actions: dict[str, Any] = {
                "grid_charging": False,
                "soc_target": round(state.current_soc_percent),  # Keep current SoC
            }
            if state.has_water_heater:
                actions["water_temp"] = self.water_temp_off
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.SLOT_FAILURE_FALLBACK,
                priority=8.0,
                reason="No valid slot plan found - preserving current battery state",
                actions=actions,
            )

        # No override needed
        return OverrideResult(
            override_needed=False,
            override_type=OverrideType.NONE,
            priority=0.0,
            reason="",
            actions={},
        )


def evaluate_overrides(
    state: SystemState,
    slot: SlotPlan | None = None,
    config: dict[str, Any] | None = None,
) -> OverrideResult:
    """
    Convenience function to evaluate overrides with default or custom config.

    Args:
        state: Current system state
        slot: Current slot plan (optional)
        config: Override configuration parameters (optional)

    Returns:
        OverrideResult with override decision
    """
    config = config or {}
    evaluator = OverrideEvaluator(
        water_temp_boost=config.get("water_temp_boost", 70),
        water_temp_max=config.get("water_temp_max", 85),
        water_temp_off=config.get("water_temp_off", 40),
    )
    return evaluator.evaluate(state, slot)
