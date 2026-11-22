"""Versioned measurement provenance stored inside slot quality flags.

This module intentionally contains no database or application-version logic.  It
records the path that produced each value and hashes only inputs that change the
measurement boundary.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, cast

PROVENANCE_SCHEMA_VERSION = 1
ENERGY_SEMANTICS = "slot-energy-v1"
RECORDER_ALGORITHM = "power-history-step-zoh-v1"
MEASUREMENT_METHODS = frozenset(
    {"power_history", "snapshot", "disabled_zero", "unconfigured_zero", "derived_history", "mixed"}
)
SUPPORTED_METHODS = MEASUREMENT_METHODS | {"unknown"}
# Every other component name (ev, water, any future device) is a device component.
NON_DEVICE_COMPONENTS = frozenset(
    {"pv", "import", "export", "load", "battery_charge", "battery_discharge"}
)
# A device with one of these methods did not give a measured value: derived load still
# contains its energy (unknown), or the value is a live reading or a placeholder.
UNMEASURED_DEVICE_METHODS = frozenset({"unknown", "snapshot", "mixed"})

# Reasons a stored ``load_kwh`` is not a trustworthy base load
# (``quality_flags.base_load = {"reliable": false, "reasons": [...]}``).
BASE_LOAD_NEGATIVE = "negative_after_subtraction"
BASE_LOAD_DEVICE_PARTIAL = "device_partial_coverage"
BASE_LOAD_LOAD_PARTIAL = "load_partial_coverage"
BASE_LOAD_INACTIVE_DEVICE = "inactive_device_drawing_power"
BASE_LOAD_LEGACY_CLAMP = "legacy_counter_clamp"
BASE_LOAD_LEGACY_AFTER_CLAMP = "legacy_counter_after_clamp"
BASE_LOAD_DISABLED_CONFIGURED = "device_disabled_but_configured"
BASE_LOAD_REASONS = frozenset(
    {
        BASE_LOAD_NEGATIVE,
        BASE_LOAD_DEVICE_PARTIAL,
        BASE_LOAD_LOAD_PARTIAL,
        BASE_LOAD_INACTIVE_DEVICE,
        BASE_LOAD_LEGACY_CLAMP,
        BASE_LOAD_LEGACY_AFTER_CLAMP,
        BASE_LOAD_DISABLED_CONFIGURED,
    }
)
# Water plus EV energy exceeded what the house used, or total load is understated:
# load + water + EV is not the real demand either. The other reasons keep demand exact.
BASE_LOAD_DEMAND_AFFECTING_REASONS = frozenset(
    {
        BASE_LOAD_NEGATIVE,
        BASE_LOAD_LOAD_PARTIAL,
        BASE_LOAD_LEGACY_CLAMP,
        BASE_LOAD_LEGACY_AFTER_CLAMP,
    }
)


def build_base_load_flag(
    *,
    clamped: bool = False,
    partial_devices: bool = False,
    partial_load: bool = False,
    inactive_device_power: bool = False,
) -> dict[str, Any] | None:
    """The ``quality_flags.base_load`` object for a slot, or None when the base load is reliable."""
    reasons = [
        reason
        for active, reason in (
            (clamped, BASE_LOAD_NEGATIVE),
            (partial_devices, BASE_LOAD_DEVICE_PARTIAL),
            (partial_load, BASE_LOAD_LOAD_PARTIAL),
            (inactive_device_power, BASE_LOAD_INACTIVE_DEVICE),
        )
        if active
    ]
    return {"reliable": False, "reasons": reasons} if reasons else None


def base_load_unreliable(flags: dict[str, Any]) -> bool:
    """Whether decoded quality flags mark the slot's ``load_kwh`` as not a trusted base load."""
    base_load = flags.get("base_load")
    return (
        isinstance(base_load, dict) and cast("dict[str, Any]", base_load).get("reliable") is False
    )


def base_load_demand_affected(flags: dict[str, Any]) -> bool:
    """Whether the base-load flag also makes load + water + EV an untrusted demand."""
    base_load = flags.get("base_load")
    if not base_load_unreliable(flags):
        return False
    reasons = cast("dict[str, Any]", base_load).get("reasons")
    return isinstance(reasons, list) and any(
        reason in BASE_LOAD_DEMAND_AFFECTING_REASONS for reason in cast("list[Any]", reasons)
    )


def device_component_methods(components: dict[str, Any]) -> dict[str, str]:
    """Method of every device component (not grid, load, pv or battery) in a components map."""
    result: dict[str, str] = {}
    for name, item in components.items():
        if name in NON_DEVICE_COMPONENTS or not isinstance(item, dict):
            continue
        method = cast("dict[str, Any]", item).get("method")
        if isinstance(method, str):
            result[str(name)] = method
    return result


