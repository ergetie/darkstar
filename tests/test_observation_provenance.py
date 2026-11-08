from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
import pytz

from backend.learning.models import Base
from backend.learning.store import LearningStore
from backend.measurement_provenance import ENERGY_SEMANTICS
from backend.observation_provenance import (
    RecordedObservation,
    calibration_eligible,
    observation_value_digest,
    trusted_row_provenance,
)


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


# --- Recorder-owned unknown water provenance (store merge) ---------------------

_TZ = pytz.timezone("Europe/Stockholm")
_SLOT = _TZ.localize(datetime(2026, 11, 5, 9, 0))
_DEVICE_UNMEASURED = {
    "schema_version": 1,
    "semantics": "active-water-energy-v1",
    "devices": {
        "tank": {
            "energy_kwh": None,
            "source": "unavailable",
            "idle_power_threshold_kw": 0.1,
            "coverage": "unavailable",
        }
    },
}


def _water_flags(method: str, owner: str, source: str = "recorder") -> dict:
    flags = trusted_flags()
    flags["source"] = source
    flags["recording"]["components"]["water"] = {"method": method, "owner": owner}
    return flags


def _record(water_kwh, flags: dict, **extra) -> dict:
    return {
        "slot_start": _SLOT,
        "slot_end": _SLOT + timedelta(minutes=15),
        "import_kwh": 1.0,
        "export_kwh": 0.0,
        "pv_kwh": 0.0,
        "load_kwh": 1.0,
        "water_kwh": water_kwh,
        "ev_charging_kwh": 0.0,
        "quality_flags": flags,
        **extra,
    }


async def _new_store(tmp_path) -> LearningStore:
    store = LearningStore(str(tmp_path / "learning.db"), _TZ)
    async with store.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return store


def _water(flags: dict) -> dict:
    water = flags["recording"]["components"].get("water", {})
    return {key: water.get(key) for key in ("method", "owner")}


def _stored(tmp_path) -> tuple[float, dict]:
    with sqlite3.connect(tmp_path / "learning.db") as conn:
        value, flags = conn.execute(
            "SELECT water_kwh, quality_flags FROM slot_observations"
        ).fetchone()
    return value, json.loads(flags)


def _unavailable_flags() -> dict:
    flags = _water_flags("unknown", "recorder")
    flags["water_heater_energy"] = _DEVICE_UNMEASURED
    return flags


@pytest.mark.asyncio
async def test_unavailable_water_on_new_row_keeps_recorder_unknown(tmp_path):
    store = await _new_store(tmp_path)
    await store.store_slot_observations(pd.DataFrame([_record(None, _unavailable_flags())]))
    await store.close()
    value, flags = _stored(tmp_path)
    assert value == 0.0
    assert _water(flags) == {"method": "unknown", "owner": "recorder"}


@pytest.mark.parametrize("existing_water", [None, {"method": "unknown", "owner": "unknown"}])
@pytest.mark.asyncio
async def test_unavailable_water_on_existing_row_takes_recorder_owner(tmp_path, existing_water):
    store = await _new_store(tmp_path)
    old = trusted_flags()
    if existing_water is None:
        del old["recording"]["components"]["water"]
    else:
        old["recording"]["components"]["water"] = existing_water
    await store.store_slot_observations(pd.DataFrame([_record(None, old)]), authoritative=False)
    await store.store_slot_observations(pd.DataFrame([_record(None, _unavailable_flags())]))
    await store.close()
    value, flags = _stored(tmp_path)
    assert value == 0.0
    assert _water(flags) == {"method": "unknown", "owner": "recorder"}


@pytest.mark.asyncio
async def test_measured_water_is_never_downgraded_by_unavailable_write(tmp_path):
    store = await _new_store(tmp_path)
    await store.store_slot_observations(
        pd.DataFrame([_record(0.4, _water_flags("power_history", "recorder"))])
    )
    await store.store_slot_observations(pd.DataFrame([_record(None, _unavailable_flags())]))
    await store.close()
    value, flags = _stored(tmp_path)
    assert value == 0.4
    assert _water(flags) == {"method": "power_history", "owner": "recorder"}


@pytest.mark.asyncio
async def test_backfill_cannot_overwrite_recorder_owned_water(tmp_path):
    store = await _new_store(tmp_path)
    await store.store_slot_observations(
        pd.DataFrame([_record(0.4, _water_flags("power_history", "recorder"))])
    )
    await store.store_slot_observations(
        pd.DataFrame([_record(0.9, _water_flags("power_history", "backfill", "backfill"))]),
        authoritative=False,
    )
    # Backfill must not claim recorder ownership of an unknown water component either.
    await store.store_slot_observations(
        pd.DataFrame([_record(None, _unavailable_flags())]), authoritative=False
    )
    await store.close()
    value, flags = _stored(tmp_path)
    assert value == 0.4
    assert _water(flags) == {"method": "power_history", "owner": "recorder"}


@pytest.mark.asyncio
async def test_non_authoritative_unknown_water_does_not_become_recorder_owned(tmp_path):
    store = await _new_store(tmp_path)
    await store.store_slot_observations(
        pd.DataFrame([_record(None, _unavailable_flags())]), authoritative=False
    )
    await store.close()
    _, flags = _stored(tmp_path)
    assert _water(flags)["owner"] != "recorder"


@pytest.mark.asyncio
async def test_unmeasured_water_per_device_metadata_is_stored_and_readable(tmp_path):
    store = await _new_store(tmp_path)
    await store.store_slot_observations(pd.DataFrame([_record(None, _unavailable_flags())]))
    rows = await store.get_water_heater_energy_range(
        _SLOT - timedelta(hours=1), _SLOT + timedelta(hours=1)
    )
    await store.close()
    _, flags = _stored(tmp_path)
    device = flags["water_heater_energy"]["devices"]["tank"]
    assert device["energy_kwh"] is None
    assert device["coverage"] is False
    assert rows[0]["energy"]["tank"]["energy_kwh"] is None
    assert rows[0]["coverage"] == "unknown"
