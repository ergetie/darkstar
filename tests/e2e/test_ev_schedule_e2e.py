from __future__ import annotations

import json
from datetime import datetime, UTC, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from backend.api.routers import ev as ev_router
from backend.api.routers.ev import EVChargerScheduleBody, set_ev_charger_schedule, get_ev_chargers
from backend.core import ev_state
from backend.ha_socket import HAWebSocketClient
from planner.pipeline import _persist_ev_multi_day_state

# E2E Test Suite for EV scheduling (price-forecasting-module-5 §6)

@pytest.mark.asyncio
async def test_ev_schedule_e2e_flow(tmp_path, monkeypatch):
    """Test 6.1:
    POST /schedule (target 80, ready_by 07:00, repeat daily)
    -> state file has the goal
    -> run pipeline (mocked prices/sensors)
    -> state file gains required_kwh/daily_quota_kwh/status
    -> GET /api/ev/chargers returns the full state.
    """
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # 1. Mock config loaded by API and pipeline
    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "name": "Tesla",
                "enabled": True,
                "type": "binary",
                "max_power_kw": 7.4,
                "battery_capacity_kwh": 80.0,
                "sensor": "sensor.ev1_power",
                "soc_sensor": "sensor.ev1_soc",
                "plug_sensor": "binary_sensor.ev1_plug",
                "switch_entity": "switch.ev1_switch",
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            }
        ]
    }
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    # 2. Simulate POST /schedule
    from fastapi import BackgroundTasks
    body = EVChargerScheduleBody(
        target_soc_percent=80,
        ready_by="07:00",
        repeat="daily",
        keep_on_after_target=True,
    )
    bg_tasks = BackgroundTasks()

    # Mock sync_goal_to_ha
    mock_sync = AsyncMock()
    monkeypatch.setattr(ev_router, "sync_goal_to_ha", mock_sync)

    # Mock HA client sensor gets
    p_power = patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0))
    p_soc = patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=40.0))
    p_plug = patch("backend.api.routers.ev.get_ha_bool", AsyncMock(return_value=True))

    with p_power, p_soc, p_plug:
        # Calls the POST schedule logic directly
        await set_ev_charger_schedule("ev1", body, bg_tasks)

    # Assert goal exists in state file
    assert state_file.exists()
    state_data = json.loads(state_file.read_text())
    assert "ev1" in state_data
    assert state_data["ev1"]["target_soc_percent"] == 80
    assert state_data["ev1"]["ready_by"] == "07:00"
    assert state_data["ev1"]["source"] == "api"

    # 3. Simulate planner running _persist_ev_multi_day_state (read-modify-write)
    tz = pytz.timezone("Europe/Stockholm")
    now = datetime.now(UTC)
    ev_states = [
        {
            "id": "ev1",
            "deadline": now + timedelta(days=1),
            "required_kwh": 32.0,  # (80% - 40%) * 80kWh = 32kWh
            "soc_percent": 40.0,
            "plugged_in": True,
            "daily_quota_kwh": 10.0,
            "quota_schedule": {str((now + timedelta(days=1)).date()): 10.0},
        }
    ]
    # Execute persist step
    _persist_ev_multi_day_state(ev_states, cfg["ev_chargers"], sqlite_path="", tz=tz, now=now)

    # State file should now have computed properties
    state_data = json.loads(state_file.read_text())
    assert state_data["ev1"]["required_kwh"] == 32.0
    assert state_data["ev1"]["daily_quota_kwh"] == 10.0
    # Goal fields must still be preserved
    assert state_data["ev1"]["target_soc_percent"] == 80
    assert state_data["ev1"]["ready_by"] == "07:00"
    assert state_data["ev1"]["source"] == "api"

    # 4. Simulate GET /api/ev/chargers
    with p_power, p_soc, p_plug:
        chargers = await get_ev_chargers()

    assert len(chargers) == 1
    charger = chargers[0]
    assert charger["id"] == "ev1"
    assert charger["target_soc_percent"] == 80
    assert charger["ready_by"] == "07:00"
    assert charger["required_kwh"] == 32.0
    assert charger["daily_quota_kwh"] == 10.0
    assert charger["status"] == "on_track"
    assert charger["source"] == "api"
    assert charger["externally_controlled"] is False


