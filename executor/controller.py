"""
Controller Logic

Action decision-making based on slot plan and current state.
Ported from the n8n Helios Executor "Controller" code node.

Determines:
- Which inverter work mode to set
- Whether to enable grid charging
- What charge/discharge currents to command
- SoC target to set
- Water heater temperature target
"""

import logging
from dataclasses import dataclass

# from typing import Any, Dict, Optional, Tuple
from .config import ControllerConfig, InverterConfig, WaterHeaterConfig
from .override import OverrideResult, SlotPlan, SystemState

logger = logging.getLogger(__name__)


@dataclass
class ControllerDecision:
    """The controller's decision on what actions to take."""

    # Inverter control
    work_mode: str  # "Export First" or "Zero Export To CT"
    grid_charging: bool
    grid_charging: bool
    charge_value: float
    discharge_value: float

    # SoC target
    soc_target: int

    # Water heater
    water_temp: int
    export_power_w: float = 0.0  # Planned grid export power in Watts (Bug Fix #1)

    # Flags
    write_charge_current: bool = False  # Only write if significant change
    write_discharge_current: bool = False
    control_unit: str = "A"  # "A" or "W"
    source: str = "plan"  # "plan" or "override"
    reason: str = ""


class Controller:
    """
    Determines actions based on slot plan and current state.

    Ported from n8n Helios Executor "Controller" JavaScript node.
    """

    def __init__(
        self,
        config: ControllerConfig,
        inverter_config: InverterConfig,
        water_heater_config: WaterHeaterConfig | None = None,
    ):
        self.config = config
        self.inverter_config = inverter_config
        self.water_heater_config = water_heater_config or WaterHeaterConfig()

    def decide(
        self,
        slot: SlotPlan,
        state: SystemState,
        override: OverrideResult | None = None,
    ) -> ControllerDecision:
        """
        Determine what actions to take based on slot plan and override.

        Args:
            slot: The current slot's planned values
            state: Current system state
            override: Override result if any override is active

        Returns:
            ControllerDecision with all action parameters
        """
        # If override is active, apply override actions
        if override and override.override_needed:
            return self._apply_override(slot, state, override)

        # Normal operation - follow the plan
        return self._follow_plan(slot, state)

    def _apply_override(
        self,
        slot: SlotPlan,
        state: SystemState,
        override: OverrideResult,
    ) -> ControllerDecision:
        """Apply override actions instead of plan."""
        actions = override.actions or {}

        # Use override values, falling back to safe defaults
        work_mode = actions.get("work_mode", "Zero Export To CT")
        grid_charging = bool(actions.get("grid_charging", False))
        soc_target = int(actions.get("soc_target", 10))
        water_temp = int(actions.get("water_temp", 40))

        # For overrides, we typically don't actively charge/discharge
        # unless specifically requested
        charge_value = 0.0
        discharge_value = 0.0
        write_charge = False
        write_discharge = False

        # Handle quick action charging
        if grid_charging and override.override_type.value in ("force_charge", "emergency_charge"):
            # Force charge - use max charging value
            if self.inverter_config.control_unit == "W":
                charge_value = self.config.max_charge_w
            else:
                charge_value = self.config.max_charge_a
            write_charge = True

        # Handle quick action exporting
        if override.override_type.value == "force_export":
            # Force export - allow max discharge
            if self.inverter_config.control_unit == "W":
                discharge_value = self.config.max_discharge_w
            else:
                discharge_value = self.config.max_charge_a  # Use max
            write_discharge = True

        return ControllerDecision(
            work_mode=work_mode,
            grid_charging=grid_charging,
            charge_value=charge_value,
            discharge_value=discharge_value,
            export_power_w=0.0,
            soc_target=soc_target,
            water_temp=water_temp,
            write_charge_current=write_charge,
            write_discharge_current=write_discharge,
            control_unit=self.inverter_config.control_unit,
            source="override",
            reason=override.reason,
        )

    def _follow_plan(self, slot: SlotPlan, state: SystemState) -> ControllerDecision:
        """Follow the slot plan for normal operation."""
        # Determine work mode based on planned export
        work_mode = "Export First" if slot.export_kw > 0 else "Zero Export To CT"

        # Determine grid charging
        # Grid charging is enabled when we're actively charging from grid
        grid_charging = slot.charge_kw > 0 and slot.export_kw == 0

        # Calculate charge/discharge values
        charge_value, write_charge = self._calculate_charge_limit(slot, state)
        discharge_value, write_discharge = self._calculate_discharge_limit(slot, state)

        # Planned grid export power (kW to W)
        export_power_w = slot.export_kw * 1000.0

        # SoC target from plan
        soc_target = slot.soc_target

        # Water heater from plan
        water_temp = self._determine_water_temp(slot)

        reason = self._generate_reason(slot, work_mode, grid_charging)

        return ControllerDecision(
            work_mode=work_mode,
            grid_charging=grid_charging,
            charge_value=charge_value,
            discharge_value=discharge_value,
            export_power_w=export_power_w,
            soc_target=soc_target,
            water_temp=water_temp,
            write_charge_current=write_charge,
            write_discharge_current=write_discharge,
            control_unit=self.inverter_config.control_unit,
            source="plan",
            reason=reason,
        )

    def _calculate_charge_limit(self, slot: SlotPlan, state: SystemState) -> tuple[float, bool]:
        """
        Calculate the charge limit to command (Amps or Watts).
        """
        unit = self.inverter_config.control_unit

        if slot.charge_kw <= 0:
            logger.debug("No charge planned, returning 0")
            return 0.0, False

        if unit == "W":
            # Watts Logic
            raw_val = slot.charge_kw * 1000.0
            
            # Round to step
            step = self.config.round_step_w
            rounded = round(raw_val / step) * step
            
            # Clamp
            clamped = max(
                self.config.min_charge_w,
                min(self.config.max_charge_w, rounded)
            )
            
            # Write trigger?
            should_write = clamped >= self.config.min_charge_w
            
            return clamped, should_write

        else:
            # Amps Logic (Default)
            # kW to Amps: I = P * 1000 / V
            raw_current = (slot.charge_kw * 1000) / self.config.worst_case_voltage_v

            # Round to step
            rounded = round(raw_current / self.config.round_step_a) * self.config.round_step_a

            # Clamp to limits
            clamped = max(self.config.min_charge_a, min(self.config.max_charge_a, rounded))

            # Decide if we should write
            should_write = clamped >= self.config.min_charge_a

            return clamped, should_write

    def _calculate_discharge_limit(
        self, slot: SlotPlan, state: SystemState
    ) -> tuple[float, bool]:
        """
        Calculate the discharge limit to command.
        ALWAYS return MAX to allow load coverage.
        """
        if self.inverter_config.control_unit == "W":
            return self.config.max_discharge_w, True
        else:
            return self.config.max_discharge_a, True

    def _determine_water_temp(self, slot: SlotPlan) -> int:
        """Determine water heater target temperature from slot plan."""
        if slot.water_kw > 0:
            # Water heating is active - use configured normal temp
            return self.water_heater_config.temp_normal
        else:
            # No water heating - use configured off temp
            return self.water_heater_config.temp_off

    def _generate_reason(self, slot: SlotPlan, work_mode: str, grid_charging: bool) -> str:
        """Generate a human-readable reason for the decision."""
        parts: list[str] = []

        if slot.charge_kw > 0:
            parts.append(f"Charge {slot.charge_kw:.1f}kW")
        if slot.export_kw > 0:
            parts.append(f"Export {slot.export_kw:.1f}kW")
        if slot.water_kw > 0:
            parts.append(f"Water {slot.water_kw:.1f}kW")

        if not parts:
            parts.append("Hold/Idle")

        mode_str = "Export" if work_mode == "Export First" else "Zero-Export"
        charge_str = "Grid+" if grid_charging else ""

        return f"Plan: {', '.join(parts)} | {charge_str}{mode_str} | SoC→{slot.soc_target}%"


def make_decision(
    slot: SlotPlan,
    state: SystemState,
    override: OverrideResult | None = None,
    config: ControllerConfig | None = None,
    inverter_config: InverterConfig | None = None,
    water_heater_config: WaterHeaterConfig | None = None,
) -> ControllerDecision:
    """
    Convenience function to make a controller decision.

    Args:
        slot: Current slot plan
        state: Current system state
        override: Override result if any
        config: Controller configuration
        inverter_config: Inverter configuration
        water_heater_config: Water heater temperature configuration

    Returns:
        ControllerDecision with all action parameters
    """
    controller = Controller(
        config or ControllerConfig(),
        inverter_config or InverterConfig(),
        water_heater_config
    )
    return controller.decide(slot, state, override)
