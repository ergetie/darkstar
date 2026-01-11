"""
Kepler Solver Types

Type definitions for the Kepler MILP solver input/output.
Migrated from backend/kepler/types.py for the new planner package.
"""

from dataclasses import dataclass
from datetime import datetime


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
    target_soc_kwh: float | None = None  # Minimum SoC at end of horizon
    target_soc_penalty_sek: float = (
        10.0  # Soft penalty for missing target (derived from risk_appetite)
    )
    terminal_value_sek_kwh: float = 0.0  # Value of energy left in battery
    ramping_cost_sek_per_kw: float = 0.0  # Penalty for power changes
    export_threshold_sek_per_kwh: float = 0.0  # Min spread to export
    grid_import_limit_kw: float | None = None  # Soft constraint
    # Water heating as deferrable load (Rev K17/K18)
    water_heating_power_kw: float = 0.0  # 0 = disabled
    water_heating_min_kwh: float = 0.0  # Daily minimum
    water_heating_max_gap_hours: float = 0.0  # Threshold for gap penalty (0 = disabled)
    water_heated_today_kwh: float = 0.0  # Already heated today (reduces remaining min)
    water_comfort_penalty_sek: float = 0.50  # Penalty per hour beyond gap threshold
    water_min_spacing_hours: float = 5.0  # Rev K21: Min gap between starts to avoid efficiency loss
    water_spacing_penalty_sek: float = 0.20  # Rev K21: Soft penalty for frequent starts
    # Rev WH2: Mid-block locking (force ON for specific slots)
    force_water_on_slots: list[int] | None = None  # Slots indices that MUST be ON
    
    # Rev WH2: Block start penalty
    water_block_start_penalty_sek: float = 0.0  # Penalty for starting a new block
    
    # Rev WH2: Smart deferral
    defer_up_to_hours: float = 0.0  # Allow heating until N hours into next day



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
    water_heat_kw: float = 0.0  # Rev K17: Water heating power in this slot
    is_optimal: bool = True


@dataclass
class KeplerResult:
    """Complete solver output."""

    slots: list[KeplerResultSlot]
    total_cost_sek: float
    is_optimal: bool
    status_msg: str
    solve_time_ms: float = 0.0
