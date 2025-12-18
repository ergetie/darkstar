"""
Planner Input Types

Immutable dataclasses for planner input data, ensuring type safety and clear contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class SlotData:
    """
    Immutable representation of a single 15-minute planning slot.

    All energy values are in kWh, prices in SEK/kWh.
    """

    start_time: datetime
    import_price_sek: float
    export_price_sek: float
    pv_forecast_kwh: float
    load_forecast_kwh: float
    water_heater_kwh: float = 0.0

    @property
    def net_load_kwh(self) -> float:
        """Net load after PV (positive = consumption, negative = surplus)."""
        return self.load_forecast_kwh + self.water_heater_kwh - self.pv_forecast_kwh

    @property
    def price_spread(self) -> float:
        """Arbitrage potential (export - import price)."""
        return self.export_price_sek - self.import_price_sek


@dataclass(frozen=True)
class PlannerInput:
    """
    Complete input bundle for the planner pipeline.

    Attributes:
        horizon_start: Start of planning horizon (timezone-aware)
        horizon_end: End of planning horizon (timezone-aware)
        slots: Tuple of SlotData for each 15-minute slot
        initial_soc_percent: Battery state of charge at horizon start (0-100)
        battery_capacity_kwh: Total usable battery capacity
        context: Additional context (vacation_mode, weather volatility, etc.)
    """

    horizon_start: datetime
    horizon_end: datetime
    slots: Tuple[SlotData, ...]
    initial_soc_percent: float
    battery_capacity_kwh: float
    context: Dict[str, Any]

    @property
    def slot_count(self) -> int:
        """Number of slots in the planning horizon."""
        return len(self.slots)

    @property
    def horizon_hours(self) -> float:
        """Duration of planning horizon in hours."""
        delta = self.horizon_end - self.horizon_start
        return delta.total_seconds() / 3600

    def get_slot(self, index: int) -> Optional[SlotData]:
        """Get a slot by index, or None if out of bounds."""
        if 0 <= index < len(self.slots):
            return self.slots[index]
        return None


@dataclass(frozen=True)
class StrategyContext:
    """
    Context from the Strategy layer affecting planner decisions.

    Populated by analyze_safety, Aurora overlays, etc.
    """

    s_index_factor: float = 1.0
    pv_bias_adjustment: float = 0.0
    load_bias_adjustment: float = 0.0
    terminal_value_sek: float = 0.0
    vacation_mode: bool = False
    weather_volatility: float = 0.0

    @property
    def is_defensive(self) -> bool:
        """True if strategy is prioritizing safety over profit."""
        return self.s_index_factor > 1.15


@dataclass(frozen=True)
class BatteryConfig:
    """
    Battery configuration extracted from config.yaml.
    """

    capacity_kwh: float
    min_soc_percent: float = 5.0
    max_soc_percent: float = 100.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    max_charge_kw: float = 5.0
    max_discharge_kw: float = 5.0
    cycle_cost_sek_kwh: float = 0.2

    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity between min and max SoC."""
        soc_range = (self.max_soc_percent - self.min_soc_percent) / 100.0
        return self.capacity_kwh * soc_range
