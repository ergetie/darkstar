"""Sensor validation utilities for detecting and handling unreasonable sensor values.

This module provides functions to validate energy sensor values against physically
reasonable limits derived from the system configuration.
"""

import copy
import logging
from typing import Any

from backend.measurement_provenance import metadata_object

logger = logging.getLogger("darkstar.validation")


def get_max_energy_per_slot(config: dict[str, Any]) -> float:
    """Calculate maximum reasonable energy per slot from grid power configuration.

    The threshold is calculated as:
        max_kwh_per_slot = grid.max_power_kw * 0.25h * 2.0

    The 2.0x safety factor accounts for:
    - Simultaneous import + PV production
    - Short transients
    - Measurement noise

    Args:
        config: Application configuration dictionary

    Returns:
        Maximum energy in kWh allowed per 15-minute slot

    Raises:
        ValueError: If system.grid.max_power_kw is not configured
    """
    grid_config = config.get("system", {}).get("grid", {})
    max_power_kw = grid_config.get("max_power_kw")

    if max_power_kw is None:
        raise ValueError(
            "Missing required configuration: system.grid.max_power_kw. "
            "This value is required to calculate energy validation thresholds."
        )

    # 0.25 hours = 15 minutes (slot duration)
    # 2.0x safety factor for simultaneous import + PV + transients
    max_kwh = float(max_power_kw) * 0.25 * 2.0

    return max_kwh


def validate_energy_values(record: dict[str, Any], max_kwh: float) -> dict[str, Any]:
    """Validate and sanitize energy values in a record.

    Values exceeding the maximum threshold are set to 0.0 and logged as warnings.
    This signals "unknown/unreliable" data rather than pretending we know the value.

    Args:
        record: Dictionary containing energy values to validate
        max_kwh: Maximum allowed energy value in kWh per slot

    Returns:
        The record with validated (and possibly zeroed) energy values
    """
    # Energy fields that should be validated
    energy_fields = [
        "pv_kwh",
        "load_kwh",
        "import_kwh",
        "export_kwh",
        "water_kwh",
        "ev_charging_kwh",
        "batt_charge_kwh",
        "batt_discharge_kwh",
    ]

    validated_record = record.copy()

    for field in energy_fields:
        if field not in validated_record:
            continue

        value = validated_record[field]

        # Skip None values
        if value is None:
            continue

        try:
            value_float = float(value)
        except (TypeError, ValueError):
            logger.warning(f"Invalid {field} value (non-numeric): {value}. Setting to 0.0")
            validated_record[field] = 0.0
            continue

        # Check for NaN or Inf
        import math

        if math.isnan(value_float) or math.isinf(value_float):
            logger.warning(f"Invalid {field} value (NaN/Inf): {value}. Setting to 0.0")
            validated_record[field] = 0.0
            continue

        # Check against threshold
        if value_float > max_kwh:
            logger.warning(
                f"Spike detected in {field}: {value_float:.3f} kWh exceeds "
                f"threshold {max_kwh:.3f} kWh. Setting to 0.0"
            )
            validated_record[field] = 0.0

    if "water_kwh" in record and record["water_kwh"] != validated_record.get("water_kwh"):
        flags = copy.deepcopy(metadata_object(record.get("quality_flags")))
        recording = metadata_object(flags.get("recording"))
        component = metadata_object(metadata_object(recording.get("components")).get("water"))
        if component:
            component["method"] = "unknown"
        devices = metadata_object(metadata_object(flags.get("water_heater_energy")).get("devices"))
        for entry in devices.values():
            device_metadata = metadata_object(entry)
            if device_metadata:
                device_metadata.update(
                    energy_kwh=None, source="unavailable", coverage="unavailable"
                )
        validated_record["water_heater_energy"] = None
        validated_record["quality_flags"] = flags
    return validated_record