def measurement_boundary(config: dict[str, Any]) -> dict[str, Any]:
    """Return canonical configuration that determines which physical boundary is measured."""
    system_value = config.get("system")
    system = cast("dict[str, Any]", system_value) if isinstance(system_value, dict) else {}
    sensors_value = config.get("input_sensors")
    sensors = cast("dict[str, Any]", sensors_value) if isinstance(sensors_value, dict) else {}
    ev_value = config.get("ev_chargers")
    ev_chargers = cast("list[dict[str, Any]]", ev_value) if isinstance(ev_value, list) else []
    water_value = config.get("water_heaters")
    water_heaters = (
        cast("list[dict[str, Any]]", water_value) if isinstance(water_value, list) else []
    )
    return {
        "meter_type": system.get("grid_meter_type", "net"),
        "sensors": {
            key: sensors.get(key)
            for key in (
                "pv_power",
                "load_power",
                "grid_power",
                "grid_import_power",
                "grid_export_power",
                "battery_power",
                "grid_power_inverted",
                "battery_power_inverted",
                "battery_soc",
            )
        },
        "solar_enabled": system.get("has_solar", True),
        "battery_enabled": system.get("has_battery", True),
        "ev": sorted(
            (str(item.get("id", "")), str(item.get("sensor", "")))
            for item in ev_chargers
            if item.get("enabled", True)
        )
        if system.get("has_ev_charger", False)
        else [],
        "water": sorted(
            (str(item.get("id", "")), str(item.get("sensor", "")))
            for item in water_heaters
            if item.get("enabled", True)
        )
        if system.get("has_water_heater", True)
        else [],
        "load_isolation": "total-minus-ev-water-v1",
    }


def boundary_fingerprint(config: dict[str, Any]) -> str:
    payload = json.dumps(measurement_boundary(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def legacy_estimate_boundary_fingerprint(config: dict[str, Any]) -> str:
    """Earlier boundary encoding, usable only as an explicit estimate assumption.

    Initial schema-v1 recordings omitted the SoC entity from the fingerprint.
    Matching that exact encoding establishes the other configured sensor paths,
    but cannot establish the historical SoC entity. It must never join calibration.
    """
    boundary = measurement_boundary(config)
    boundary["sensors"].pop("battery_soc")
    payload = json.dumps(boundary, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def recording_metadata(
    config: dict[str, Any],
    components: dict[str, dict[str, str]],
    soc_source: str,
    owner: str = "recorder",
) -> dict[str, Any]:
    """Build a fresh versioned metadata object for one accepted observation."""
    if soc_source not in {"live", "power_history", "cached", "unavailable"}:
        raise ValueError(f"unsupported SoC source: {soc_source}")
    if any(value.get("method") not in SUPPORTED_METHODS for value in components.values()):
        raise ValueError("unsupported component measurement method")
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "semantics": ENERGY_SEMANTICS,
        "boundary_fingerprint": boundary_fingerprint(config),
        "algorithm": RECORDER_ALGORITHM,
        "components": components,
        "soc": {"source": soc_source, "owner": owner},
    }


def parse_recording(
    flags: dict[str, Any], allowed_methods: frozenset[str] = MEASUREMENT_METHODS
) -> dict[str, Any] | None:
    """Return only structurally supported observed provenance; unknown stays unknown.

    ``allowed_methods`` defaults to the measured methods, so a component recorded as
    ``unknown`` makes the whole recording unusable. Callers that need to read such rows
    (a device sensor that was unavailable) pass ``SUPPORTED_METHODS``.
    """
    value = flags.get("recording")
    if not isinstance(value, dict):
        return None
    recording = cast("dict[str, Any]", value)
    if (
        type(recording.get("schema_version")) is not int
        or recording.get("schema_version") != PROVENANCE_SCHEMA_VERSION
    ):
        return None
    if recording.get("semantics") != ENERGY_SEMANTICS or not is_sha256(
        recording.get("boundary_fingerprint")
    ):
        return None
    components_value = recording.get("components")
    soc_value = recording.get("soc")
    if not isinstance(components_value, dict) or not isinstance(soc_value, dict):
        return None
    components = cast("dict[str, Any]", components_value)
    soc = cast("dict[str, Any]", soc_value)
    for item in components.values():
        if not isinstance(item, dict):
            return None
        component = cast("dict[str, Any]", item)
        if (
            not isinstance(component.get("method"), str)
            or component.get("method") not in allowed_methods
        ):
            return None
        if not isinstance(component.get("owner"), str) or component.get("owner") not in {
            "recorder",
            "backfill",
            "unknown",
        }:
            return None
    if not isinstance(soc.get("source"), str) or soc.get("source") not in {
        "live",
        "power_history",
        "cached",
        "unavailable",
        "unknown",
    }:
        return None
    if not isinstance(soc.get("owner"), str) or soc.get("owner") not in {
        "recorder",
        "backfill",
        "unknown",
    }:
        return None
    return recording


def parse_quality_flags(raw: object) -> dict[str, Any]:
    """Decode stored flags into a typed object, treating malformed input as unknown."""
    if isinstance(raw, dict):
        return cast("dict[str, Any]", raw)
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else {}
    return {}


def metadata_object(value: object) -> dict[str, Any]:
    """Narrow a decoded JSON object at its runtime boundary."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def soc_metadata(recording: dict[str, Any], endpoint: str) -> dict[str, Any]:
    """Read endpoint provenance, including the original shared-SoC representation."""
    soc = metadata_object(recording.get("soc"))
    if "start" in soc or "end" in soc:
        return metadata_object(soc.get(endpoint))
    return soc


def measurement_value_digest(values: list[Any] | tuple[Any, ...]) -> str:
    """Bind an attestation/cache identity to its complete numerical measurement preimage."""
    start = values[0]
    moment = start if isinstance(start, datetime) else datetime.fromisoformat(str(start))
    if moment.tzinfo is None:
        raise ValueError("measurement timestamp must include a timezone")
    normalized: list[Any] = [moment.astimezone(UTC).isoformat()]
    normalized.extend(None if value is None else float(value) for value in values[1:])
    payload = json.dumps(normalized, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
