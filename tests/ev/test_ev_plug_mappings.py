from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.ev_plug import is_ev_plugged_in, parse_ev_plugged_in_states
from backend.core.ha_client import get_initial_state
from backend.ha_socket import HAWebSocketClient


def test_plug_state_csv_is_trimmed_case_insensitively_and_ignores_empty_tokens():
    assert parse_ev_plugged_in_states(" WaitCar, Charging, , Complete ") == {
        "waitcar",
        "charging",
        "complete",
    }
    assert is_ev_plugged_in(" COMPLETE ", "WaitCar, Charging, Complete") is True
    assert is_ev_plugged_in("Idle", "WaitCar, Charging, Complete") is False
    assert is_ev_plugged_in("connected") is True


@pytest.mark.asyncio
async def test_initial_state_uses_charger_specific_plug_mapping(tmp_path):
    config = {
        "system": {"has_ev_charger": True, "battery": {"capacity_kwh": 10}},
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

    async def read_bool(entity_id: str, states: str):
        assert entity_id == "sensor.goe_state"
        assert states == "WaitCar, Charging"
        return is_ev_plugged_in(" charging ", states)

    with (
        patch("backend.core.secrets.load_yaml", return_value=config),
        patch("backend.core.ha_client.get_ha_bool", new=AsyncMock(side_effect=read_bool)),
        patch("backend.core.secrets.load_home_assistant_config", return_value={}),
    ):
        result = await get_initial_state(config_path=str(config_path))

    assert result["ev_charger_states"] == [
        {"id": "goe", "soc_percent": None, "plugged_in": True}
    ]


def test_websocket_uses_mapping_and_skips_connected_to_connected_replan():
    client = object.__new__(HAWebSocketClient)
    client.monitored_entities = {"sensor.goe_state": "ev_plug_0"}
    client.ev_charger_configs = [
        {
            "id": "goe",
            "name": "go-e",
            "plugged_in_states": "WaitCar,Charging",
        }
    ]
    client.latest_values = {
        "ev_chargers": [{"name": "go-e", "kw": 0.0, "soc": None, "plugged_in": True}]
    }
    client._trigger_ev_replan = MagicMock()

    with (
        patch("backend.events.emit_ha_entity_change"),
        patch("backend.events.emit_live_metrics"),
    ):
        client._handle_state_change("sensor.goe_state", {"state": "Charging"})

    assert client.latest_values["ev_chargers"][0]["plugged_in"] is True
    client._trigger_ev_replan.assert_not_called()
