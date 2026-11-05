"""Unit-aware battery power limits shared by the solver, manual plans and preflight."""

from __future__ import annotations

from typing import Any


def resolve_control_unit(config: dict[str, Any]) -> str:
    """Return the active inverter control unit: ``"W"`` only when configured, else ``"A"``."""
    inverter_cfg = config.get("executor", {}).get("inverter", {})
    return "W" if inverter_cfg.get("control_unit", "A") == "W" else "A"


def resolve_battery_power_limits(planner_config: dict[str, Any]) -> tuple[float, float]:
    """
    Resolve the battery (charge_kw, discharge_kw) limits the planner works with.

    Single source of truth shared by the solver adapter, price reserve, manual
    plans and preflight. Watt control unit uses ``max_charge_w`` /
    ``max_discharge_w``; Ampere mode (default) multiplies ``max_charge_a`` /
    ``max_discharge_a`` by the battery's nominal voltage (48 V when unset).
    Missing limits resolve to 0.0.
    """
    system = planner_config.get("system", {})
    battery = system.get("battery", planner_config.get("battery", {}))

    if resolve_control_unit(planner_config) == "W":
        return (
            float(battery.get("max_charge_w", 0.0)) / 1000.0,
            float(battery.get("max_discharge_w", 0.0)) / 1000.0,
        )

    # Amps mode - use nominal voltage for planning
    voltage = float(battery.get("nominal_voltage_v", battery.get("system_voltage_v", 48.0)))
    return (
        float(battery.get("max_charge_a", 0.0)) * voltage / 1000.0,
        float(battery.get("max_discharge_a", 0.0)) * voltage / 1000.0,
    )
