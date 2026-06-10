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
from .config import (
    ControllerConfig,
    InverterConfig,
    WaterHeaterDeviceConfig,
    WaterHeaterGlobalConfig,
)
from .override import OverrideResult, SlotPlan, SystemState
from .profiles import InverterProfile

logger = logging.getLogger(__name__)


@dataclass
class ControllerDecision:
    """The controller's decision on what actions to take.

    Uses 4 mode intents: charge, export, idle, self_consumption.
    The executor looks up the mode definition from the profile to get
    the ordered list of actions to execute.
    """

    # Mode intent - the primary field (required)
    # Values: "charge", "export", "idle", "self_consumption"
    mode_intent: str

    # Charge/discharge values (templates for executor to resolve)
    charge_value: float = 0.0
    discharge_value: float = 0.0

    # SoC target
    soc_target: int = 10

    # Water heater
    water_temp: int = 40  # Aggregate/fallback scalar (backward compat)
    water_temps: dict[str, int] = None  # type: ignore[assignment]  # Per-device: heater_id → temp

    def __post_init__(self) -> None:
        if self.water_temps is None:  # type: ignore[comparison-overlap]
            self.water_temps = {}

    export_power_w: float = 0.0  # Planned grid export power in Watts
    export_with_load_w: float = 0.0  # Export power + house load (for Fronius export mode)

    # User's configured max limits (for templates like {{max_charge}})
    max_charge: float = 0.0
    max_discharge: float = 0.0

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
        water_heater_config: WaterHeaterGlobalConfig | None = None,
        water_heater_devices: list[WaterHeaterDeviceConfig] | None = None,
        profile: InverterProfile | None = None,
    ):
        self.config = config
        self.inverter_config = inverter_config
        self.water_heater_config = water_heater_config or WaterHeaterGlobalConfig()
        self.water_heater_devices = water_heater_devices or []
        self.profile = profile

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
        """Apply override actions instead of plan using 4 mode intents."""
        actions = override.actions or {}

        # Determine mode intent from override type
        mode_intent = "idle"  # default

        if override.override_type.value == "force_charge":
            mode_intent = "charge"

        # For overrides, we typically don't actively charge/discharge
        # unless specifically requested
        charge_value = 0.0
        discharge_value = 0.0
        write_charge = False
        write_discharge = False

        # Handle quick action charging
        if override.override_type.value == "force_charge":
            # Force charge - use max charging value
            if self.inverter_config.control_unit == "W":
                charge_value = self.config.max_charge_w
            else:
                charge_value = self.config.max_charge_a
            write_charge = True

        # Get SoC target and water temp from override
        soc_target = int(actions.get("soc_target", 10))
        water_temp = int(actions.get("water_temp", 40))

        # User's configured max limits (for templates)
        unit = (
            self.profile.behavior.control_unit
            if self.profile
            else self.inverter_config.control_unit
        )
        max_charge = self.config.max_charge_w if unit == "W" else self.config.max_charge_a
        max_discharge = self.config.max_discharge_w if unit == "W" else self.config.max_discharge_a

        return ControllerDecision(
            mode_intent=mode_intent,
            charge_value=charge_value,
            discharge_value=discharge_value,
            export_power_w=0.0,
            export_with_load_w=0.0,
            soc_target=soc_target,
            water_temp=water_temp,
            max_charge=max_charge,
            max_discharge=max_discharge,
            write_charge_current=write_charge,
            write_discharge_current=write_discharge,
            control_unit=unit,
            source="override",
            reason=override.reason,
        )

    def _follow_plan(self, slot: SlotPlan, state: SystemState) -> ControllerDecision:
        """Follow the slot plan for normal operation using 4 mode intents."""
        # Determine mode intent based on slot plan
        # Order matters: export > charge > idle > self_consumption
        #
        # PV surplus vs battery export distinction:
        # - Battery export: discharge_kw > 0 (battery actively discharging to grid)
        # - PV surplus: discharge_kw == 0, charge_kw > 0 (excess PV exports while charging)
        if slot.export_kw > 0 and slot.discharge_kw > 0:
            # Battery discharge to grid - use export mode
            mode_intent = "export"
        elif slot.charge_kw > 0 and slot.export_kw == 0:
            # Grid charging (no PV surplus) - use charge mode with grid_charging ON
            mode_intent = "charge"
        elif slot.charge_kw > 0:
            # PV surplus (charge_kw > 0 AND export_kw > 0 AND discharge_kw == 0)
            # Charge battery from PV while exporting excess - use self_consumption
            mode_intent = "self_consumption"
        elif round(state.current_soc_percent) <= slot.soc_target:
            # At or below SoC target - use idle to hold battery
            # Round current SoC to integer for consistent comparison with plan target
            mode_intent = "idle"
        elif slot.discharge_kw == 0 and slot.ev_charging_kw > 0.1:
            # REV F76 Phase 3: EV charging active - use idle instead of self_consumption
            # to prevent any battery discharge to EV
            mode_intent = "idle"
        else:
            # Above SoC target - use self_consumption
            mode_intent = "self_consumption"

        # Calculate charge/discharge values
        charge_value, write_charge = self._calculate_charge_limit(slot, state)
        discharge_value, write_discharge = self._calculate_discharge_limit(slot, state)

        # Planned grid export power (kW to W)
        export_power_w = slot.export_kw * 1000.0

        # Calculate export_with_load_w for Fronius export mode
        # This adds house load to export power so battery delivers both
        if slot.export_kw > 0:
            step = self.profile.behavior.round_step_w if self.profile else 100.0
            raw_export_with_load = export_power_w + (slot.load_kw * 1000.0)
            export_with_load_w = round(raw_export_with_load / step) * step
        else:
            export_with_load_w = 0.0

        # SoC target from plan
        soc_target = slot.soc_target

        # Water heater from plan (scalar + per-device)
        water_temp = self._determine_water_temp(slot)
        water_temps = self._determine_water_temps(slot)

        # User's configured max limits (for templates)
        unit = (
            self.profile.behavior.control_unit
            if self.profile
            else self.inverter_config.control_unit
        )
        max_charge = self.config.max_charge_w if unit == "W" else self.config.max_charge_a
        max_discharge = self.config.max_discharge_w if unit == "W" else self.config.max_discharge_a

        # Override for self_consumption default fallback
        # When no charge is planned (charge_value <= 0) and we fall back to self_consumption,
        # we should use max charge instead of 0 to allow PV to charge the battery.
        if mode_intent == "self_consumption" and charge_value <= 0:
            charge_value = max_charge
            write_charge = True

        reason = self._generate_reason(slot, mode_intent)

        return ControllerDecision(
            mode_intent=mode_intent,
            charge_value=charge_value,
            discharge_value=discharge_value,
            export_power_w=export_power_w,
            export_with_load_w=export_with_load_w,
            soc_target=soc_target,
            water_temp=water_temp,
            water_temps=water_temps,
            max_charge=max_charge,
            max_discharge=max_discharge,
            write_charge_current=write_charge,
            write_discharge_current=write_discharge,
            control_unit=unit,
            source="plan",
            reason=reason,
        )

    def _calculate_charge_limit(self, slot: SlotPlan, state: SystemState) -> tuple[float, bool]:
        """
        Calculate the charge limit to command (Amps or Watts).
        """
        unit = self.inverter_config.control_unit
        if self.profile and self.profile.behavior.control_unit:
            unit = self.profile.behavior.control_unit

        if slot.charge_kw <= 0:
            logger.debug("No charge planned, returning 0")
            return 0.0, False

        if unit == "W":
            # Watts Logic
            raw_val = slot.charge_kw * 1000.0

            # Round to step
            is_grid_charge = slot.charge_kw > 0
            step = self.profile.behavior.round_step_w if self.profile else self.config.round_step_w

            # Use grid-specific rounding if available (Rev IP1 Phase 4)
            if is_grid_charge and self.profile and self.profile.behavior.grid_charge_round_step_w:
                step = self.profile.behavior.grid_charge_round_step_w
                logger.debug("Using grid-specific rounding step: %.1fW", step)

            rounded = round(raw_val / step) * step

            # Clamp
            min_w = self.profile.behavior.min_charge_w if self.profile else self.config.min_charge_w
            max_w = self.config.max_charge_w
            clamped = max(min_w, min(max_w, rounded))

            # Decide if we should write
            should_write = clamped >= min_w

            return clamped, should_write

        else:
            # Amps Logic (Default)
            # kW to Amps: I = P * 1000 / V
            raw_current = (slot.charge_kw * 1000) / self.config.nominal_voltage_v

            # Round to step
            round_step_a = (
                self.profile.behavior.round_step_a if self.profile else self.config.round_step_a
            )
            rounded = round(raw_current / round_step_a) * round_step_a

            # Clamp to limits
            min_a = self.profile.behavior.min_charge_a if self.profile else self.config.min_charge_a
            max_a = self.config.max_charge_a
            clamped = max(min_a, min(max_a, rounded))

            # Decide if we should write
            should_write = clamped >= min_a

            return clamped, should_write

    def _calculate_discharge_limit(self, slot: SlotPlan, state: SystemState) -> tuple[float, bool]:
        """
        Calculate the discharge limit to command.
        ALWAYS return MAX to allow load coverage.
        """
        if self.inverter_config.control_unit == "W":
            return self.config.max_discharge_w, True
        else:
            return self.config.max_discharge_a, True

    def _determine_water_temp(self, slot: SlotPlan) -> int:
        """Determine aggregate water heater target temperature from slot plan (backward compat)."""
        if slot.water_kw > 0:
            return self.water_heater_config.temp_normal
        return self.water_heater_config.temp_off

    def _determine_water_temps(self, slot: SlotPlan) -> dict[str, int]:
        """Determine per-device water heater temperatures from slot plan (task 6.4)."""
        if not self.water_heater_devices:
            return {}
        temps: dict[str, int] = {}
        for device in self.water_heater_devices:
            planned_kw = slot.water_heater_plans.get(device.id, 0.0)
            is_boost = slot.water_heating_boost.get(device.id, False)
            if is_boost and planned_kw > 0:
                # Excess PV boost uses temp_max (85°C, the PV dump target).
                # temp_boost (70°C) is reserved for the manual dashboard boost button.
                temps[device.id] = self.water_heater_config.temp_max
            elif planned_kw > 0:
                temps[device.id] = self.water_heater_config.temp_normal
            else:
                temps[device.id] = self.water_heater_config.temp_off
        return temps

    def _generate_reason(self, slot: SlotPlan, mode_intent: str) -> str:
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

        # Use mode intent directly for reason string
        mode_str = mode_intent.replace("_", " ").title()

        return f"Plan: {', '.join(parts)} | {mode_str} | SoC→{slot.soc_target}%"


def make_decision(
    slot: SlotPlan,
    state: SystemState,
    override: OverrideResult | None = None,
    config: ControllerConfig | None = None,
    inverter_config: InverterConfig | None = None,
    water_heater_config: WaterHeaterGlobalConfig | None = None,
    water_heater_devices: list[WaterHeaterDeviceConfig] | None = None,
    profile: InverterProfile | None = None,
) -> ControllerDecision:
    """
    Convenience function to make a controller decision.

    Returns:
        ControllerDecision with all action parameters
    """
    controller = Controller(
        config or ControllerConfig(),
        inverter_config or InverterConfig(),
        water_heater_config,
        water_heater_devices,
        profile,
    )
    return controller.decide(slot, state, override)
