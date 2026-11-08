"""compute_slot_energy (shared by the recorder and backfill) ends holds at unavailable states."""

from datetime import datetime, timedelta

import pytest
import pytz

from backend.core.ha_client import parse_power_states
from backend.core.slot_energy import SlotEnergySources, compute_slot_energy

BASE = datetime(2026, 11, 5, 8, 0, tzinfo=pytz.UTC)
SLOT = timedelta(minutes=15)


def _states(points: list[tuple[float, str]]) -> list[dict]:
    return [
        {
            "state": state,
            "last_changed": (BASE + timedelta(seconds=sec)).isoformat(),
            "attributes": {"unit_of_measurement": "kW"},
        }
        for sec, state in points
    ]


SOURCES = SlotEnergySources(
    meter_type="net",
    pv=None,
    load="sensor.load",
    grid=None,
    grid_import=None,
    grid_export=None,
    battery=None,
    grid_inverted=False,
    battery_inverted=False,
    ev_chargers=(),
    water_heaters=(("tank", "sensor.wh"),),
)


def test_long_history_chunk_water_slots_follow_the_gap_not_the_stale_value():
    """Backfill-style series spanning many slots: 2 kW until 26 s, unavailable until slot 3."""
    series = {
        "sensor.load": parse_power_states(_states([(0, "3.0")])),
        "sensor.wh": parse_power_states(
            _states([(0, "2.0"), (26, "unavailable"), (2 * 900 + 300, "2.0")])
        ),
    }
    first = compute_slot_energy(SOURCES, series, BASE, BASE + SLOT)
    middle = compute_slot_energy(SOURCES, series, BASE + SLOT, BASE + 2 * SLOT)
    last = compute_slot_energy(SOURCES, series, BASE + 2 * SLOT, BASE + 3 * SLOT)

    assert first.water["sensor.wh"] == pytest.approx(2.0 * 26 / 3600)
    assert middle.water["sensor.wh"] is None  # unknown, not a held 2 kW and not a measured 0
    assert last.water["sensor.wh"] == pytest.approx(2.0 * 600 / 3600)
    assert first.load == pytest.approx(0.75)


def _backfill_engine():
    from backend.learning.backfill import BackfillEngine

    engine = object.__new__(BackfillEngine)
    engine.config = {
        "system": {"has_solar": False, "has_battery": False, "has_water_heater": True},
        "input_sensors": {"load_power": "sensor.load"},
        "water_heaters": [{"id": "tank", "sensor": "sensor.wh", "enabled": True}],
    }
    engine.timezone = pytz.UTC
    return engine


def test_backfill_fully_unavailable_water_day_is_truthful_unknown_not_a_crash():
    """Every state unavailable for the window: unknown provenance, 0.0 stored, no exception."""
    engine = _backfill_engine()
    history = {
        "sensor.load": _states([(0, "3.0")]),
        "sensor.wh": _states([(0, "unavailable")]),
    }
    records = engine.integrate_slots(SOURCES, None, history, [BASE, BASE + SLOT])
    assert len(records) == 2
    for record in records:
        assert record["water_kwh"] == 0.0
        assert record["water_heater_energy"] is None
        components = record["quality_flags"]["recording"]["components"]
        assert components["water"]["method"] == "unknown"
        assert components["load"]["method"] == "mixed"
        device = record["quality_flags"]["water_heater_energy"]["devices"]["tank"]
        assert device["energy_kwh"] is None
        assert device["coverage"] == "unavailable"


def test_backfill_writes_nothing_when_every_sensor_is_unavailable():
    """No valid interval for any metric: no row, so no fabricated 0 reaches NOT NULL columns."""
    engine = _backfill_engine()
    history = {
        "sensor.load": _states([(0, "unavailable")]),
        "sensor.wh": _states([(0, "unavailable")]),
    }
    assert engine.integrate_slots(SOURCES, None, history, [BASE, BASE + SLOT]) == []


def test_backfill_skips_slots_whose_load_has_no_valid_interval():
    """Water has data but the load sensor is unavailable: load would be stored as 0, so skip."""
    engine = _backfill_engine()
    history = {"sensor.load": _states([(0, "unavailable")]), "sensor.wh": _states([(0, "2.0")])}
    assert engine.integrate_slots(SOURCES, None, history, [BASE]) == []


def test_backfill_partial_day_writes_only_slots_with_measured_core_data():
    """Load unavailable for the first two slots, valid afterwards: only measured slots are written."""
    engine = _backfill_engine()
    history = {
        "sensor.load": _states([(0, "unavailable"), (2 * 900, "3.0")]),
        "sensor.wh": _states([(0, "0.0")]),
    }
    slots = [BASE + i * SLOT for i in range(4)]
    records = engine.integrate_slots(SOURCES, None, history, slots)
    assert [record["slot_start"] for record in records] == slots[2:]
    for record in records:
        assert record["load_kwh"] == pytest.approx(0.75)
        for field in ("pv_kwh", "load_kwh", "import_kwh", "export_kwh"):
            assert record[field] is not None


def test_backfill_skips_slot_when_configured_pv_has_no_valid_interval():
    """Load measured but a configured PV sensor is in a gap: pv_kwh would become a fake 0."""
    engine = _backfill_engine()
    engine.config["system"]["has_solar"] = True
    engine.config["input_sensors"]["pv_power"] = "sensor.pv"
    sources = SlotEnergySources(**{**SOURCES.__dict__, "pv": "sensor.pv"})
    history = {
        "sensor.load": _states([(0, "3.0")]),
        "sensor.pv": _states([(0, "unavailable"), (900, "1.0")]),
        "sensor.wh": _states([(0, "0.0")]),
    }
    records = engine.integrate_slots(sources, None, history, [BASE, BASE + SLOT])
    assert [record["slot_start"] for record in records] == [BASE + SLOT]
    assert records[0]["pv_kwh"] == pytest.approx(0.25)
