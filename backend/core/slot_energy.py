"""Slot energy from power history, shared by the live recorder and the backfill.

Every energy metric of a 15-minute slot (PV, load, grid, battery, EV, water) is the
step integral of the matching power sensor's HA history over exactly the slot window.
No cumulative energy counter is read anywhere.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from backend.core.ha_client import PowerPoint, integrate_power_points_covered
from backend.core.water_heating import (
    DEFAULT_IDLE_POWER_THRESHOLD_KW,
    normalize_active_power_kw,
)
from backend.measurement_provenance import build_base_load_flag

logger = logging.getLogger(__name__)

# Minimum share of a slot a sensor's valid history must cover (about 45 s of 15 minutes)
# before its integrated energy is trusted as the whole slot.
MIN_COVERAGE_SHARE = 0.95
# Float noise tolerated when total load equals water plus EV (not a clamp).
_CLAMP_TOLERANCE_KWH = 1e-9

# Inactive-device sensors already warned about (once per sensor per process).
_inactive_warned: set[str] = set()


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
    water_idle_power_thresholds_kw: dict[str, float] = field(
        default_factory=lambda: cast("dict[str, float]", {})
    )
    # (device id, power sensor) of chargers / heaters that configuration excludes
    # (feature flag off or ``enabled`` false). Read only to notice a live sensor.
    inactive_ev_chargers: tuple[tuple[str, str], ...] = ()
    inactive_water_heaters: tuple[tuple[str, str], ...] = ()

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
            *(sensor for _, sensor in self.inactive_ev_chargers),
            *(sensor for _, sensor in self.inactive_water_heaters),
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
    # Share of the slot covered by valid history per sensor / for total load; ``None``
    # means no valid interval at all (the energy is then ``None`` too).
    load_coverage: float | None = None
    ev_coverage: dict[str, float | None] = field(default_factory=lambda: dict[str, float | None]())
    water_coverage: dict[str, float | None] = field(
        default_factory=lambda: dict[str, float | None]()
    )
    # Active energy of excluded (inactive) chargers / heaters, keyed by sensor entity.
    inactive: dict[str, float | None] = field(default_factory=lambda: dict[str, float | None]())


def build_slot_sources(config: dict[str, Any]) -> SlotEnergySources:
    """Derive the slot's power entities from ``input_sensors``, ``ev_chargers`` and ``water_heaters``."""
    system: dict[str, Any] = config.get("system", {})
    input_sensors: dict[str, Any] = config.get("input_sensors", {}) or {}
    meter_type = system.get("grid_meter_type", "net")

    def sensor(key: str, enabled: bool = True) -> str | None:
        entity = input_sensors.get(key)
        return str(entity) if enabled and entity else None

    ev_chargers: list[tuple[str, str]] = []
    inactive_ev_chargers: list[tuple[str, str]] = []
    ev_feature = bool(system.get("has_ev_charger", False))
    for ev_charger in config.get("ev_chargers", []):
        if not ev_charger.get("sensor"):
            continue
        device = (str(ev_charger.get("id", "")), str(ev_charger["sensor"]))
        if ev_feature and ev_charger.get("enabled", True):
            ev_chargers.append(device)
        else:
            inactive_ev_chargers.append(device)

    water_heaters: list[tuple[str, str]] = []
    inactive_water_heaters: list[tuple[str, str]] = []
    water_idle_power_thresholds_kw: dict[str, float] = {}
    water_feature = bool(system.get("has_water_heater", True))
    for water_heater in config.get("water_heaters", []):
        if not water_heater.get("sensor"):
            continue
        sensor_id = str(water_heater["sensor"])
        device = (str(water_heater.get("id", "")), sensor_id)
        if water_feature and water_heater.get("enabled", True):
            water_heaters.append(device)
        else:
            inactive_water_heaters.append(device)
        water_idle_power_thresholds_kw[sensor_id] = float(
            water_heater.get("idle_power_threshold_kw", DEFAULT_IDLE_POWER_THRESHOLD_KW)
        )
    active_sensors = {sensor for _, sensor in (*ev_chargers, *water_heaters)}
    inactive_ev_chargers = [d for d in inactive_ev_chargers if d[1] not in active_sensors]
    inactive_water_heaters = [d for d in inactive_water_heaters if d[1] not in active_sensors]

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
        water_idle_power_thresholds_kw=water_idle_power_thresholds_kw,
        inactive_ev_chargers=tuple(inactive_ev_chargers),
        inactive_water_heaters=tuple(inactive_water_heaters),
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

    slot_seconds = (end - start).total_seconds()

    def covered(
        entity: str | None, points: list[PowerPoint] | None = None
    ) -> tuple[float, float, float] | None:
        """``(positive, negative, share of slot covered)`` or None without a valid interval."""
        if entity is None:
            return 0.0, 0.0, 1.0
        integrated = integrate_power_points_covered(
            series.get(entity, []) if points is None else points, start, end
        )
        if integrated is None:
            return None
        return integrated[0], integrated[1], min(1.0, integrated[2] / slot_seconds)

    def integrate(entity: str | None) -> tuple[float, float] | None:
        result = covered(entity)
        return None if result is None else (result[0], result[1])

    def positive(entity: str | None) -> float | None:
        result = integrate(entity)
        return None if result is None else result[0]

    def active_water(sensor: str) -> tuple[float, float, float] | None:
        cutoff = sources.water_idle_power_thresholds_kw.get(sensor, DEFAULT_IDLE_POWER_THRESHOLD_KW)
        active_points: list[PowerPoint] = [
            (
                timestamp,
                None
                if value is None
                else max(0.0, normalize_active_power_kw(value, "kW", cutoff) or 0.0),
            )
            for timestamp, value in series.get(sensor, [])
        ]
        return covered(sensor, active_points)

    energy = SlotEnergy(pv=positive(sources.pv), load=positive(sources.load))
    load_covered = covered(sources.load)
    energy.load_coverage = None if load_covered is None else load_covered[2]

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
        ev_covered = covered(sensor)
        energy.ev[sensor] = None if ev_covered is None else ev_covered[0]
        energy.ev_coverage[sensor] = None if ev_covered is None else ev_covered[2]
    for _, sensor in sources.water_heaters:
        water_covered = active_water(sensor)
        energy.water[sensor] = None if water_covered is None else water_covered[0]
        energy.water_coverage[sensor] = None if water_covered is None else water_covered[2]
    for _, sensor in sources.inactive_ev_chargers:
        energy.inactive[sensor] = positive(sensor)
    for _, sensor in sources.inactive_water_heaters:
        inactive_covered = active_water(sensor)
        energy.inactive[sensor] = None if inactive_covered is None else inactive_covered[0]

    return energy


