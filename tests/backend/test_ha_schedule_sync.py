from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, UTC
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
    monkeypatch.setattr(
        "backend.core.secrets.load_yaml", lambda _: {"timezone": "Europe/Stockholm"}
    )
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


def test_monitored_entities_include_ev_goal_entities(monkeypatch):
    """5.1: ha_ready_by_entity/ha_target_soc_entity are registered for monitoring."""
    cfg = {
        "input_sensors": {},
        "system": {"has_ev_charger": True},
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            }
        ],
    }
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)
    client = HAWebSocketClient()
    assert client.monitored_entities.get("input_datetime.ev1_ready") == "ev_ready_by_0"
    assert client.monitored_entities.get("input_number.ev1_soc") == "ev_target_soc_0"


@pytest.mark.asyncio
async def test_startup_sync_scenarios(tmp_path, monkeypatch):
    """HA-wins-with-sanity reconnect sync: seeds a goal-less charger from HA
    when HA's values are sane, and pushes an existing goal back to HA when
    HA's values are missing/insane — never blanket-overwrites either side."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    tz = pytz.timezone("Europe/Stockholm")
    future = datetime.now(tz) + timedelta(days=2)
    future_str = future.strftime("%Y-%m-%d %H:%M:%S")

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
            },
        ],
    }
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)

    # 1. State:
    # - ev1 has no state goal, HA has sane future values -> seeded from HA
    # - ev2 has a state goal, HA is unavailable/insane -> pushed back to HA
    initial_state = {
        "ev2": {
            "target_soc_percent": 85,
            "ready_by": "07:30",
            "repeat": "daily",
            "source": "api",
        }
    }
    state_file.write_text(json.dumps(initial_state))

    results = [
        {"entity_id": "input_datetime.ev1_ready", "state": future_str},
        {"entity_id": "input_number.ev1_soc", "state": "95.0"},
        {"entity_id": "input_datetime.ev2_ready", "state": "unknown"},
        {"entity_id": "input_number.ev2_soc", "state": "unavailable"},
    ]

    client = HAWebSocketClient()
    mock_sync_ha = AsyncMock()
    monkeypatch.setattr("backend.api.routers.ev.sync_goal_to_ha", mock_sync_ha)

    client._sync_ev_schedules_on_startup(results)

    # Await background tasks in sync_goal_to_ha
    await asyncio.sleep(0.1)

    updated = json.loads(state_file.read_text())

    # 2. ev1 seeded from HA (sane future datetime -> adopted as a one-off)
    assert "ev1" in updated
    assert updated["ev1"]["target_soc_percent"] == 95
    assert updated["ev1"]["repeat"] == "none"
    assert updated["ev1"]["ready_by_date"] == future.date().isoformat()
    assert updated["ev1"]["source"] == "ha"

    # 3. ev2 state goal kept untouched (HA unavailable), and pushed to HA
    assert updated["ev2"]["target_soc_percent"] == 85
    assert updated["ev2"]["source"] == "api"
    mock_sync_ha.assert_called_once()
    args, kwargs = mock_sync_ha.call_args
    assert args[0] == "ev2"
    assert args[1] == 85


@pytest.mark.asyncio
async def test_reconnect_past_ha_datetime_not_adopted_pushes_state_instead(tmp_path, monkeypatch):
    """A past/stale HA ready-by datetime is never adopted (kills the expired-
    goal seeding bug); the existing state-file goal is pushed to HA instead."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            },
        ],
    }
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)

    initial_state = {
        "ev1": {
            "target_soc_percent": 85,
            "ready_by": "07:30",
            "repeat": "daily",
            "source": "api",
        }
    }
    state_file.write_text(json.dumps(initial_state))

    results = [
        {"entity_id": "input_datetime.ev1_ready", "state": "2020-01-01 06:00:00"},
        {"entity_id": "input_number.ev1_soc", "state": "unknown"},
    ]

    client = HAWebSocketClient()
    mock_sync_ha = AsyncMock()
    monkeypatch.setattr("backend.api.routers.ev.sync_goal_to_ha", mock_sync_ha)

    client._sync_ev_schedules_on_startup(results)
    await asyncio.sleep(0.1)

    updated = json.loads(state_file.read_text())
    # State-file goal untouched — the past HA datetime was rejected.
    assert updated["ev1"]["target_soc_percent"] == 85
    assert updated["ev1"]["ready_by"] == "07:30"
    assert updated["ev1"]["source"] == "api"

    mock_sync_ha.assert_called_once()
    args, kwargs = mock_sync_ha.call_args
    assert args[0] == "ev1"
    assert args[1] == 85


@pytest.mark.asyncio
async def test_reconnect_adopts_sane_ha_soc_nothing_pushed_back(tmp_path, monkeypatch):
    """HA SoC changed while Darkstar was offline (sane value) -> adopted;
    since HA is the only configured entity and it agrees, nothing is pushed."""
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "enabled": True,
                "ha_target_soc_entity": "input_number.ev1_soc",
            },
        ],
    }
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)

    initial_state = {
        "ev1": {
            "target_soc_percent": 60,
            "ready_by": "07:30",
            "repeat": "daily",
            "source": "api",
        }
    }
    state_file.write_text(json.dumps(initial_state))

    results = [{"entity_id": "input_number.ev1_soc", "state": "75.0"}]

    client = HAWebSocketClient()
    mock_sync_ha = AsyncMock()
    monkeypatch.setattr("backend.api.routers.ev.sync_goal_to_ha", mock_sync_ha)

    client._sync_ev_schedules_on_startup(results)
    await asyncio.sleep(0.1)

    updated = json.loads(state_file.read_text())
    assert updated["ev1"]["target_soc_percent"] == 75
    assert updated["ev1"]["source"] == "ha"
    mock_sync_ha.assert_not_called()
