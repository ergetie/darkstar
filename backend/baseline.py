"""Without-Darkstar baseline: replay recorded slots through a plain self-use inverter.

The baseline keeps the same house, solar and battery, but the battery only charges from
PV surplus and only discharges to cover load. It never charges from the grid and never
exports from the battery. Recorded battery flows are AC-side, so efficiencies are applied
between the AC flow and the stored energy.
"""

from collections.abc import Sequence
from dataclasses import dataclass

SLOT_HOURS = 0.25


@dataclass(frozen=True)
class BaselineBattery:
    """Battery parameters the self-use simulation runs on."""

    capacity_kwh: float
    min_soc_percent: float
    max_soc_percent: float
    max_charge_w: float
    max_discharge_w: float
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95


@dataclass(frozen=True)
class BaselineSlot:
    """Recorded energy of one slot (kWh) and the SoC the real battery ended it at."""

    pv_kwh: float
    load_kwh: float
    water_kwh: float
    ev_kwh: float
    soc_end_percent: float | None = None


@dataclass(frozen=True)
class BaselineFlow:
    """Simulated grid and battery energy of one slot (kWh, AC side)."""

    import_kwh: float
    export_kwh: float
    charge_kwh: float
    discharge_kwh: float


def _start_soc_percent(
    slots: Sequence[BaselineSlot], prior_soc_percent: float | None, battery: BaselineBattery
) -> float:
    """Real SoC before the first slot, else the first recorded SoC in the period, else the minimum."""
    if prior_soc_percent is not None:
        return prior_soc_percent
    for slot in slots:
        if slot.soc_end_percent is not None:
            return slot.soc_end_percent
    return battery.min_soc_percent


@dataclass(frozen=True)
class BaselineResult:
    """Simulated flows per slot and the simulated state of charge after the last slot."""

    flows: list[BaselineFlow]
    end_soc_percent: float


def simulate_self_use(
    slots: Sequence[BaselineSlot],
    battery: BaselineBattery,
    prior_soc_percent: float | None = None,
) -> list[BaselineFlow]:
    """Simulate a self-use inverter and return only the per-slot flows."""
    return simulate_self_use_with_end_state(slots, battery, prior_soc_percent).flows


def simulate_self_use_with_end_state(
    slots: Sequence[BaselineSlot],
    battery: BaselineBattery,
    prior_soc_percent: float | None = None,
) -> BaselineResult:
    """Simulate a self-use inverter over chronologically ordered slots.

    Household demand is load + water + EV. The simulated state of charge starts from the
    real one at the start of the period and is carried forward; the recorded SoC of later
    slots is never used to correct it, because it reflects Darkstar's decisions.
    """
    min_kwh = battery.capacity_kwh * battery.min_soc_percent / 100.0
    max_kwh = battery.capacity_kwh * battery.max_soc_percent / 100.0
    max_charge_kwh = battery.max_charge_w / 1000.0 * SLOT_HOURS
    max_discharge_kwh = battery.max_discharge_w / 1000.0 * SLOT_HOURS
    stored_kwh = (
        battery.capacity_kwh * _start_soc_percent(slots, prior_soc_percent, battery) / 100.0
    )

    flows: list[BaselineFlow] = []
    for slot in slots:
        surplus = slot.pv_kwh - (slot.load_kwh + slot.water_kwh + slot.ev_kwh)
        charge = discharge = 0.0
        if surplus >= 0:
            room_kwh = max(0.0, max_kwh - stored_kwh)
            charge = min(surplus, max_charge_kwh, room_kwh / battery.charge_efficiency)
            stored_kwh += charge * battery.charge_efficiency
            flows.append(BaselineFlow(0.0, surplus - charge, charge, 0.0))
        else:
            deficit = -surplus
            usable_kwh = max(0.0, stored_kwh - min_kwh)
            discharge = min(deficit, max_discharge_kwh, usable_kwh * battery.discharge_efficiency)
            stored_kwh -= discharge / battery.discharge_efficiency
            flows.append(BaselineFlow(deficit - discharge, 0.0, 0.0, discharge))
    return BaselineResult(flows, stored_kwh / battery.capacity_kwh * 100.0)