@dataclass(frozen=True)
class BaseLoadIsolation:
    """Base load after subtracting deferrable loads; ``clamped`` when it went negative."""

    kwh: float
    clamped: bool


def isolate_base_load(total_load_kwh: float, ev_kwh: float, water_kwh: float) -> BaseLoadIsolation:
    """Subtract EV and water energy from total load.

    A negative result is stored as the placeholder 0.0 and reported as ``clamped``, so the
    caller can flag the slot instead of trusting that 0. Exact equality is not a clamp.
    """
    if ev_kwh <= 0 and water_kwh <= 0:
        return BaseLoadIsolation(total_load_kwh, False)
    base_load_kwh = total_load_kwh - ev_kwh - water_kwh
    if base_load_kwh < -_CLAMP_TOLERANCE_KWH:
        logger.warning(
            f"Negative base load: total={total_load_kwh:.3f}kWh, EV={ev_kwh:.3f}kWh, "
            f"water={water_kwh:.3f}kWh. Clamping to 0."
        )
        return BaseLoadIsolation(0.0, True)
    return BaseLoadIsolation(max(0.0, base_load_kwh), False)


def slot_base_load_flag(
    sources: SlotEnergySources, energy: SlotEnergy, clamped: bool
) -> dict[str, Any] | None:
    """The ``quality_flags.base_load`` object of a slot (None when reliable).

    One rule set for the live recorder and the backfill: a clamped subtraction, a device
    or total-load sensor with history for less than ``MIN_COVERAGE_SHARE`` of the slot,
    or an excluded device whose sensor shows active energy.
    """

    def below_minimum(coverage: dict[str, float | None]) -> bool:
        return any(share is not None and share < MIN_COVERAGE_SHARE for share in coverage.values())

    partial_load = (
        sources.load is not None
        and energy.load is not None
        and energy.load_coverage is not None
        and energy.load_coverage < MIN_COVERAGE_SHARE
    )
    inactive_power = False
    for kind, devices, config_keys in (
        (
            "water heater",
            sources.inactive_water_heaters,
            "system.has_water_heater / water_heaters[].enabled",
        ),
        (
            "EV charger",
            sources.inactive_ev_chargers,
            "system.has_ev_charger / ev_chargers[].enabled",
        ),
    ):
        for _, sensor in devices:
            if (energy.inactive.get(sensor) or 0.0) > 0:
                inactive_power = True
                if sensor not in _inactive_warned:
                    _inactive_warned.add(sensor)
                    logger.warning(
                        f"{kind} sensor {sensor} is excluded by configuration but draws power; "
                        f"its energy stays in base load. Check {config_keys}."
                    )
    return build_base_load_flag(
        clamped=clamped,
        partial_devices=below_minimum(energy.ev_coverage) or below_minimum(energy.water_coverage),
        partial_load=partial_load,
        inactive_device_power=inactive_power,
    )
