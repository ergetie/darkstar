"""Slot energy from power history, shared by the live recorder and the backfill.

Every energy metric of a 15-minute slot (PV, load, grid, battery, EV, water) is the
step integral of the matching power sensor's HA history over exactly the slot window.
No cumulative energy counter is read anywhere.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.core.ha_client import PowerPoint, integrate_power_points

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SlotEnergySources:
    """Power entities that feed the slot energy columns, after feature flags.

    An entity that is ``None`` (not configured, or its subsystem disabled) records
    ``0.0`` for its metrics without any history request.
    """

    meter_type: str
    pv: str | None
    load: str | None
    grid: str | None
    grid_import: str | None
    grid_export: str | None
    battery: str | None
    grid_inverted: bool
    battery_inverted: bool
    # (device id, power sensor) per enabled EV charger / water heater
    ev_chargers: tuple[tuple[str, str], ...]
    water_heaters: tuple[tuple[str, str], ...]

    def entity_ids(self) -> list[str]:
        """All entities whose history is needed for a slot, without duplicates."""
        entities = [
            self.pv,
            self.load,
            self.grid,
            self.grid_import,
            self.grid_export,
            self.battery,
            *(sensor for _, sensor in self.ev_chargers),
            *(sensor for _, sensor in self.water_heaters),
        ]
        return list(dict.fromkeys(entity for entity in entities if entity))


@dataclass
class SlotEnergy:
    """Integrated slot energy per metric in kWh; ``None`` means history gave no value."""

    pv: float | None = None
    load: float | None = None
    import_kwh: float | None = None
    export_kwh: float | None = None
    batt_charge: float | None = None
    batt_discharge: float | None = None
    # Keyed by power sensor entity
    ev: dict[str, float | None] = field(default_factory=lambda: dict[str, float | None]())
    water: dict[str, float | None] = field(default_factory=lambda: dict[str, float | None]())


def build_slot_sources(config: dict[str, Any]) -> SlotEnergySources:
    """Derive the slot's power entities from ``input_sensors``, ``ev_chargers`` and ``water_heaters``."""
    system: dict[str, Any] = config.get("system", {})
    input_sensors: dict[str, Any] = config.get("input_sensors", {}) or {}
    meter_type = system.get("grid_meter_type", "net")

    def sensor(key: str, enabled: bool = True) -> str | None:
        entity = input_sensors.get(key)
        return str(entity) if enabled and entity else None

    ev_chargers: list[tuple[str, str]] = []
    if system.get("has_ev_charger", False):
        for ev_charger in config.get("ev_chargers", []):
            if ev_charger.get("enabled", True) and ev_charger.get("sensor"):
                ev_chargers.append((str(ev_charger.get("id", "")), str(ev_charger["sensor"])))

    water_heaters: list[tuple[str, str]] = []
    if system.get("has_water_heater", True):
        for water_heater in config.get("water_heaters", []):
            if water_heater.get("enabled", True) and water_heater.get("sensor"):
                water_heaters.append((str(water_heater.get("id", "")), str(water_heater["sensor"])))

    dual = meter_type == "dual"
    return SlotEnergySources(
        meter_type=meter_type,
        pv=sensor("pv_power", system.get("has_solar", True)),
        load=sensor("load_power"),
        grid=None if dual else sensor("grid_power"),
        grid_import=sensor("grid_import_power") if dual else None,
        grid_export=sensor("grid_export_power") if dual else None,
        battery=sensor("battery_power", system.get("has_battery", True)),
        grid_inverted=bool(input_sensors.get("grid_power_inverted", False)),
        battery_inverted=bool(input_sensors.get("battery_power_inverted", False)),
        ev_chargers=tuple(ev_chargers),
        water_heaters=tuple(water_heaters),
    )


def compute_slot_energy(
    sources: SlotEnergySources,
    series: dict[str, list[PowerPoint]],
    start: datetime,
    end: datetime,
) -> SlotEnergy:
    """Integrate every metric over ``[start, end]`` from parsed power points per entity.

    Sign rules: net grid is positive = import after ``grid_power_inverted``; battery is
    positive = discharge after ``battery_power_inverted``; negative samples contribute 0
    for PV, load, dual-meter import/export, EV and water. A configured entity without
    history yields ``None`` for its metrics (caller falls back to the power snapshot);
    an unconfigured or disabled one yields ``0.0``.
    """

    def integrate(entity: str | None) -> tuple[float, float] | None:
        if entity is None:
            return 0.0, 0.0
        return integrate_power_points(series.get(entity, []), start, end)

    def positive(entity: str | None) -> float | None:
        result = integrate(entity)
        return None if result is None else result[0]

    energy = SlotEnergy(pv=positive(sources.pv), load=positive(sources.load))

    if sources.meter_type == "dual":
        energy.import_kwh = positive(sources.grid_import)
        energy.export_kwh = positive(sources.grid_export)
    else:
        grid = integrate(sources.grid)
        if grid is not None:
            energy.import_kwh, energy.export_kwh = grid[::-1] if sources.grid_inverted else grid

    battery = integrate(sources.battery)
    if battery is not None:
        # integrate() returns (positive, negative magnitude) = (discharge, charge)
        discharge, charge = battery[::-1] if sources.battery_inverted else battery
        energy.batt_discharge = discharge
        energy.batt_charge = charge

    for _, sensor in sources.ev_chargers:
        energy.ev[sensor] = positive(sensor)
    for _, sensor in sources.water_heaters:
        energy.water[sensor] = positive(sensor)

    return energy


def isolate_base_load(total_load_kwh: float, ev_kwh: float, water_kwh: float) -> float:
    """Subtract EV and water energy from total load; clamp at 0 with a warning."""
    if ev_kwh <= 0 and water_kwh <= 0:
        return total_load_kwh
    base_load_kwh = total_load_kwh - ev_kwh - water_kwh
    if base_load_kwh < 0:
        logger.warning(
            f"Negative base load: total={total_load_kwh:.3f}kWh, EV={ev_kwh:.3f}kWh, "
            f"water={water_kwh:.3f}kWh. Clamping to 0."
        )
        return 0.0
    return base_load_kwh
