"""Every power reading is converted to kW through the shared unit resolver."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytz

from backend.api.routers import system as system_router
from backend.core import ha_client
from backend.core.water_progress import _history_energy
from backend.ha_socket import HAWebSocketClient
from backend.loads.service import LoadDisaggregator


@pytest.fixture(autouse=True)
def _fresh_warnings():
    ha_client._unitless_warned.clear()
    yield
    ha_client._unitless_warned.clear()


def with_overrides(overrides):
    return patch.object(ha_client, "get_sensor_unit_overrides", return_value=overrides)


# --- ha_socket (2.11) ---------------------------------------------------------------


CONFIG = {
    "input_sensors": {"pv_power": "sensor.pv", "grid_power": "sensor.grid"},
    "system": {"grid_meter_type": "net", "has_ev_charger": True},
    "ev_chargers": [{"id": "ev1", "enabled": True, "sensor": "sensor.ev"}],
    "water_heaters": [{"id": "wh1", "enabled": True, "name": "Tank", "sensor": "sensor.wh"}],
}


def socket_client():
    with (
        patch(
            "backend.ha_socket.load_home_assistant_config",
            return_value={"url": "http://ha.local", "token": "token"},
        ),
        patch("backend.ha_socket.load_yaml", return_value=CONFIG),
    ):
        return HAWebSocketClient()


def emitted(entity_id, value, unit, overrides=None):
    client = socket_client()
    state = {"state": str(value), "attributes": {"unit_of_measurement": unit} if unit else {}}
    with (
        with_overrides(overrides or {}),
        patch("backend.events.emit_live_metrics") as emit,
    ):
        client._handle_state_change(entity_id, state)
    return emit.call_args.args[0]


@pytest.mark.parametrize(
    ("value", "unit", "overrides", "expected"),
    [
        (1500, "W", None, 1.5),
        (1.5, "kW", None, 1.5),
        (0.002, "MW", None, 2.0),
        (1500, None, None, 1500.0),
        (1500, None, {"sensor.pv": "W"}, 1.5),
        (1500, "kW", {"sensor.pv": "W"}, 1500.0),
    ],
)
def test_input_sensor_units(value, unit, overrides, expected):
    assert emitted("sensor.pv", value, unit, overrides)["pv_kw"] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("entity", "metric", "unit", "overrides", "expected"),
    [
        ("sensor.ev", "ev_chargers", "W", None, 7.2),
        ("sensor.ev", "ev_chargers", None, {"sensor.ev": "W"}, 7.2),
        ("sensor.ev", "ev_chargers", "kW", None, 7200.0),
        ("sensor.wh", "water_heaters", "W", None, 7.2),
        ("sensor.wh", "water_heaters", "MW", None, 7_200_000.0),
        ("sensor.wh", "water_heaters", None, {"sensor.wh": "W"}, 7.2),
        ("sensor.wh", "water_heaters", None, None, 7200.0),
    ],
)
def test_device_sensor_units(entity, metric, unit, overrides, expected):
    payload = emitted(entity, 7200, unit, overrides)
    assert payload[metric][0]["kw"] == pytest.approx(expected)


# --- system status (2.12) -----------------------------------------------------------


@pytest.mark.asyncio
async def test_status_converts_a_7200_w_ev_sensor_to_7_2_kw(monkeypatch):
    config = {
        "system": {"has_ev_charger": True},
        "input_sensors": {},
        "ev_chargers": [{"id": "ev1", "enabled": True, "name": "EV", "sensor": "sensor.ev"}],
    }
    monkeypatch.setattr(system_router, "load_yaml", lambda _path: config)
    state = {"state": "7200", "attributes": {"unit_of_measurement": "W"}}
    with (
        with_overrides({}),
        patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=state)),
    ):
        status = await system_router.get_system_status()
    assert status.ev_kw == pytest.approx(7.2)
    assert status.ev_chargers[0]["kw"] == pytest.approx(7.2)


@pytest.mark.asyncio
async def test_status_uses_the_override_for_a_unitless_ev_sensor(monkeypatch):
    config = {
        "system": {"has_ev_charger": True},
        "input_sensors": {},
        "ev_chargers": [{"id": "ev1", "enabled": True, "name": "EV", "sensor": "sensor.ev"}],
    }
    monkeypatch.setattr(system_router, "load_yaml", lambda _path: config)
    state = {"state": "7200", "attributes": {}}
    with (
        with_overrides({"sensor.ev": "W"}),
        patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=state)),
    ):
        assert (await system_router.get_system_status()).ev_kw == pytest.approx(7.2)


# --- water progress (2.8) -----------------------------------------------------------


def history(unit=None):
    tz = pytz.timezone("Europe/Stockholm")
    start = tz.localize(datetime(2026, 1, 15, 6))
    states = [
        {
            "state": "3000",
            "last_changed": start.isoformat(),
            "attributes": {"unit_of_measurement": unit} if unit else {},
        },
        {"state": "unavailable", "last_changed": (start + timedelta(minutes=5)).isoformat()},
        {"state": "60", "last_changed": (start + timedelta(minutes=10)).isoformat()},
    ]
    return states, start, tz


@pytest.mark.parametrize(
    ("unit", "overrides", "expected"),
    [
        ("W", {}, 0.25),  # 3 kW for 5 minutes
        (None, {"sensor.wh": "W"}, 0.25),
        (None, {}, 255.0),  # unitless without override is kW, as before
        ("kW", {"sensor.wh": "W"}, 255.0),
    ],
)
def test_water_progress_history_units(unit, overrides, expected):
    states, start, tz = history(unit)
    with with_overrides(overrides):
        energy, _ = _history_energy(
            states, start, start + timedelta(minutes=15), 0.1, tz, "sensor.wh"
        )
    assert energy == pytest.approx(expected)


# --- loads service (2.9) ------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("unit", "overrides", "expected"),
    [("W", {}, 2.5), (None, {"sensor.wh": "W"}, 2.5), (None, {}, 2500.0)],
)
async def test_load_service_power_units(unit, overrides, expected):
    config = {
        "config_version": 2,
        "system": {"has_water_heater": True},
        "water_heaters": [
            {"id": "wh", "enabled": True, "name": "Tank", "sensor": "sensor.wh", "power_kw": 3.0}
        ],
        "input_sensors": {},
    }
    state = {"state": "2500", "attributes": {"unit_of_measurement": unit} if unit else {}}
    service = LoadDisaggregator(config)
    with (
        with_overrides(overrides),
        patch.object(ha_client, "get_ha_entity_state", AsyncMock(return_value=state)),
    ):
        assert await service.update_current_power() == pytest.approx(expected)
