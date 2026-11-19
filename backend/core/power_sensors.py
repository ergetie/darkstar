"""Registry of config paths read as power sensors, and the unit-needed computation.

The registry is the single list of places where a configured entity is read as power.
Callers of ``resolve_power_unit`` pass one of the ``path_key`` constants below; adding a
new power sensor type means adding one registry entry and calling the resolver with its
key. Readiness and the UI never list fields themselves, they ask ``compute_unit_needed``.
"""

import math
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

from backend.core.entity_matcher import value_at_path

PV_POWER = "pv_power"
LOAD_POWER = "load_power"
BATTERY_POWER = "battery_power"
GRID_POWER = "grid_power"
GRID_IMPORT_POWER = "grid_import_power"
GRID_EXPORT_POWER = "grid_export_power"
EV_POWER = "ev_power"
EV_PHASE_POWER = "ev_phase_power"
WATER_POWER = "water_power"
LOAD_DEVICE_POWER = "load_device_power"

ENTITY_ID_PATTERN = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _enabled(_: dict[str, Any]) -> bool:
    return True


def _system_flag(flag: str, default: bool) -> Callable[[dict[str, Any]], bool]:
    def check(config: dict[str, Any]) -> bool:
        system = config.get("system")
        value = (
            cast("dict[str, Any]", system).get(flag, default)
            if isinstance(system, dict)
            else default
        )
        return bool(value)

    return check


def _grid_meter(dual: bool) -> Callable[[dict[str, Any]], bool]:
    def check(config: dict[str, Any]) -> bool:
        system = config.get("system")
        meter = (
            cast("dict[str, Any]", system).get("grid_meter_type", "net")
            if isinstance(system, dict)
            else "net"
        )
        return (meter == "dual") == dual

    return check


@dataclass(frozen=True)
class PowerSensorPath:
    """One kind of configured power sensor.

    ``patterns`` are dotted config paths; ``[*]`` expands over a list. ``applies`` says
    whether the feature behind the sensor is in use. ``report_unitless`` is False when a
    unitless reading has another established meaning (phase sensors read amps), so the
    user is never asked to pick W or kW for it.
    """

    path_key: str
    label: str
    patterns: tuple[str, ...]
    applies: Callable[[dict[str, Any]], bool] = _enabled
    report_unitless: bool = True


POWER_SENSOR_PATHS: dict[str, PowerSensorPath] = {
    entry.path_key: entry
    for entry in (
        PowerSensorPath(
            PV_POWER, "pv_power", ("input_sensors.pv_power",), _system_flag("has_solar", True)
        ),
        PowerSensorPath(LOAD_POWER, "load_power", ("input_sensors.load_power",)),
        PowerSensorPath(
            BATTERY_POWER,
            "battery_power",
            ("input_sensors.battery_power",),
            _system_flag("has_battery", True),
        ),
        PowerSensorPath(
            GRID_POWER, "grid_power", ("input_sensors.grid_power",), _grid_meter(dual=False)
        ),
        PowerSensorPath(
            GRID_IMPORT_POWER,
            "grid_import_power",
            ("input_sensors.grid_import_power",),
            _grid_meter(dual=True),
        ),
        PowerSensorPath(
            GRID_EXPORT_POWER,
            "grid_export_power",
            ("input_sensors.grid_export_power",),
            _grid_meter(dual=True),
        ),
        PowerSensorPath(
            EV_POWER,
            "ev power sensor",
            ("ev_chargers[*].sensor",),
            _system_flag("has_ev_charger", False),
        ),
        PowerSensorPath(
            EV_PHASE_POWER,
            "ev phase sensor",
            (
                "ev_chargers[*].phase_sensor_l1",
                "ev_chargers[*].phase_sensor_l2",
                "ev_chargers[*].phase_sensor_l3",
            ),
            _system_flag("has_ev_charger", False),
            report_unitless=False,
        ),
        PowerSensorPath(
            WATER_POWER,
            "water heater power sensor",
            ("water_heaters[*].sensor",),
            _system_flag("has_water_heater", True),
        ),
        PowerSensorPath(
            LOAD_DEVICE_POWER,
            "load power sensor",
            ("load_balancing.loads[*].power_sensor",),
        ),
    )
}


def _expand(config: Any, pattern: str, active_only: bool) -> Iterator[tuple[str, Any]]:
    """Yield ``(concrete_path, value)`` for every list entry the pattern matches.

    Disabled entries are skipped when ``active_only``.
    """
    head, star, rest = pattern.partition("[*].")
    if not star:
        yield pattern, value_at_path(config, pattern)
        return
    entries = value_at_path(config, head)
    if not isinstance(entries, list):
        return
    for index, entry in enumerate(cast("list[Any]", entries)):
        if not isinstance(entry, dict):
            continue
        item = cast("dict[str, Any]", entry)
        if active_only and item.get("enabled", True) is False:
            continue
        yield f"{head}.{index}.{rest}", item.get(rest)


def referenced_power_sensors(
    config: dict[str, Any],
    *,
    unitless_reportable_only: bool = False,
    active_only: bool = True,
) -> list[tuple[str, str, str]]:
    """Return ``(path_key, concrete_path, entity_id)`` for every configured power sensor.

    With ``active_only`` False, sensors of switched-off features and disabled devices
    are included (they are still configured).
    """
    found: list[tuple[str, str, str]] = []
    for entry in POWER_SENSOR_PATHS.values():
        if unitless_reportable_only and not entry.report_unitless:
            continue
        if active_only and not entry.applies(config):
            continue
        for pattern in entry.patterns:
            for path, value in _expand(config, pattern, active_only):
                if path.startswith("load_balancing.loads.") and not _is_custom_load(config, path):
                    continue
                if isinstance(value, str) and ENTITY_ID_PATTERN.match(value.strip()):
                    found.append((entry.path_key, path, value.strip()))
    return found


def _is_custom_load(config: dict[str, Any], path: str) -> bool:
    entry = value_at_path(config, path.rsplit(".", 1)[0])
    return (
        isinstance(entry, dict)
        and cast("dict[str, Any]", entry).get("device_type") == "custom_entity"
    )


def referenced_entity_ids(config: dict[str, Any], *, active_only: bool = True) -> set[str]:
    """Entities configured as power sensors anywhere in ``config``."""
    return {entity for _, _, entity in referenced_power_sensors(config, active_only=active_only)}


def compute_unit_needed(
    config: dict[str, Any], states: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """List configured power sensors for which the user can choose W or kW.

    A sensor is listed when its live state is numeric and Home Assistant reports no unit
    for it, whether or not it already has an override, so the choice stays visible and
    editable. ``override`` is the chosen ``W`` or ``kW`` (None while unchosen); only
    entries with no override need action. ``states`` maps entity id to a mapping with
    ``state`` and ``unit_of_measurement``. Each entity appears once, at its first path.
    """
    overrides = config.get("sensor_unit_overrides")
    override_table = cast("dict[str, Any]", overrides) if isinstance(overrides, dict) else {}
    needed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, path, entity_id in referenced_power_sensors(config, unitless_reportable_only=True):
        if entity_id in seen:
            continue
        seen.add(entity_id)
        live = states.get(entity_id)
        if live is None:
            continue
        if str(live.get("unit_of_measurement") or "").strip():
            continue
        try:
            value = float(live.get("state"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        chosen = override_table.get(entity_id)
        needed.append(
            {
                "entity_id": entity_id,
                "settings_path": path,
                "live_value": value,
                "override": chosen if chosen in ("W", "kW") else None,
            }
        )
    return needed
