from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from backend.api.routers import ev as ev_router
from backend.api.routers.ev import EVChargerScheduleBody, set_ev_charger_schedule
from backend.core import ev_state


def _charger_cfg(
    *,
    id: str = "ev1",
    name: str = "EV-01",
    enabled: bool = True,
    sensor: str = "sensor.ev1_power",
    soc_sensor: str = "sensor.ev1_soc",
    plug_sensor: str = "binary_sensor.ev1_plug",
    max_power_kw: float = 7.4,
    ha_ready_by_entity: str | None = None,
    ha_target_soc_entity: str | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "enabled": enabled,
        "sensor": sensor,
        "soc_sensor": soc_sensor,
        "plug_sensor": plug_sensor,
        "max_power_kw": max_power_kw,
        "ha_ready_by_entity": ha_ready_by_entity,
        "ha_target_soc_entity": ha_target_soc_entity,
    }


def _patch_ha(power_kw: float, soc: float, plugged: bool):
    return (
        patch(
            "backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=power_kw)
        ),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=soc)),
        patch("backend.api.routers.ev.get_ha_bool", AsyncMock(return_value=plugged)),
    )


@pytest.mark.asyncio
async def test_set_schedule_happy_path(tmp_path, monkeypatch):
    # Setup tmp path for state file
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {"ev_chargers": [_charger_cfg(id="ev1", ha_ready_by_entity="input_datetime.ev_ready_by", ha_target_soc_entity="input_number.ev_target_soc")]}
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    p_power, p_soc, p_plug = _patch_ha(power_kw=1.0, soc=40.0, plugged=True)

    body = EVChargerScheduleBody(
        target_soc_percent=80,
        ready_by="07:00",
        repeat="daily",
        keep_on_after_target=True,
    )
    bg_tasks = BackgroundTasks()

    # Mock sync_goal_to_ha to inspect calls
    mock_sync = AsyncMock()
    monkeypatch.setattr(ev_router, "sync_goal_to_ha", mock_sync)

    with p_power, p_soc, p_plug:
        res = await set_ev_charger_schedule("ev1", body, bg_tasks)

    # 1. State written
    assert state_file.exists()
    written_data = json.loads(state_file.read_text())
    assert "ev1" in written_data
    assert written_data["ev1"]["target_soc_percent"] == 80
    assert written_data["ev1"]["ready_by"] == "07:00"
    assert written_data["ev1"]["repeat"] == "daily"
    assert written_data["ev1"]["keep_on_after_target"] is True

    # 2. Response shape (merges live sensors)
    assert res["id"] == "ev1"
    assert res["target_soc_percent"] == 80
    assert res["ready_by"] == "07:00"
    assert res["repeat"] == "daily"
    assert res["keep_on_after_target"] is True
    assert res["soc_percent"] == 40.0
    assert res["power_kw"] == 1.0


@pytest.mark.asyncio
async def test_clear_goal(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    # Seed initial state with two chargers
    initial_state = {
        "ev1": {"target_soc_percent": 80, "ready_by": "07:00", "repeat": "daily"},
        "ev2": {"target_soc_percent": 90, "ready_by": "08:00", "repeat": "daily"},
    }
    state_file.write_text(json.dumps(initial_state))

    cfg = {"ev_chargers": [_charger_cfg(id="ev1"), _charger_cfg(id="ev2")]}
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=50.0, plugged=False)

    body = EVChargerScheduleBody(target_soc_percent=None)
    bg_tasks = BackgroundTasks()

    with p_power, p_soc, p_plug:
        res = await set_ev_charger_schedule("ev1", body, bg_tasks)

    # Goal cleared for ev1 (removed from state)
    written_data = json.loads(state_file.read_text())
    assert "ev1" not in written_data
    # Other charger (ev2) preserved
    assert "ev2" in written_data
    assert written_data["ev2"]["target_soc_percent"] == 90

    # Response indicates idle / null goal fields
    assert res["id"] == "ev1"
    assert res["target_soc_percent"] is None
    assert res["status"] == "idle"


@pytest.mark.asyncio
async def test_set_schedule_404_unknown_charger(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {"ev_chargers": [_charger_cfg(id="ev1")]}
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    body = EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="daily")
    bg_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as excinfo:
        await set_ev_charger_schedule("ev_unknown", body, bg_tasks)
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_schedule_422_invalid_inputs(tmp_path, monkeypatch):
    state_file = tmp_path / "ev_multi_day_state.json"
    monkeypatch.setattr(ev_state, "STATE_FILE_PATH", state_file)

    cfg = {"ev_chargers": [_charger_cfg(id="ev1")]}
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)
    bg_tasks = BackgroundTasks()

    # Invalid target
    body = EVChargerScheduleBody(target_soc_percent=150, ready_by="07:00", repeat="daily")
    with pytest.raises(HTTPException) as excinfo:
        await set_ev_charger_schedule("ev1", body, bg_tasks)
    assert excinfo.value.status_code == 422

    # Invalid repeat
    body = EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="invalid_mode")
    with pytest.raises(HTTPException) as excinfo:
        await set_ev_charger_schedule("ev1", body, bg_tasks)
    assert excinfo.value.status_code == 422

    # None repeat without date
    body = EVChargerScheduleBody(target_soc_percent=80, ready_by="07:00", repeat="none", ready_by_date=None)
    with pytest.raises(HTTPException) as excinfo:
        await set_ev_charger_schedule("ev1", body, bg_tasks)
    assert excinfo.value.status_code == 422
