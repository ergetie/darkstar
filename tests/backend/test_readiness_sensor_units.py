"""Readiness reports power sensors that need a W or kW choice (sensor-unit-overrides)."""

import copy
from unittest.mock import AsyncMock, patch

import pytest

from backend.core import readiness
from backend.core.secrets import load_yaml


@pytest.fixture
def config():
    cfg = copy.deepcopy(load_yaml("config.default.yaml"))
    cfg["system"].update(
        has_battery=False,
        has_solar=True,
        has_water_heater=False,
        has_ev_charger=False,
        grid_meter_type="net",
    )
    cfg["system"]["location"].update(latitude=59.3, longitude=18.0)
    cfg["input_sensors"].update(
        {"pv_power": "sensor.pv", "load_power": "sensor.load", "grid_power": "sensor.grid"}
    )
    return cfg


def entity(eid, state="500", unit=None):
    return {
        "entity_id": eid,
        "domain": "sensor",
        "state": state,
        "unit_of_measurement": unit,
    }


async def readiness_with(config, states):
    with (
        patch(
            "backend.core.readiness.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "t"},
        ),
        patch("backend.health.HealthChecker.check_ha_connection", new=AsyncMock(return_value=[])),
        patch(
            "backend.core.readiness.discover_entities",
            new=AsyncMock(return_value={"entities": states}),
        ),
        patch("backend.core.prices.get_nordpool_data", new=AsyncMock(return_value=[{}])),
        patch("backend.core.readiness.run_isolated_plan", new=AsyncMock(return_value=3)),
    ):
        return await readiness.check_readiness(config)


def check(result, check_id):
    return next(c for c in result["checks"] if c["id"] == check_id)


@pytest.mark.asyncio
async def test_unitless_sensor_is_listed_and_warns_with_action(config):
    states = [
        entity("sensor.pv"),
        entity("sensor.load", unit="W"),
        entity("sensor.grid", unit="kW"),
    ]
    result = await readiness_with(config, states)
    assert result["unit_needed"] == [
        {
            "entity_id": "sensor.pv",
            "settings_path": "input_sensors.pv_power",
            "live_value": 500.0,
            "override": None,
        }
    ]
    pv = check(result, "pv_power")
    assert pv["status"] == "warn"
    assert pv["message"] == (
        "pv_power: no unit reported by Home Assistant. Choose W or kW for this sensor."
    )
    assert pv["action"] == {
        "kind": "set_sensor_unit",
        "entity_id": "sensor.pv",
        "path": "input_sensors.pv_power",
    }
    assert check(result, "load_power")["status"] == "pass"
    assert "action" not in check(result, "load_power")
    assert result["ready"]


@pytest.mark.asyncio
async def test_override_passes_and_notes_the_manual_unit(config):
    config["sensor_unit_overrides"] = {"sensor.pv": "W"}
    states = [entity("sensor.pv"), entity("sensor.load", unit="W"), entity("sensor.grid", unit="W")]
    result = await readiness_with(config, states)
    # Still listed so the UI keeps the selector, but with its override and no warning.
    assert result["unit_needed"] == [
        {
            "entity_id": "sensor.pv",
            "settings_path": "input_sensors.pv_power",
            "live_value": 500.0,
            "override": "W",
        }
    ]
    pv = check(result, "pv_power")
    assert pv["status"] == "pass"
    assert "action" not in pv
    assert "W (set manually)" in pv["message"]


@pytest.mark.asyncio
async def test_reported_unit_wins_over_override(config):
    config["sensor_unit_overrides"] = {"sensor.pv": "W"}
    states = [
        entity("sensor.pv", unit="kW"),
        entity("sensor.load", unit="W"),
        entity("sensor.grid", unit="W"),
    ]
    pv = check(await readiness_with(config, states), "pv_power")
    assert pv["status"] == "pass"
    assert "manually" not in pv["message"]


@pytest.mark.asyncio
async def test_other_unknown_unit_keeps_the_plain_warning(config):
    states = [
        entity("sensor.pv", unit="kWh"),
        entity("sensor.load", unit="W"),
        entity("sensor.grid", unit="W"),
    ]
    result = await readiness_with(config, states)
    pv = check(result, "pv_power")
    assert pv["status"] == "warn"
    assert "action" not in pv
    assert result["unit_needed"] == []


@pytest.mark.asyncio
async def test_device_and_load_sensors_are_checked_too(config):
    config["system"].update(has_water_heater=True, has_ev_charger=True)
    config["water_heaters"] = [
        {"id": "wh", "enabled": True, "sensor": "sensor.wh", "target_entity": "switch.wh"}
    ]
    config["ev_chargers"] = [
        {"id": "ev", "enabled": True, "sensor": "sensor.ev", "switch_entity": "switch.ev"}
    ]
    config["load_balancing"]["loads"] = [
        {"device_type": "custom_entity", "device_id": "x", "power_sensor": "sensor.shed"}
    ]
    config["sensor_unit_overrides"] = {"sensor.ev": "kW"}
    states = [
        entity("sensor.pv", unit="W"),
        entity("sensor.load", unit="W"),
        entity("sensor.grid", unit="W"),
        entity("sensor.wh"),
        entity("sensor.ev"),
        entity("sensor.shed"),
        entity("switch.wh", state="on"),
        entity("switch.ev", state="on"),
    ]
    result = await readiness_with(config, states)
    assert {n["settings_path"] for n in result["unit_needed"] if n["override"] is None} == {
        "water_heaters.0.sensor",
        "load_balancing.loads.0.power_sensor",
    }
    assert {n["settings_path"] for n in result["unit_needed"] if n["override"]} == {
        "ev_chargers.0.sensor"
    }
    assert check(result, "water_heater_0_sensor")["status"] == "warn"
    assert check(result, "water_heater_0_sensor")["action"]["kind"] == "set_sensor_unit"
    ev = check(result, "ev_0_sensor")
    assert ev["status"] == "pass"
    assert "kW (set manually)" in ev["message"]
    load = check(result, "unit_load_balancing.loads.0.power_sensor")
    assert load["status"] == "warn"
    assert load["action"]["entity_id"] == "sensor.shed"
