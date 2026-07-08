from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.core import ev_state
from backend.core.ha_client import get_ha_datetime
from backend.ha_socket import HAWebSocketClient


@pytest.mark.asyncio
async def test_get_ha_datetime_variants(monkeypatch):
    """Test get_ha_datetime parses various format variants and localizes naive datetimes."""
    # 1. ISO format with tz
    state_iso = {"state": "2026-06-10T14:30:00+02:00"}
    with patch("backend.core.ha_client.get_ha_entity_state", AsyncMock(return_value=state_iso)):
        res = await get_ha_datetime("input_datetime.test")
        assert res is not None
        assert res.tzinfo is not None
        assert res.hour == 14

    # 2. YYYY-MM-DD HH:MM:SS format (naive)
    state_naive = {"state": "2026-06-10 14:30:00"}
    # Mock load_yaml for config timezone
    monkeypatch.setattr("backend.core.secrets.load_yaml", lambda _: {"timezone": "Europe/Stockholm"})
    with patch("backend.core.ha_client.get_ha_entity_state", AsyncMock(return_value=state_naive)):
        res = await get_ha_datetime("input_datetime.test")
        assert res is not None
        assert res.tzinfo is not None
        assert res.tzinfo.zone == "Europe/Stockholm"
        assert res.hour == 14

    # 3. Time-only format -> returns None
    state_time = {"state": "14:30:00"}
    with patch("backend.core.ha_client.get_ha_entity_state", AsyncMock(return_value=state_time)):
        res = await get_ha_datetime("input_datetime.test")
        assert res is None

    # 4. Unknown/unavailable -> returns None
    state_unknown = {"state": "unknown"}
    with patch("backend.core.ha_client.get_ha_entity_state", AsyncMock(return_value=state_unknown)):
        res = await get_ha_datetime("input_datetime.test")
        assert res is None


def test_ha_change_updates_state_file_and_debounce(tmp_path, monkeypatch):
    """Test that HA state changes update state file goals and respect debounce windows."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # 1. Setup client
    client = HAWebSocketClient()
    client.ev_charger_configs = [{"index": 0, "name": "EV1", "id": "ev1"}]
    client.monitored_entities = {
        "input_datetime.ev_ready_by": "ev_ready_by_0",
        "input_number.ev_target_soc": "ev_target_soc_0",
    }

    # Seed state file
    initial = {"ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"}}
    state_file.write_text(json.dumps(initial))

    # 2. Trigger target SoC change from HA
    new_state = {"state": "90"}
    with patch("backend.core.websockets.ws_manager.emit_sync") as mock_emit:
        client._handle_state_change("input_number.ev_target_soc", new_state)

    updated = json.loads(state_file.read_text())
    assert updated["ev1"]["target_soc_percent"] == 90
    assert updated["ev1"]["source"] == "ha"
    mock_emit.assert_called_with("ev_schedule_changed", {"charger_id": "ev1", "id": "ev1"})

    # 3. Debounce: Simulate recent Darkstar write within 5s
    ev_state.last_darkstar_write["ev1"] = time.time()

    # Try to trigger ready-by change from HA
    new_ready_state = {"state": "2026-06-11 08:00:00"}
    with patch("backend.core.websockets.ws_manager.emit_sync") as mock_emit:
        client._handle_state_change("input_datetime.ev_ready_by", new_ready_state)

    # State file should NOT have been updated due to debounce!
    updated = json.loads(state_file.read_text())
    assert updated["ev1"].get("ready_by") == "07:00"  # remains old value

    # 4. Debounce expiry: Simulate write older than 5s
    ev_state.last_darkstar_write["ev1"] = time.time() - 6.0
    with patch("backend.core.websockets.ws_manager.emit_sync") as mock_emit:
        client._handle_state_change("input_datetime.ev_ready_by", new_ready_state)

    updated = json.loads(state_file.read_text())
    assert updated["ev1"]["ready_by"] == "08:00"  # updated!


@pytest.mark.asyncio
async def test_startup_sync_scenarios(tmp_path, monkeypatch):
    """Test startup sync seeds state file from HA, and pushes goals to HA if already present."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # Mock load_yaml for config
    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            },
            {
                "id": "ev2",
                "enabled": True,
                "ha_ready_by_entity": "input_datetime.ev2_ready",
                "ha_target_soc_entity": "input_number.ev2_soc",
            }
        ]
    }
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)

    # 1. State:
    # - ev1 has no state goal (needs to seed HA -> state)
    # - ev2 has a state goal (needs to push state -> HA)
    initial_state = {
        "ev2": {
            "target_soc_percent": 85,
            "ready_by": "07:30",
            "repeat": "daily",
        }
    }
    state_file.write_text(json.dumps(initial_state))

    # Mock HA get_states results
    results = [
        {"entity_id": "input_datetime.ev1_ready", "state": "2026-06-11 06:15:00"},
        {"entity_id": "input_number.ev1_soc", "state": "95.0"},
        {"entity_id": "input_datetime.ev2_ready", "state": "2026-06-11 08:00:00"},
        {"entity_id": "input_number.ev2_soc", "state": "50.0"},
    ]

    client = HAWebSocketClient()
    mock_sync_ha = AsyncMock()
    monkeypatch.setattr("backend.api.routers.ev.sync_goal_to_ha", mock_sync_ha)

    client._sync_ev_schedules_on_startup(results)

    # Await background tasks in sync_goal_to_ha
    await asyncio.sleep(0.1)

    updated = json.loads(state_file.read_text())

    # 2. ev1 seeded from HA
    assert "ev1" in updated
    assert updated["ev1"]["target_soc_percent"] == 95
    assert updated["ev1"]["ready_by"] == "06:15"
    assert updated["ev1"]["repeat"] == "none"  # because ready_by had a specific date
    assert updated["ev1"]["source"] == "ha"

    # 3. ev2 state goal kept, and pushed to HA
    assert updated["ev2"]["target_soc_percent"] == 85
    mock_sync_ha.assert_called_once()
    # Check arguments of mock_sync_ha: charger_id='ev2', target_soc=85
    args, kwargs = mock_sync_ha.call_args
    assert args[0] == "ev2"
    assert args[1] == 85
