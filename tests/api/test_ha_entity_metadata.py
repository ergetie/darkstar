from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routers.ha import get_ha_entities


@pytest.mark.asyncio
async def test_ha_entities_exposes_select_options_from_states_payload():
    response = MagicMock(status_code=200)
    response.json.return_value = [
        {
            "entity_id": "select.ev_mode",
            "attributes": {"friendly_name": "EV mode", "options": ["Neutral", "Off", "On"]},
        },
        {"entity_id": "sensor.ev_state", "attributes": {"friendly_name": "EV state"}},
    ]
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    with (
        patch(
            "backend.api.routers.ha.load_home_assistant_config",
            return_value={"url": "http://ha", "token": "token"},
        ),
        patch("backend.core.ha_client.get_ha_http_client", return_value=client),
    ):
        result = await get_ha_entities()

    by_id = {entity["entity_id"]: entity for entity in result["entities"]}
    assert by_id["select.ev_mode"]["options"] == ["Neutral", "Off", "On"]
    assert by_id["sensor.ev_state"]["options"] == []
