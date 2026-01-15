"""
Override Logic

Real-time override detection and handling, ported from the n8n
Helios Executor "Override" code node.

Overrides take precedence over the scheduled plan when real-time
conditions require immediate action (e.g., low SoC protection,
excess PV utilization).
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OverrideType(Enum):
    """Types of overrides that can be activated."""

    NONE = "none"
    LOW_SOC_EXPORT_PREVENTION = "low_soc_export_prevention"
    EXCESS_PV_HEATING = "excess_pv_heating"
    SLOT_FAILURE_FALLBACK = "slot_failure_fallback"
    MANUAL_OVERRIDE = "manual_override"
    EMERGENCY_CHARGE = "emergency_charge"
    GRID_OUTAGE = "grid_outage"
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
    """Current system state for override evaluation."""

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
    water_kw: float = 0.0
    soc_target: int = 50
    soc_projected: int = 50


class OverrideEvaluator:
    """
    Evaluates real-time conditions and determines if overrides are needed.

    Ported from n8n Helios Executor "Override" JavaScript node.
    """

    def __init__(
        self,
        min_soc_floor: float = 10.0,
        low_soc_threshold: float = 20.0,
        excess_pv_threshold_kw: float = 2.0,
        water_temp_boost: int = 70,
        water_temp_max: int = 85,
        water_temp_off: int = 40,
    ):
        self.min_soc_floor = min_soc_floor
        self.low_soc_threshold = low_soc_threshold
        self.excess_pv_threshold_kw = excess_pv_threshold_kw
        self.water_temp_boost = water_temp_boost
        self.water_temp_max = water_temp_max
        self.water_temp_off = water_temp_off

    def evaluate(self, state: SystemState, slot: SlotPlan | None = None) -> OverrideResult:
        """
        Evaluate current state and slot plan for override conditions.

        Overrides are evaluated in priority order (highest first):
        1. Manual override (user explicitly took control) - Priority 10
        2. Emergency charge (critically low SoC) - Priority 9
        3. Low SoC export prevention - Priority 8.5
        4. Slot failure fallback - Priority 8
        5. Excess PV heating - Priority 5
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

        # Priority 9: Emergency charge (SoC BELOW absolute floor)
        if state.current_soc_percent < self.min_soc_floor:
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.EMERGENCY_CHARGE,
                priority=9.0,
                reason=f"EMERGENCY: SoC at floor ({state.current_soc_percent}%). "
                f"Enabling grid charge, stopping all export.",
                actions={
                    "work_mode": "Zero Export To CT",
                    "grid_charging": True,
                    "soc_target": max(30, int(self.min_soc_floor + 20)),
                    "water_temp": self.water_temp_off,
                },
            )

        # Priority 8.5: Low SoC export prevention
        # If plan wants to export but SoC is dangerously low
        if slot and slot.export_kw > 0 and state.current_soc_percent <= self.low_soc_threshold:
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.LOW_SOC_EXPORT_PREVENTION,
                priority=8.5,
                reason=f"Plan wants to export ({slot.export_kw:.1f} kW), but SoC is at "
                f"floor ({state.current_soc_percent}%). Preventing export.",
                actions={
                    "work_mode": "Zero Export To CT",
                    "grid_charging": False,
                    "soc_target": int(self.min_soc_floor),
                },
            )

        # Priority 8: Slot failure fallback
        # If no valid slot exists, fall back to safe defaults
        if not state.slot_exists or not state.slot_valid:
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.SLOT_FAILURE_FALLBACK,
                priority=8.0,
                reason="No valid slot plan found - using safe defaults (zero export, no charge)",
                actions={
                    "work_mode": "Zero Export To CT",
                    "grid_charging": False,
                    "soc_target": int(self.min_soc_floor),
                    "water_temp": self.water_temp_off,
                },
            )

        # Priority 5: Excess PV heating (PV dump to thermal storage)
        # If we have excess PV and water isn't at max temp, heat to max
        excess_pv = state.current_pv_kw - state.current_load_kw
        if (
            excess_pv >= self.excess_pv_threshold_kw
            and state.current_water_temp < self.water_temp_max
            and state.current_soc_percent >= 50  # Only if battery is healthy
        ):
            return OverrideResult(
                override_needed=True,
                override_type=OverrideType.EXCESS_PV_HEATING,
                priority=5.0,
                reason=f"Excess PV available ({excess_pv:.1f} kW). "
                f"Heating water to max temp to utilize free energy.",
                actions={
                    "water_temp": self.water_temp_max,
                },
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
        min_soc_floor=config.get("min_soc_floor", 10.0),
        low_soc_threshold=config.get("low_soc_threshold", 20.0),
        excess_pv_threshold_kw=config.get("excess_pv_threshold_kw", 2.0),
        water_temp_boost=config.get("water_temp_boost", 70),
        water_temp_max=config.get("water_temp_max", 85),
        water_temp_off=config.get("water_temp_off", 40),
    )
    return evaluator.evaluate(state, slot)
