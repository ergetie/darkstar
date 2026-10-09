"""Shared water-heater power and quota-window semantics."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Any, cast

import pytz

from backend.measurement_provenance import metadata_object, parse_recording

DEFAULT_IDLE_POWER_THRESHOLD_KW = 0.0
WATER_HEATER_ENERGY_SCHEMA_VERSION = 1
WATER_HEATER_ENERGY_SEMANTICS = "active-water-energy-v1"


def normalize_active_power_kw(
    value: object,
    unit: object = "kW",
    idle_power_threshold_kw: object = DEFAULT_IDLE_POWER_THRESHOLD_KW,
) -> float | None:
    """Convert a finite power reading to kW and filter only samples below its cutoff."""
    if (
        isinstance(idle_power_threshold_kw, bool)
        or not isinstance(idle_power_threshold_kw, int | float)
        or not math.isfinite(idle_power_threshold_kw)
        or idle_power_threshold_kw < 0
    ):
        raise ValueError("idle_power_threshold_kw must be finite and non-negative")
    cutoff_kw = float(idle_power_threshold_kw)
    if isinstance(value, bool):
        return None
    if not isinstance(value, str | int | float):
        return None
    try:
        power_kw = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(power_kw):
        return None

    normalized_unit = str(unit or "").strip().upper()
    if normalized_unit == "W":
        power_kw /= 1000.0
    elif normalized_unit == "MW":
        power_kw *= 1000.0
    # Preserve negative power for bidirectional grid/battery sensors. Water
    # components clamp their own readings to non-negative active load.
    return 0.0 if 0.0 <= power_kw < cutoff_kw else power_kw


def validate_water_heating_config(config: dict[str, Any]) -> None:
    """Reject invalid scheduling values with field-specific correction guidance."""
    raw_water: Any = config.get("water_heating", {})
    water = cast("dict[str, Any]", raw_water) if isinstance(raw_water, dict) else {}
    defer = water.get("defer_up_to_hours", 6.0)
    if (
        isinstance(defer, bool)
        or not isinstance(defer, int | float)
        or not math.isfinite(defer)
        or not 0 <= defer <= 23
    ):
        raise ValueError(
            "water_heating.defer_up_to_hours must be finite and between 0 and 23 hours "
            f"inclusive (got {defer}); correct this value explicitly."
        )

    heaters_value = config.get("water_heaters", [])
    if not isinstance(heaters_value, list):
        return
    raw_heaters = cast("list[Any]", heaters_value)
    for index, raw_heater in enumerate(raw_heaters):
        if not isinstance(raw_heater, dict):
            continue
        heater = cast("dict[str, Any]", raw_heater)
        max_gap = heater.get("max_hours_between_heating", 8.0)
        if (
            isinstance(max_gap, bool)
            or not isinstance(max_gap, int | float)
            or not math.isfinite(max_gap)
            or max_gap < 0
        ):
            raise ValueError(
                f"water_heaters[{index}].max_hours_between_heating must be finite and non-negative "
                f"(got {max_gap}); use 0 to disable the comfort ceiling."
            )
        cutoff = heater.get("idle_power_threshold_kw", DEFAULT_IDLE_POWER_THRESHOLD_KW)
        if (
            isinstance(cutoff, bool)
            or not isinstance(cutoff, int | float)
            or not math.isfinite(cutoff)
            or cutoff < 0
        ):
            heater_id = heater.get("id")
            field = (
                f"water_heaters[{index}].idle_power_threshold_kw"
                if not heater_id
                else f"water_heaters[{index}].idle_power_threshold_kw ({heater_id})"
            )
            raise ValueError(f"{field} must be finite and non-negative (got {cutoff}).")


def _local_boundary(day: date, defer_hours: float, timezone: pytz.BaseTzInfo) -> datetime:
    seconds = round(defer_hours * 3600)
    naive = datetime.combine(day, time.min) + timedelta(seconds=seconds)
    try:
        return timezone.localize(naive, is_dst=None)
    except pytz.AmbiguousTimeError:
        # Use the first occurrence so both repeated wall-clock hours share one bucket.
        return timezone.localize(naive, is_dst=True)
    except pytz.NonExistentTimeError:
        # Move a skipped boundary to the first valid wall-clock instant.
        candidate = naive.replace(second=0, microsecond=0)
        while True:
            candidate += timedelta(minutes=1)
            try:
                return timezone.localize(candidate, is_dst=None)
            except pytz.NonExistentTimeError:
                continue


def water_quota_window(
    moment: datetime, defer_hours: object, timezone: pytz.BaseTzInfo
) -> tuple[datetime, datetime]:
    """Return the local-time quota bucket containing ``moment`` as aware bounds."""
    if (
        isinstance(defer_hours, bool)
        or not isinstance(defer_hours, int | float)
        or not math.isfinite(defer_hours)
        or not 0 <= defer_hours <= 23
    ):
        raise ValueError("defer_up_to_hours must be finite and within 0 to 23 hours")
    defer_value = float(defer_hours)
    local = timezone.localize(moment) if moment.tzinfo is None else moment.astimezone(timezone)
    today_start = _local_boundary(local.date(), defer_value, timezone)
    bucket_day = local.date() if local >= today_start else local.date() - timedelta(days=1)
    return (
        _local_boundary(bucket_day, defer_value, timezone),
        _local_boundary(bucket_day + timedelta(days=1), defer_value, timezone),
    )


def parse_water_heater_energy_metadata(raw: object) -> dict[str, Any] | None:
    """Return supported per-heater energy metadata, leaving malformed data unknown."""
    if not isinstance(raw, dict):
        return None
    metadata = cast("dict[str, Any]", raw)
    if (
        type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != WATER_HEATER_ENERGY_SCHEMA_VERSION
        or metadata.get("semantics") != WATER_HEATER_ENERGY_SEMANTICS
        or not isinstance(metadata.get("devices"), dict)
    ):
        return None

    devices: dict[str, dict[str, Any]] = {}
    raw_devices = cast("dict[object, object]", metadata["devices"])
    for raw_heater_id, raw_entry in raw_devices.items():
        if (
            not isinstance(raw_heater_id, str)
            or not raw_heater_id
            or not isinstance(raw_entry, dict)
        ):
            continue
        heater_id = raw_heater_id
        entry = cast("dict[str, Any]", raw_entry)
        energy = entry.get("energy_kwh")
        if energy is not None and (
            isinstance(energy, bool)
            or not isinstance(energy, int | float)
            or not math.isfinite(energy)
            or energy < 0
        ):
            continue
        cutoff = entry.get("idle_power_threshold_kw")
        if (
            isinstance(cutoff, bool)
            or not isinstance(cutoff, int | float)
            or not math.isfinite(cutoff)
            or cutoff < 0
        ):
            continue
        source = entry.get("source")
        if not isinstance(source, str) or source not in {
            "power_history",
            "snapshot",
            "unavailable",
        }:
            continue
        coverage = entry.get("coverage")
        complete = (
            (coverage == "complete" or coverage is True)
            and energy is not None
            and source != "unavailable"
        )
        devices[heater_id] = {
            "energy_kwh": float(energy) if energy is not None else None,
            "source": source,
            "idle_power_threshold_kw": float(cutoff),
            "coverage": complete,
        }
    return {"schema_version": 1, "semantics": WATER_HEATER_ENERGY_SEMANTICS, "devices": devices}


def water_component_recording(flags: dict[str, Any]) -> dict[str, Any] | None:
    """Validate water's own provenance even when unrelated measurements are unknown."""
    raw = metadata_object(flags.get("recording"))
    water = metadata_object(metadata_object(raw.get("components")).get("water"))
    effective = {
        key: water.get(key, raw.get(key))
        for key in ("schema_version", "semantics", "boundary_fingerprint", "algorithm")
    }
    effective.update(
        {"components": {"water": water}, "soc": {"source": "unavailable", "owner": "unknown"}}
    )
    return parse_recording({"recording": effective})
