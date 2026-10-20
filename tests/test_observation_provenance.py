from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from backend.observation_provenance import (
    RecordedObservation,
    calibration_eligible,
    observation_value_digest,
    trusted_row_provenance,
)
from backend.measurement_provenance import ENERGY_SEMANTICS


def trusted_flags() -> dict:
    return {
        "source": "recorder",
        "recording": {
            "schema_version": 1,
            "semantics": ENERGY_SEMANTICS,
            "boundary_fingerprint": "a" * 64,
            "algorithm": "power-history-step-zoh-v1",
            "components": {
                name: {"method": "power_history", "owner": "recorder"}
                for name in (
                    "import",
                    "export",
                    "pv",
                    "load",
                    "water",
                    "ev",
                    "battery_charge",
                    "battery_discharge",
                )
            },
            "soc": {"source": "live", "owner": "recorder"},
        },
    }


def recording(count: int = 1_200) -> list[RecordedObservation]:
    """Synthetic trusted rows with energy-balanced grid flows and consistent SoC."""
    start = datetime(2026, 9, 1, tzinfo=UTC)
    eta_out, eta_in = 0.94, 0.90
    eta_charge, eta_discharge = 0.92, 0.94
    state = 50.0
    capacity = 10.0
    flow_level = 0.6
    discharge_level = flow_level * eta_charge * eta_discharge
    rows = []
    for i in range(count):
        charging = i % 2 == 0
        charge, discharge = (flow_level, 0.0) if charging else (0.0, discharge_level)
        pv = 0.1 if charging else 0.4
        demand = 0.3 if charging else 0.7
        soc_start = state
        state += (eta_charge * charge - discharge / eta_discharge) / capacity * 100
        bus = pv + discharge - charge
        net = demand - (eta_out * bus if bus >= 0 else bus / eta_in)
        rows.append(
            RecordedObservation(
                start=start + i * timedelta(minutes=15),
                import_kwh=max(net, 0),
                export_kwh=max(-net, 0),
                import_price=-0.2 if i % 41 == 0 else 1.0 + i % 4 * 0.1,
                export_price=0.5,
                pv_kwh=pv,
                load_kwh=demand,
                water_kwh=0.0,
                ev_kwh=0.0,
                charge_kwh=charge,
                discharge_kwh=discharge,
                soc_start_percent=soc_start,
                soc_end_percent=state,
                quality_flags=trusted_flags(),
            )
        )
    return rows


@pytest.mark.parametrize("field", ["boundary_fingerprint", "semantics", "algorithm"])
def test_component_and_soc_identities_cannot_borrow_the_row_summary(field):
    row = recording(1)[0]
    for target in ("pv", "soc"):
        flags = trusted_flags()
        metadata = (
            flags["recording"]["soc"]
            if target == "soc"
            else flags["recording"]["components"][target]
        )
        metadata[field] = "unsupported-identity"
        assert trusted_row_provenance(replace(row, quality_flags=flags)) is None


def test_retained_cached_start_soc_is_not_certified_by_live_end_soc():
    row = recording(1)[0]
    flags = trusted_flags()
    flags["recording"]["soc"].update(
        {
            "start": {"source": "cached", "owner": "recorder"},
            "end": {"source": "live", "owner": "recorder"},
        }
    )
    row = replace(row, quality_flags=flags)
    assert trusted_row_provenance(row) is not None
    assert calibration_eligible(row)
    flags["recording"]["soc"]["end"] = {"source": "cached", "owner": "recorder"}
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is None
    assert not calibration_eligible(replace(row, quality_flags=flags))


def test_legacy_attestation_is_invalidated_by_manual_numeric_correction():
    row = recording(1)[0]
    attestation = {
        "schema_version": 1,
        "disposition": "verified_measured_energy",
        "semantics": ENERGY_SEMANTICS,
        "boundary_fingerprint": "a" * 64,
        "methods": dict.fromkeys(
            (
                "import",
                "export",
                "pv",
                "load",
                "water",
                "ev",
                "battery_charge",
                "battery_discharge",
            ),
            "cumulative_meter_energy",
        ),
        "soc_method": "live_soc_history",
        "evidence_digest": "b" * 64,
        "affected_measurement_digest": observation_value_digest(row),
    }
    flags = {
        "source": "recorder",
        "legacy_attestation": attestation,
        "comparison_history": {
            "schema_version": 1,
            "disposition": "verified_measured_energy",
            "evidence_digest": "b" * 64,
        },
    }
    row = replace(row, quality_flags=flags)
    assert trusted_row_provenance(row) is not None
    assert trusted_row_provenance(replace(row, pv_kwh=2)) is None


def test_disabled_zeros_qualify_but_enabled_unconfigured_zeros_do_not():
    row = recording(1)[0]
    flags = trusted_flags()
    flags["recording"]["components"]["ev"]["method"] = "disabled_zero"
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is not None
    flags["recording"]["components"]["ev"]["method"] = "unconfigured_zero"
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is None


@pytest.mark.parametrize(
    "target,value",
    [
        ("method", []),
        ("owner", {}),
        ("algorithm", []),
        ("boundary_fingerprint", {}),
        ("schema_version", True),
    ],
)
def test_malformed_provenance_values_are_unknown_without_crashing(target, value):
    row = recording(1)[0]
    flags = trusted_flags()
    if target in {"method", "owner"}:
        flags["recording"]["components"]["pv"][target] = value
    else:
        flags["recording"][target] = value
    assert trusted_row_provenance(replace(row, quality_flags=flags)) is None
    assert not calibration_eligible(replace(row, quality_flags=flags))
