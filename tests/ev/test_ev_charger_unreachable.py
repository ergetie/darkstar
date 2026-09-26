"""Unreachable charger is distinct from unplugged (ev-goal-shortfall-recovery 4.4).

Spec: ``ev-missed-goal-recovery`` — "Unreachable charger is distinct from
unplugged".
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core import ev_plug
from backend.core.ev_plug import is_unreachable_state, resolve_plug_state
from backend.core.ha_client import get_initial_state
from backend.ha_socket import HAWebSocketClient


@pytest.fixture(autouse=True)
def _clear_last_known_plug_state():
    ev_plug._last_known_plugged.clear()
    yield
    ev_plug._last_known_plugged.clear()


def _client(plugged_in: bool = True) -> HAWebSocketClient:
    client = object.__new__(HAWebSocketClient)
    client.monitored_entities = {"sensor.goe_state": "ev_plug_0"}
    client.ev_charger_configs = [
        {"id": "goe", "name": "go-e", "plugged_in_states": "WaitCar,Charging"}
    ]
    client.latest_values = {
        "ev_chargers": [{"name": "go-e", "kw": 0.0, "soc": None, "plugged_in": plugged_in}]
    }
    client._trigger_ev_replan = MagicMock()
    return client


def _change(client: HAWebSocketClient, state: str) -> None:
    with (
        patch("backend.events.emit_ha_entity_change"),
        patch("backend.events.emit_live_metrics"),
    ):
        client._handle_state_change("sensor.goe_state", {"state": state})


@pytest.mark.parametrize("raw", ["unavailable", "unknown", " Unavailable "])
def test_unreachable_states(raw):
    assert is_unreachable_state(raw) is True


@pytest.mark.parametrize("raw", [None, "", "Idle", "off", "Charging"])
def test_reachable_states(raw):
    assert is_unreachable_state(raw) is False


def test_resolve_keeps_last_known_state_when_unreachable():
    assert resolve_plug_state("goe", "Charging", "WaitCar,Charging") == (True, False)
    assert resolve_plug_state("goe", "unavailable", "WaitCar,Charging") == (True, True)


def test_resolve_unreachable_without_history_is_unplugged():
    assert resolve_plug_state("goe", "unknown", "WaitCar,Charging") == (False, True)


@pytest.mark.parametrize("raw", ["unavailable", "unknown"])
def test_websocket_unavailable_does_not_unplug_or_replan(raw):
    client = _client(plugged_in=True)
    _change(client, raw)

    ev = client.latest_values["ev_chargers"][0]
    assert ev["plugged_in"] is True
    assert ev["unreachable"] is True
    client._trigger_ev_replan.assert_not_called()


def test_websocket_return_to_connected_triggers_plugin_replan():
    client = _client(plugged_in=True)
    _change(client, "unavailable")
    _change(client, "Charging")

    ev = client.latest_values["ev_chargers"][0]
    assert ev["plugged_in"] is True
    assert ev["unreachable"] is False
    client._trigger_ev_replan.assert_called_once_with(charger_id="goe", plugged_in=True)


def test_websocket_return_unplugged_uses_existing_unplug_rule():
    client = _client(plugged_in=True)
    _change(client, "unavailable")
    _change(client, "Idle")

    assert client.latest_values["ev_chargers"][0]["plugged_in"] is False
    client._trigger_ev_replan.assert_called_once_with(charger_id="goe", plugged_in=False)


@pytest.mark.asyncio
async def test_planner_state_uses_last_known_plug_when_unreachable(tmp_path):
    config = {
        "system": {"has_ev_charger": True},
        "input_sensors": {},
        "ev_chargers": [
            {
                "id": "goe",
                "enabled": True,
                "plug_sensor": "sensor.goe_state",
                "plugged_in_states": "WaitCar, Charging",
            }
        ],
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text("placeholder")
    ev_plug.remember_plug_state("goe", True)

    with (
        patch("backend.core.secrets.load_yaml", return_value=config),
        patch(
            "backend.core.ha_client.get_ha_entity_state",
            new=AsyncMock(return_value={"state": "unavailable"}),
        ),
        patch("backend.core.secrets.load_home_assistant_config", return_value={}),
    ):
        result = await get_initial_state(config_path=str(config_path))

    assert result["ev_charger_states"] == [
        {
            "id": "goe",
            "soc_percent": None,
            "soc_status": None,
            "soc_age_minutes": None,
            "plugged_in": True,
            "unreachable": True,
        }
    ]
