"""Unit tests for planner/battery_limits.py."""

from __future__ import annotations

import pytest

from planner.battery_limits import resolve_battery_power_limits, resolve_control_unit


def test_amps_mode():
    config = {
        "executor": {"inverter": {"control_unit": "A"}},
        "battery": {"max_charge_a": 100, "max_discharge_a": 50, "max_charge_w": 9999},
    }
    assert resolve_battery_power_limits(config) == pytest.approx((4.8, 2.4))


def test_watts_mode():
    config = {
        "executor": {"inverter": {"control_unit": "W"}},
        "battery": {"max_charge_w": 5000, "max_discharge_w": 4000, "max_charge_a": 999},
    }
    assert resolve_battery_power_limits(config) == (5.0, 4.0)


def test_default_unit_is_amps():
    config = {"battery": {"max_charge_a": 100, "max_charge_w": 5000}}
    assert resolve_battery_power_limits(config)[0] == pytest.approx(4.8)


def test_missing_keys_give_zero():
    assert resolve_battery_power_limits({}) == (0.0, 0.0)
    assert resolve_battery_power_limits({"executor": {"inverter": {"control_unit": "W"}}}) == (
        0.0,
        0.0,
    )


def test_voltage_default_and_system_voltage_fallback():
    assert resolve_battery_power_limits({"battery": {"max_charge_a": 100}})[0] == pytest.approx(4.8)
    config = {"battery": {"max_charge_a": 100, "system_voltage_v": 51.2}}
    assert resolve_battery_power_limits(config)[0] == pytest.approx(5.12)
    config["battery"]["nominal_voltage_v"] = 100
    assert resolve_battery_power_limits(config)[0] == pytest.approx(10.0)


def test_system_battery_block_preferred_over_top_level():
    config = {
        "system": {"battery": {"max_charge_a": 100}},
        "battery": {"max_charge_a": 200},
    }
    assert resolve_battery_power_limits(config)[0] == pytest.approx(4.8)
    assert resolve_battery_power_limits({"battery": {"max_charge_a": 200}})[0] == pytest.approx(9.6)


def test_resolve_control_unit_defaults():
    assert resolve_control_unit({}) == "A"
    assert resolve_control_unit({"executor": {"inverter": {"control_unit": "W"}}}) == "W"
    assert resolve_control_unit({"executor": {"inverter": {"control_unit": "A"}}}) == "A"
    assert resolve_control_unit({"executor": {"inverter": {"control_unit": "x"}}}) == "A"
