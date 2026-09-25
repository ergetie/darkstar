"""Tests for EV register-as-disabled behavior."""
import pytest

from backend.loads.base import DeferrableLoad, LoadType
from backend.loads.service import LoadDisaggregator


def _base_config(ev_chargers: list[dict]) -> dict:
    return {
        "config_version": 2,
        "system": {"has_ev_charger": True, "has_battery": True},
        "battery": {"capacity_kwh": 10.0},
        "ev_chargers": ev_chargers,
        "water_heaters": [],
        "input_sensors": {},
    }


def test_ev_missing_power_registers_disabled():
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "rated_power_kw": 0.0, "type": "binary"},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason == "missing_rated_power"


def test_ev_zero_power_registers_disabled():
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "rated_power_kw": 0, "type": "binary"},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason == "missing_rated_power"


def test_ev_valid_power_registers_normally():
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "rated_power_kw": 11.0, "type": "binary"},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason is None
    assert load.nominal_power_kw == 11.0


def test_adapter_excludes_disabled_chargers():
    from planner.solver.adapter import build_ev_charger_inputs

    ev_config = [
        {"id": "ev1", "enabled": True, "rated_power_kw": 11.0, "battery_capacity_kwh": 60.0,
         "disabled_reason": None},
        {"id": "ev2", "enabled": True, "rated_power_kw": 0.0, "battery_capacity_kwh": 60.0,
         "disabled_reason": "missing_power_kw"},
    ]

    inputs = build_ev_charger_inputs(ev_config, [
        {"id": "ev1", "soc_percent": 50.0, "plugged_in": True},
        {"id": "ev2", "soc_percent": 50.0, "plugged_in": True},
    ])

    charger_ids = [c.id for c in inputs]
    assert "ev1" in charger_ids
    assert "ev2" not in charger_ids


def test_fixing_config_re_registers_without_disabled():
    """After re-initialization with valid config, disabled_reason is cleared."""
    # First: invalid config
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "rated_power_kw": 0.0, "type": "binary"},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load.disabled_reason == "missing_rated_power"

    # Fix config and re-initialize
    config["ev_chargers"][0]["rated_power_kw"] = 11.0

    disagg2 = LoadDisaggregator(config)
    load2 = disagg2.get_load_by_id("ev1")
    assert load2 is not None
    assert load2.disabled_reason is None


def test_current_charger_missing_max_current_registers_disabled():
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "type": "current", "min_current_a": 6, "phases": [1, 2, 3]},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason == "missing_max_current"


def test_current_charger_missing_phases_registers_disabled():
    config = _base_config([
        {"id": "ev1", "name": "Garage", "enabled": True, "sensor": "sensor.ev_power",
         "type": "current", "min_current_a": 6, "max_current_a": 12},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason == "missing_phases"


def test_disabled_reason_message_uses_charger_name():
    from backend.core.ev_power import charger_disabled_reason

    assert charger_disabled_reason(
        {"id": "ev1", "name": "Garage", "type": "current", "max_current_a": 12}, 230.0
    ) == ("missing_phases", "Configure phases for Garage to enable planning")
    assert charger_disabled_reason(
        {"id": "ev1", "type": "current", "max_current_a": 12, "phases": []}, 230.0
    ) == ("missing_phases", "Configure phases for ev1 to enable planning")
    assert charger_disabled_reason(
        {"id": "ev1", "name": "Garage", "type": "current", "max_current_a": 12, "phases": [1]},
        230.0,
    ) is None


def test_current_charger_derived_power_registers_normally():
    config = _base_config([
        {"id": "ev1", "name": "EV", "enabled": True, "sensor": "sensor.ev_power",
         "type": "current", "min_current_a": 6, "max_current_a": 10, "phases": [1, 2, 3]},
    ])
    disagg = LoadDisaggregator(config)
    load = disagg.get_load_by_id("ev1")
    assert load is not None
    assert load.disabled_reason is None
    assert load.nominal_power_kw == pytest.approx(6.9)
