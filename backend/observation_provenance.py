"""Recorded-observation provenance and calibration-eligibility helpers.

All energy values use the installation's recorded sensor boundary. This module has
no database, configuration, or async dependencies so its rules can be tested
independently from the API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.measurement_provenance import (
    ENERGY_SEMANTICS,
    MEASUREMENT_METHODS,
    is_sha256,
    measurement_value_digest,
    metadata_object,
    parse_quality_flags,
    parse_recording,
    soc_metadata,
)

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class RecordedObservation:
    start: datetime
    import_kwh: float | None
    export_kwh: float | None
    import_price: float | None
    export_price: float | None
    pv_kwh: float | None
    load_kwh: float | None
    water_kwh: float | None
    ev_kwh: float | None
    charge_kwh: float | None
    discharge_kwh: float | None
    soc_start_percent: float | None
    soc_end_percent: float | None
    quality_flags: str | dict[str, Any] | None = None

    @property
    def demand_kwh(self) -> float | None:
        values = (self.load_kwh, self.water_kwh, self.ev_kwh)
        if any(value is None for value in values):
            return None
        return sum(float(value) for value in values if value is not None)


def _finite_nonnegative(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value >= 0


def _finite_price(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _valid_soc(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and 0 <= value <= 100


def _flags(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    return parse_quality_flags(raw)


def calibration_eligible(row: RecordedObservation) -> bool:
    flags = _flags(row.quality_flags)
    if flags.get("exclude") is True or flags.get("source") == "backfill":
        return False
    if trusted_row_provenance(row) is None:
        return False
    energies = (
        row.import_kwh,
        row.export_kwh,
        row.pv_kwh,
        row.load_kwh,
        row.water_kwh,
        row.ev_kwh,
        row.charge_kwh,
        row.discharge_kwh,
    )
    if not all(_finite_nonnegative(v) for v in energies) or not (
        _finite_price(row.import_price) and _finite_price(row.export_price)
    ):
        return False
    # Historical recorder rows commonly lack slot-start SoC; contiguous end-SoC
    # pairs still identify battery factors. Validate start SoC when it exists.
    if (
        row.soc_start_percent is not None and not _valid_soc(row.soc_start_percent)
    ) or not _valid_soc(row.soc_end_percent):
        return False
    return row.start.tzinfo is not None


_REQUIRED_COMPONENTS = (
    "import",
    "export",
    "pv",
    "load",
    "water",
    "ev",
    "battery_charge",
    "battery_discharge",
)
_LEGACY_METHODS = {"cumulative_meter_energy", "power_history_energy"}
_ENERGY_COMPATIBILITY_REGISTRY = {
    "observed_algorithm": {
        # Recorder integration is zero-order hold over each 15-minute slot.
        "power-history-step-zoh-v1": "full-slot-measured-energy-v1",
    },
    "legacy_method": {
        # These are accepted only when a reviewed interval attestation also
        # establishes the same boundary, slot semantics, and live-SoC history.
        "cumulative_meter_energy": "full-slot-measured-energy-v1",
        "power_history_energy": "full-slot-measured-energy-v1",
    },
}
_OBSERVED_ALGORITHMS = _ENERGY_COMPATIBILITY_REGISTRY["observed_algorithm"]
_LEGACY_COMPATIBILITY = _ENERGY_COMPATIBILITY_REGISTRY["legacy_method"]


def _measured_energy_cohort(boundary: str, semantics: str) -> str:
    """Identity for the single explicitly registered full-slot compatibility class."""
    compatibility_class = "full-slot-measured-energy-v1"
    return f"measured:{boundary}:{semantics}:{compatibility_class}:compat-v1"


def trusted_row_provenance(
    row: RecordedObservation, expected_boundary: str | None = None
) -> tuple[str, str, str] | None:
    """Return (cohort id, boundary, source class) only for explicit trusted evidence."""
    flags = _flags(row.quality_flags)
    if flags.get("exclude") is True or flags.get("source") == "backfill":
        return None
    comparison_history = metadata_object(flags.get("comparison_history"))
    if comparison_history.get("disposition") == "exclude_from_comparison":
        return None
    recording = parse_recording(flags)
    if recording is not None:
        boundary = str(recording["boundary_fingerprint"])
        if boundary == "mixed" or (expected_boundary and boundary != expected_boundary):
            return None
        components = recording["components"]
        for component in _REQUIRED_COMPONENTS:
            item = metadata_object(components.get(component))
            if item.get("owner") != "recorder":
                return None
            if item.get("schema_version", recording["schema_version"]) != 1:
                return None
            if item.get("method") not in MEASUREMENT_METHODS:
                return None
            if item.get("boundary_fingerprint", boundary) != boundary:
                return None
            if item.get("semantics", ENERGY_SEMANTICS) != ENERGY_SEMANTICS:
                return None
            if (
                not isinstance(item.get("algorithm", recording.get("algorithm")), str)
                or item.get("algorithm", recording.get("algorithm")) not in _OBSERVED_ALGORITHMS
            ):
                return None
            if item.get("method") in {"snapshot", "mixed", "unconfigured_zero", "unknown"}:
                return None
        soc = soc_metadata(recording, "end")
        if soc.get("owner") != "recorder" or soc.get("source") != "live":
            return None
        if (
            soc.get("schema_version", recording["schema_version"]) != 1
            or soc.get("boundary_fingerprint", boundary) != boundary
            or soc.get("semantics", ENERGY_SEMANTICS) != ENERGY_SEMANTICS
            or not isinstance(soc.get("algorithm", recording.get("algorithm")), str)
            or soc.get("algorithm", recording.get("algorithm")) not in _OBSERVED_ALGORITHMS
        ):
            return None
        algorithm = str(recording.get("algorithm", ""))
        if algorithm not in _OBSERVED_ALGORITHMS or recording.get("semantics") != ENERGY_SEMANTICS:
            return None
        return _measured_energy_cohort(boundary, recording["semantics"]), boundary, "observed"

    # A malformed or unsupported observed-provenance object is never downgraded
    # into legacy history by attaching a separate attestation.
    if "recording" in flags:
        return None

    attestation = metadata_object(flags.get("legacy_attestation"))
    if type(attestation.get("schema_version")) is not int or attestation.get("schema_version") != 1:
        return None
    if attestation.get("disposition") != "verified_measured_energy":
        return None
    if (
        comparison_history.get("schema_version") != 1
        or comparison_history.get("disposition") != "verified_measured_energy"
        or comparison_history.get("evidence_digest") != attestation.get("evidence_digest")
    ):
        return None
    if attestation.get("semantics") != ENERGY_SEMANTICS:
        return None
    boundary = attestation.get("boundary_fingerprint")
    evidence = attestation.get("evidence_digest")
    methods = metadata_object(attestation.get("methods"))
    soc_method = attestation.get("soc_method")
    if not isinstance(boundary, str) or not is_sha256(boundary) or not is_sha256(evidence):
        return None
    if expected_boundary and boundary != expected_boundary:
        return None
    if set(methods) != set(_REQUIRED_COMPONENTS) or any(
        not isinstance(methods.get(name), str) or methods.get(name) not in _LEGACY_METHODS
        for name in _REQUIRED_COMPONENTS
    ):
        return None
    if soc_method != "live_soc_history":
        return None
    compatibility_classes = {_LEGACY_COMPATIBILITY.get(method) for method in methods.values()}
    if compatibility_classes != {"full-slot-measured-energy-v1"}:
        return None
    try:
        value_digest = observation_value_digest(row)
    except (ValueError, TypeError):
        return None
    if attestation.get("affected_measurement_digest") != value_digest:
        return None
    cohort = _measured_energy_cohort(boundary, attestation["semantics"])
    return cohort, boundary, "attested"


def observation_value_digest(row: RecordedObservation) -> str:
    return measurement_value_digest(
        (
            row.start,
            row.import_kwh,
            row.export_kwh,
            row.pv_kwh,
            row.load_kwh,
            row.water_kwh,
            row.ev_kwh,
            row.charge_kwh,
            row.discharge_kwh,
            row.soc_start_percent,
            row.soc_end_percent,
            row.import_price,
            row.export_price,
        )
    )
