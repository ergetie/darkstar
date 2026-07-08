"""Tests for the read-only EV state API (price-forecasting-module-4 §5.4).

Covers the spec scenarios in ``specs/ev-target-charging/spec.md``:
- Charger with an active goal returns live sensors + goal + progress + status.
- Spreading charger includes ``quota_schedule``; non-spreading has null quota.
- Missing/stale state file → ``idle`` status + null goal-progress fields, with
  live HA sensors still populated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routers import ev as ev_router


def _config(chargers: list[dict]) -> dict:
    return {"ev_chargers": chargers}


def _charger_cfg(
    *,
    id: str = "ev1",
    name: str = "EV-01",
    enabled: bool = True,
    sensor: str = "sensor.ev1_power",
    soc_sensor: str = "sensor.ev1_soc",
    plug_sensor: str = "binary_sensor.ev1_plug",
    max_power_kw: float = 7.4,
    **extra,
) -> dict:
    base = {
        "id": id,
        "name": name,
        "enabled": enabled,
        "sensor": sensor,
        "soc_sensor": soc_sensor,
        "plug_sensor": plug_sensor,
        "max_power_kw": max_power_kw,
    }
    base.update(extra)
    return base


def _patch_ha(power_kw: float, soc: float, plugged: bool):
    return (
        patch(
            "backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=power_kw)
        ),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=soc)),
        patch("backend.api.routers.ev.get_ha_bool", AsyncMock(return_value=plugged)),
    )


@pytest.mark.asyncio
async def test_charger_with_active_goal_returns_status_and_progress(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=6)
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": deadline.isoformat(),
            "required_kwh": 20.0,
            "delivered_kwh": 5.0,
            "remaining_kwh": 15.0,
            "current_soc_percent": 50.0,
            "target_soc_percent_cfg": 80,
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": None,
            "quota_schedule": None,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": now.isoformat(),
        }
    }
    state_file = tmp_path / "ev_multi_day_state.json"
    state_file.write_text(json.dumps(state))
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})

    cfg = _config([_charger_cfg()])
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)

    p_power, p_soc, p_plug = _patch_ha(power_kw=2.5, soc=50.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    assert len(result) == 1
    entry = result[0]
    assert entry["id"] == "ev1"
    assert entry["name"] == "EV-01"
    assert entry["plugged_in"] is True
    assert entry["soc_percent"] == 50.0
    assert entry["power_kw"] == 2.5
    assert entry["target_soc_percent"] == 80
    assert entry["ready_by"] == "07:00"
    assert entry["repeat"] == "daily"
    assert entry["required_kwh"] == 20.0
    assert entry["delivered_kwh"] == 5.0
    assert entry["remaining_kwh"] == 15.0
    assert entry["daily_quota_kwh"] is None
    assert entry["quota_schedule"] is None
    assert entry["status"] == "on_track"
    assert entry["last_updated"] == now.isoformat()
    # No charge_priority field is returned.
    assert "charge_priority" not in entry


@pytest.mark.asyncio
async def test_spreading_charger_includes_quota_schedule(monkeypatch):
    now = datetime.now(UTC)
    deadline = now + timedelta(days=3)
    quota_schedule = {
        (now).date().isoformat(): 12.0,
        (now + timedelta(days=1)).date().isoformat(): 20.0,
        (now + timedelta(days=2)).date().isoformat(): 18.0,
    }
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": deadline.isoformat(),
            "required_kwh": 50.0,
            "delivered_kwh": 0.0,
            "remaining_kwh": 50.0,
            "current_soc_percent": 30.0,
            "target_soc_percent_cfg": 80,
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": 12.0,
            "quota_schedule": quota_schedule,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": now.isoformat(),
        }
    }
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=30.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["daily_quota_kwh"] == 12.0
    assert entry["quota_schedule"] == quota_schedule
    assert entry["status"] in {"on_track", "behind"}


@pytest.mark.asyncio
async def test_non_spreading_charger_has_null_quota_fields(monkeypatch):
    now = datetime.now(UTC)
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": (now + timedelta(hours=6)).isoformat(),
            "required_kwh": 10.0,
            "delivered_kwh": 0.0,
            "remaining_kwh": 10.0,
            "current_soc_percent": 60.0,
            "target_soc_percent_cfg": 80,
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": None,
            "quota_schedule": None,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": now.isoformat(),
        }
    }
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=60.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["daily_quota_kwh"] is None
    assert entry["quota_schedule"] is None


@pytest.mark.asyncio
async def test_missing_state_file_returns_idle_with_live_sensors(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=1.5, soc=45.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["status"] == "idle"
    assert entry["target_soc_percent"] is None
    assert entry["required_kwh"] is None
    assert entry["deadline"] is None
    assert entry["daily_quota_kwh"] is None
    # Live sensors still populated.
    assert entry["plugged_in"] is True
    assert entry["soc_percent"] == 45.0
    assert entry["power_kw"] == 1.5


@pytest.mark.asyncio
async def test_stale_state_returns_idle(monkeypatch):
    now = datetime.now(UTC)
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": (now + timedelta(hours=6)).isoformat(),
            "required_kwh": 10.0,
            "delivered_kwh": 0.0,
            "remaining_kwh": 10.0,
            "current_soc_percent": 60.0,
            "target_soc_percent_cfg": 80,
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": None,
            "quota_schedule": None,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": (now - timedelta(hours=6)).isoformat(),
        }
    }
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=60.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["status"] == "idle"
    assert entry["required_kwh"] is None


@pytest.mark.asyncio
async def test_target_already_met_reports_complete(monkeypatch):
    now = datetime.now(UTC)
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": (now + timedelta(hours=6)).isoformat(),
            "required_kwh": 5.0,
            "delivered_kwh": 15.0,
            "remaining_kwh": 5.0,
            "current_soc_percent": 80.0,
            "target_soc_percent_cfg": 80,
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": None,
            "quota_schedule": None,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": now.isoformat(),
        }
    }
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=85.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["status"] == "complete"


@pytest.mark.asyncio
async def test_disabled_chargers_not_returned(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: _config([_charger_cfg(id="ev1"), _charger_cfg(id="ev2", enabled=False)]),
    )
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=0.0, plugged=False)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    assert len(result) == 1
    assert result[0]["id"] == "ev1"
