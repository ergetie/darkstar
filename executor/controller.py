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
from typing import cast

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

# Fixed margin (percentage points) shared by the charge-target latch and the
# hold margin (battery-plan-tracking D1/D2). The hold margin is bounded below by
# battery.min_soc_percent (min-soc-floor-tracking D1).
SOC_TRACKING_MARGIN = 2

CHARGE_TARGET_REASON = "charge target reached, holding"
HOLD_MARGIN_REASON = "hold margin used, blocking discharge"


@dataclass
class BatteryPlanState:
    """Per-block runtime state for charge-target latch and hold margin.

    Owned by the executor and passed to the controller on each tick. A block is
    identified by its kind and soc_target; any tick that is neither a grid-charge
    nor a hold slot (or has a different target) starts a fresh block.
    """

    kind: str | None = None  # "charge" | "hold"
    target: int | None = None
    latched: bool = False  # charge: stopped at target / hold: discharge blocked

    def enter(self, kind: str | None, target: int | None) -> None:
        """Reset the latch when the block changes."""
        if self.kind != kind or self.target != target:
            self.kind = kind
            self.target = target
            self.latched = False


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
        plan_state: BatteryPlanState | None = None,
    ):
        self.plan_state = plan_state if plan_state is not None else BatteryPlanState()
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
        self.plan_state.enter(None, None)
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
        raw_water_temps = actions.get("water_temps")
        water_temps: dict[str, int] = {}
        if isinstance(raw_water_temps, dict):
            typed_water_temps = cast("dict[object, object]", raw_water_temps)
            water_temps = {
                str(heater_id): int(temp)
                for heater_id, temp in typed_water_temps.items()
                if isinstance(temp, (int, float, str))
            }
        if water_temps:
            # Manual boost overrides only the selected heaters; the remaining
            # devices continue to follow this slot's per-device schedule.
            scheduled_water_temps = self._determine_water_temps(slot)
            scheduled_water_temps.update(water_temps)
            water_temps = scheduled_water_temps

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
            water_temps=water_temps,
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
        grid_charge_planned = (
            slot.grid_charge_kw > 0
            if slot.grid_charge_kw is not None
            else slot.charge_kw > 0 and slot.export_kw == 0
        )
        # Determine mode intent based on slot plan
        # Order matters: export > charge > idle > self_consumption
        #
        # PV surplus vs battery export distinction:
        # - Battery export: discharge_kw > 0 (battery actively discharging to grid)
        # - PV surplus: discharge_kw == 0, charge_kw > 0 (excess PV exports while charging)
        note: str | None = None
        live_soc = round(state.current_soc_percent)
        ev_isolating = slot.discharge_kw == 0 and (
            slot.ev_charging_kw > 0.1 or any(slot.ev_keep_on.values())
        )
        if slot.export_kw > 0 and slot.discharge_kw > 0:
            # Battery discharge to grid - use export mode
            self.plan_state.enter(None, None)
            mode_intent = "export"
        elif slot.charge_kw > 0 and grid_charge_planned:
            # Enable grid charging only while below the planned target
            # (battery-plan-tracking D1); latch per charge block.
            self.plan_state.enter("charge", slot.soc_target)
            mode_intent = self._grid_charge_or_hold(live_soc, slot.soc_target)
            if mode_intent == "idle":
                note = CHARGE_TARGET_REASON
        elif slot.charge_kw > 0:
            # Solar charging can consume all surplus, with zero grid export.
            self.plan_state.enter(None, None)
            mode_intent = "self_consumption"
        elif ev_isolating:
            # REV F76 Phase 3: EV charging active - idle prevents any battery
            # discharge to EV. keep_on-only slots (no planned kW) get the same
            # treatment (design D4). Takes precedence over the hold margin.
            self.plan_state.enter(None, None)
            mode_intent = "idle"
        elif slot.discharge_kw == 0 and not slot.discharge_blocked_by_ev:
            # Hold slot: 2-point margin below the target, bounded by min_soc_percent
            # (battery-plan-tracking D2, min-soc-floor-tracking D1).
            self.plan_state.enter("hold", slot.soc_target)
            mode_intent = self._hold_mode(live_soc, slot.soc_target)
            if mode_intent == "idle":
                note = HOLD_MARGIN_REASON
        elif live_soc <= slot.soc_target:
            # Discharge slot at its floor (or EV-isolated) - idle to hold battery
            self.plan_state.enter(None, None)
            mode_intent = "idle"
        else:
            self.plan_state.enter(None, None)
            mode_intent = "self_consumption"

        # Calculate charge/discharge values
        if note == CHARGE_TARGET_REASON:
            charge_value, write_charge = 0.0, False
        else:
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
        if note:
            reason = f"{reason} | {note}"

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

    def _grid_charge_or_hold(self, live_soc: int, target: int) -> str:
        """Charge below target; hold from target until SoC is 2 points below it."""
        st = self.plan_state
        if st.latched:
            if live_soc <= target - SOC_TRACKING_MARGIN:
                st.latched = False
                return "charge"
            return "idle"
        if live_soc >= target:
            st.latched = True
            return "idle"
        return "charge"

    def _hold_mode(self, live_soc: int, target: int) -> str:
        """Self-consumption above the hold floor; block discharge at or below it.

        The floor is ``max(target - 2, min(target, min_soc))`` so the margin never
        crosses ``battery.min_soc_percent``, and a hold at or below the minimum
        blocks immediately (min-soc-floor-tracking D1). The block lifts once SoC is
        back at the target and above the floor, so a hold at the floor only lifts
        on a real gain (no idle/self-consumption flap).
        """
        floor = max(target - SOC_TRACKING_MARGIN, min(target, self.config.min_soc_percent))
        st = self.plan_state
        if st.latched:
            if live_soc >= target and live_soc > floor:
                st.latched = False
                return "self_consumption"
            return "idle"
        if live_soc <= floor:
            st.latched = True
            return "idle"
        return "self_consumption"

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
    plan_state: BatteryPlanState | None = None,
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
        plan_state,
    )
    return controller.decide(slot, state, override)
