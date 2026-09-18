"""System-status coverage for per-charger EV plug-state mappings."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routers import system as system_router
from backend.core.ev_plug import is_ev_plugged_in


@pytest.mark.asyncio
async def test_system_status_uses_each_chargers_plug_vocabulary(monkeypatch):
    config = {
        "system": {"has_ev_charger": True},
        "input_sensors": {},
        "ev_chargers": [
            {
                "id": "charger_a",
                "name": "A",
                "enabled": True,
                "sensor": "sensor.a_power",
                "soc_sensor": "sensor.a_soc",
                "plug_sensor": "sensor.a_state",
                "plugged_in_states": "WaitCar",
            },
            {
                "id": "charger_b",
                "name": "B",
                "enabled": True,
                "sensor": "sensor.b_power",
                "soc_sensor": "sensor.b_soc",
                "plug_sensor": "sensor.b_state",
                "plugged_in_states": "Charging",
            },
        ],
    }
    monkeypatch.setattr(system_router, "load_yaml", lambda _path: config)

    async def read_power(_entity_id: str) -> float:
        return 0.0

    async def read_soc(_entity_id: str) -> float:
        return 50.0

    raw_states = {"sensor.a_state": "WaitCar", "sensor.b_state": "WaitCar"}

    async def read_plug(entity_id: str, connected_states: str) -> bool:
        return is_ev_plugged_in(raw_states[entity_id], connected_states)

    with (
        patch(
            "backend.api.routers.system.get_ha_sensor_kw_normalized",
            new=AsyncMock(side_effect=read_power),
        ),
        patch(
            "backend.api.routers.system.get_ha_sensor_float",
            new=AsyncMock(side_effect=read_soc),
        ),
        patch("backend.api.routers.system.get_ha_bool", new=AsyncMock(side_effect=read_plug)),
    ):
        result = await system_router.get_system_status()

    assert [charger["plugged_in"] for charger in result.ev_chargers] == [True, False]
    assert result.ev_plugged_in is True
