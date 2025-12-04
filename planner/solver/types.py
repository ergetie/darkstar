"""
Kepler Solver Types

Type definitions for the Kepler MILP solver input/output.
Migrated from backend/kepler/types.py for the new planner package.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


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
    max_export_power_kw: Optional[float] = None
    max_import_power_kw: Optional[float] = None
    target_soc_kwh: Optional[float] = None  # Minimum SoC at end of horizon
    terminal_value_sek_kwh: float = 0.0  # Value of energy left in battery
    ramping_cost_sek_per_kw: float = 0.0  # Penalty for power changes
    export_threshold_sek_per_kwh: float = 0.0  # Min spread to export
    grid_import_limit_kw: Optional[float] = None  # Soft constraint


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
    slots: List[KeplerInputSlot]
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
    is_optimal: bool = True


@dataclass
class KeplerResult:
    """Complete solver output."""
    slots: List[KeplerResultSlot]
    total_cost_sek: float
    is_optimal: bool
    status_msg: str
    solve_time_ms: float = 0.0