@pytest.mark.asyncio
async def test_ev_schedule_e2e_ha_sync(tmp_path, monkeypatch):
    """Test 6.2: E2E HA sync:
    Simulate a state_changed on the ready-by input_datetime and the target-SoC input_number
    -> state-file goal updates and HA value wins
    -> GET reflects it.
    """
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev1",
                "name": "Tesla",
                "enabled": True,
                "type": "binary",
                "max_power_kw": 7.4,
                "sensor": "sensor.ev1_power",
                "soc_sensor": "sensor.ev1_soc",
                "plug_sensor": "binary_sensor.ev1_plug",
                "switch_entity": "switch.ev1_switch",
                "ha_ready_by_entity": "input_datetime.ev1_ready",
                "ha_target_soc_entity": "input_number.ev1_soc",
            }
        ]
    }
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)
    monkeypatch.setattr("backend.ha_socket.load_yaml", lambda _: cfg)

    # Initialize HAWebSocketClient
    client = HAWebSocketClient()
    client.ev_charger_configs = [{"index": 0, "name": "Tesla", "id": "ev1"}]
    client.monitored_entities = {
        "input_datetime.ev1_ready": "ev_ready_by_0",
        "input_number.ev1_soc": "ev_target_soc_0",
    }

    # Simulate HA state changes
    new_ready_state = {"state": "2026-06-11 08:30:00"}
    new_soc_state = {"state": "90"}

    with patch("backend.core.websockets.ws_manager.emit_sync") as mock_emit:
        client._handle_state_change("input_datetime.ev1_ready", new_ready_state)
        client._handle_state_change("input_number.ev1_soc", new_soc_state)

    # Verify state file updated, source set to "ha"
    state_data = json.loads(state_file.read_text())
    assert state_data["ev1"]["ready_by"] == "08:30"
    assert state_data["ev1"]["target_soc_percent"] == 90
    assert state_data["ev1"]["source"] == "ha"

    # GET request reflects HA values
    p_power = patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0))
    p_soc = patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=50.0))
    p_plug = patch("backend.api.routers.ev.get_ha_bool", AsyncMock(return_value=True))

    with p_power, p_soc, p_plug:
        chargers = await get_ev_chargers()

    assert len(chargers) == 1
    assert chargers[0]["ready_by"] == "08:30"
    assert chargers[0]["target_soc_percent"] == 90
    assert chargers[0]["source"] == "ha"


@pytest.mark.asyncio
async def test_ev_schedule_e2e_escape_hatch(tmp_path, monkeypatch):
    """Test 6.3: E2E escape hatch:
    A charger with switch_entity unset is reported as externally controlled
    and Darkstar issues no switch command for it.
    """
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {
        "timezone": "Europe/Stockholm",
        "ev_chargers": [
            {
                "id": "ev_uncontrolled_binary",
                "name": "Legacy Binary Charger",
                "enabled": True,
                "max_power_kw": 7.4,
                "type": "binary",
                "sensor": "sensor.ev1_power",
                "soc_sensor": "sensor.ev1_soc",
                "plug_sensor": "binary_sensor.ev1_plug",
                "switch_entity": "",  # Unset -> Escape hatch!
            },
            {
                "id": "ev_controlled_binary",
                "name": "Controlled Binary Charger",
                "enabled": True,
                "max_power_kw": 7.4,
                "type": "binary",
                "sensor": "sensor.ev2_power",
                "soc_sensor": "sensor.ev2_soc",
                "plug_sensor": "binary_sensor.ev2_plug",
                "switch_entity": "switch.ev2_switch",  # Set
            }
        ]
    }
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    # 1. Verify GET /api/ev/chargers reports uncontrolled charger as externally controlled
    p_power = patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0))
    p_soc = patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=50.0))
    p_plug = patch("backend.api.routers.ev.get_ha_bool", AsyncMock(return_value=True))

    with p_power, p_soc, p_plug:
        chargers = await get_ev_chargers()

    assert len(chargers) == 2
    uncontrolled = next(c for c in chargers if c["id"] == "ev_uncontrolled_binary")
    controlled = next(c for c in chargers if c["id"] == "ev_controlled_binary")

    assert uncontrolled["externally_controlled"] is True
    assert controlled["externally_controlled"] is False

    # 2. Verify executor issues no switch commands for uncontrolled binary charger
    from executor.engine import ExecutorEngine
    from executor.config import ExecutorConfig, EVChargerDeviceConfig
    from executor.override import SlotPlan

    exec_cfg = ExecutorConfig(
        timezone="Europe/Stockholm",
        ev_chargers=[
            EVChargerDeviceConfig(
                id="ev_uncontrolled_binary",
                type="binary",
                switch_entity="",  # Unset
            ),
            EVChargerDeviceConfig(
                id="ev_controlled_binary",
                type="binary",
                switch_entity="switch.ev2_switch",  # Set
                max_power_kw=7.4,
            )
        ]
    )

    # Use __new__ to bypass file-loading __init__ logic
    engine = ExecutorEngine.__new__(ExecutorEngine)
    engine.config = exec_cfg
    engine._ev_charger_states = {}

    mock_ha = AsyncMock()
    engine.ha_client = mock_ha
    engine.dispatcher = MagicMock()
    engine.dispatcher.set_ev_charger_switch = AsyncMock()

    # Create slot plan where both chargers should charge
    slot = SlotPlan(
        ev_charger_plans={
            "ev_uncontrolled_binary": 7.4,
            "ev_controlled_binary": 7.4,
        }
    )

    # Mock HA state to show switches are currently off
    mock_ha.get_state_value = AsyncMock(return_value="off")

    # Run executor EV control step
    await engine._control_ev_charger(slot, now=datetime.now(), force_stop=False, shed_binary_charger_ids=set())

    # Verify that only the controlled binary charger got a set_ev_charger_switch call!
    # No call should be made for ev_uncontrolled_binary
    assert engine.dispatcher.set_ev_charger_switch.call_count == 1
    args, kwargs = engine.dispatcher.set_ev_charger_switch.call_args
    assert args[0] == "switch.ev2_switch"
