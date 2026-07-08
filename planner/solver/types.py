"""
Kepler Solver Types

Type definitions for the Kepler MILP solver input/output.
Migrated from backend/kepler/types.py for the new planner package.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class WaterHeaterInput:
    """Per-device water heater input for the Kepler MILP solver."""

    id: str
    power_kw: float
    min_kwh_per_day: float
    max_hours_between_heating: float
    min_spacing_hours: float
    force_on_slots: list[int] | None = None
    heated_today_kwh: float = 0.0


@dataclass
class EVChargerInput:
    """Per-device EV charger input for the Kepler MILP solver."""

    id: str
    max_power_kw: float
    battery_capacity_kwh: float
    current_soc_percent: float
    plugged_in: bool
    deadline: datetime | None
    required_kwh: float | None = None
    daily_quota_kwh: float | None = None
    keep_on_after_target: bool = False
    # "binary" (ON/OFF switch) or "current" (variable ampere setpoint). Only
    # "current" chargers are eligible for excess-PV surplus charging — surplus
    # is inherently fractional and a binary charger can't modulate to match it.
    control_type: str = "binary"


@dataclass
class ExcessPVSinkEntry:
    """One priority-ordered excess-PV sink entry, with its rank-scaled effective reward.

    Mirrors executor.config.ExcessPVSinkEntry; built by the adapter from the
    executor's `excess_pv.priority[]` config plus the shared base reward.
    """

    type: str  # "ev" | "water_heater_boost" | "custom_entity"
    effective_reward_sek_per_kwh: float
    charger_id: str | None = None  # type == "ev"
    power_kw: float = 1.0  # type == "custom_entity": estimated power draw


@dataclass
class KeplerConfig:
    """Configuration for the Kepler MILP solver."""

    capacity_kwh: float
    min_soc_percent: float
    max_soc_percent: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    wear_cost_sek_per_kwh: float
    # Optional export limits (if any)
    max_export_power_kw: float | None = None
    max_import_power_kw: float | None = None
    max_inverter_ac_kw: float | None = None  # Inverter AC output limit
    inverter_topology: str = "dc_coupled"  # "dc_coupled" | "ac_coupled"
    target_soc_kwh: float | None = None  # Minimum SoC at end of horizon
    target_soc_penalty_sek: float = 0.0  # Set by pipeline (Safety Floor penalty)
    curtailment_penalty_sek: float = 0.0  # Penalty for wasting available solar power
    ev_shortfall_penalty_sek_per_kwh: float = 50.0  # Soft penalty for missing EV target by ready-by
    ramping_cost_sek_per_kw: float = 0.0  # Penalty for power changes
    export_threshold_sek_per_kwh: float = 0.0  # Min spread to export
    grid_import_limit_kw: float | None = None  # Soft constraint
    # Per-device water heater inputs (replaces scalar water fields)
    water_heaters: list[WaterHeaterInput] = field(default_factory=lambda: [])

    # Global water heating settings (apply to all heaters)
    water_heating_max_gap_hours: float = 0.0  # Threshold for gap penalty (0 = disabled)
    water_gap_penalty_sek: float = 0.0  # Penalty per hour of gap beyond water_heating_max_gap_hours (0 = disabled); scaled by comfort_level
    water_block_penalty_sek: float = 0.0  # Penalty per slot for overshooting block window
    water_reliability_penalty_sek: float = 0.0  # Penalty per day for missing daily minimum
    max_block_hours: float = 2.0  # Rev K24: Dynamic window size per comfort level (global)
    water_spacing_penalty_sek: float = (
        0.20  # DEPRECATED (PERF1): No longer used. Spacing is now a hard constraint per device.
    )
    water_block_start_penalty_sek: float = 0.0  # Penalty per block start (global)
    defer_up_to_hours: float = 0.0  # Allow heating until N hours into next day (global)

    # Rev E4: Export Toggle
    enable_export: bool = True  # If False, enforce 0 export

    # Export SoC Floor: minimum SoC required to allow grid export
    export_floor_soc_percent: float | None = None

    # EV Charging as deferrable load (per-device, multi-charger support)
    ev_chargers: list[EVChargerInput] = field(
        default_factory=lambda: []
    )  # Per-device EV charger inputs

    # Excess PV dispatch
    excess_pv_slots: list[bool] = field(
        default_factory=lambda: []
    )  # Per-slot flags: True if excess PV available
    # Priority-ordered sink list (index 0 = highest priority); empty = disabled.
    excess_pv_priority: list[ExcessPVSinkEntry] = field(default_factory=lambda: [])
    excess_pv_soc_threshold_percent: float = 95.0  # Battery SoC % required before sink activates

    def __post_init__(self):
        """Validate configuration after initialization."""
        # Rev F39: Validate battery configuration
        if self.capacity_kwh > 0:
            if self.max_charge_power_kw <= 0:
                raise ValueError(
                    f"Battery capacity is {self.capacity_kwh} kWh but max_charge_power_kw is {self.max_charge_power_kw}. Battery cannot charge!"
                )
            if self.max_discharge_power_kw <= 0:
                raise ValueError(
                    f"Battery capacity is {self.capacity_kwh} kWh but max_discharge_power_kw is {self.max_discharge_power_kw}. Battery cannot discharge!"
                )

        # Log actual values for debugging
        import logging

        logger = logging.getLogger("darkstar.kepler.config")
        logger.info(
            f"Kepler Config: capacity={self.capacity_kwh}kWh, charge={self.max_charge_power_kw}kW, discharge={self.max_discharge_power_kw}kW"
        )


@dataclass
class KeplerInputSlot:
    """Input data for a single time slot."""

    start_time: datetime
    end_time: datetime
    load_kwh: float
    pv_kwh: float
    import_price_sek_kwh: float
    export_price_sek_kwh: float


@dataclass
class KeplerInput:
    """Complete input for a solver run."""

    slots: list[KeplerInputSlot]
    initial_soc_kwh: float


@dataclass
class KeplerResultSlot:
    """Solver output for a single time slot."""

    start_time: datetime
    end_time: datetime
    charge_kwh: float
    discharge_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    soc_kwh: float
    cost_sek: float
    import_price_sek_kwh: float = 0.0
    export_price_sek_kwh: float = 0.0
    water_heat_kw: float = 0.0  # Aggregate water heating power (backward compat)
    water_heater_results: dict[str, float] = field(
        default_factory=lambda: {}
    )  # Per-device: heater_id -> kW
    ev_charge_kw: float = 0.0  # Aggregate EV charging power in this slot (backward compat)
    ev_charger_results: dict[str, float] = field(
        default_factory=lambda: {}
    )  # Per-device: charger_id -> kW
    water_heating_boost: dict[str, bool] = field(
        default_factory=lambda: {}
    )  # Per-device: heater_id -> boost active
    custom_entity_active: dict[str, bool] = field(
        default_factory=lambda: {}
    )  # Per-entry: str(priority-list rank) -> whether that custom entity sink is on
    ev_surplus_kw: dict[str, float] = field(
        default_factory=lambda: {}
    )  # Per-charger: charger_id -> surplus-eligible kW this slot
    ev_shortfall_kwh: dict[str, float] = field(
        default_factory=lambda: {}
    )  # Per-charger: shortfall vs required_kwh by deadline
    is_optimal: bool = True


@dataclass
class KeplerResult:
    """Complete solver output."""

    slots: list[KeplerResultSlot]
    total_cost_sek: float
    is_optimal: bool
    status_msg: str
    solve_time_ms: float = 0.0
