"""Tests for the read-only EV state API (price-forecasting-module-4 §5.4).

Covers the spec scenarios in ``specs/ev-target-charging/spec.md``:
- Charger with an active goal returns live sensors + goal + progress + status.
- ``planned_by_day`` / ``deferral_price_source`` are returned; legacy
  ``daily_quota_kwh`` / ``quota_schedule`` state keys are ignored.
- Missing/stale state file → ``idle`` status + null goal-progress fields, with
  live HA sensors still populated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routers import ev as ev_router


@pytest.fixture(autouse=True)
def _no_executor():
    """No executor instance unless a test patches one in (the real getter creates one)."""
    with patch("backend.api.routers.executor.get_executor_instance", return_value=None):
        yield


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
        "rated_power_kw": max_power_kw,
    }
    base.update(extra)
    return base


def _patch_ha(power_kw: float, soc: float, plugged: bool):
    return (
        patch(
            "backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=power_kw)
        ),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=soc)),
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(return_value={"state": "on" if plugged else "off"}),
        ),
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
    assert entry["planned_by_day"] == []
    assert entry["deferral_price_source"] is None
    assert "daily_quota_kwh" not in entry
    assert "quota_schedule" not in entry
    assert entry["status"] == "on_track"
    assert entry["last_updated"] == now.isoformat()
    # No charge_priority field is returned.
    assert "charge_priority" not in entry


@pytest.mark.asyncio
async def test_multi_day_charger_returns_planned_by_day(monkeypatch):
    now = datetime.now(UTC)
    deadline = now + timedelta(days=3)
    planned = [
        {"date": now.date().isoformat(), "kwh": 0.0, "basis": "known"},
        {"date": (now + timedelta(days=1)).date().isoformat(), "kwh": 8.0, "basis": "known"},
        {"date": (now + timedelta(days=2)).date().isoformat(), "kwh": 14.0, "basis": "estimated"},
    ]
    state = {
        "ev1": {
            "target_soc_percent": 80,
            "ready_by": "07:00",
            "repeat": "daily",
            "deadline": deadline.isoformat(),
            "required_kwh": 22.0,
            "delivered_kwh": 0.0,
            "remaining_kwh": 22.0,
            "current_soc_percent": 30.0,
            "battery_capacity_kwh": 82.0,
            "planned_by_day": planned,
            "deferral_price_source": "forecast",
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
    assert entry["planned_by_day"] == planned
    assert entry["deferral_price_source"] == "forecast"


@pytest.mark.asyncio
async def test_old_quota_keys_in_state_file_are_ignored(monkeypatch):
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
            "battery_capacity_kwh": 82.0,
            "daily_quota_kwh": 12.0,
            "quota_schedule": {now.date().isoformat(): 12.0},
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
    assert "daily_quota_kwh" not in entry
    assert "quota_schedule" not in entry
    assert entry["planned_by_day"] == []


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
    assert entry["planned_by_day"] == []
    # Live sensors still populated.
    assert entry["plugged_in"] is True
    assert entry["soc_percent"] == 45.0
    assert entry["power_kw"] == 1.5


@pytest.mark.asyncio
async def test_old_last_updated_still_reports_goal_truthfully(monkeypatch):
    """GET no longer nulls the goal based on ``last_updated`` age — the
    planner is what decides whether to act on it; ``last_planned_at`` reports
    when the planner last computed this progress instead of silently hiding
    the goal (removed 2-hour staleness rule)."""
    now = datetime.now(UTC)
    last_planned = (now - timedelta(hours=6)).isoformat()
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
            "battery_capacity_kwh": 82.0,
            "keep_on_after_target": False,
            "status": "on_track",
            "last_updated": last_planned,
            "last_planned_at": last_planned,
        }
    }
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {k: v for k, v in state.items()})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=60.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["status"] == "on_track"
    assert entry["required_kwh"] == 10.0
    assert entry["target_soc_percent"] == 80
    assert entry["last_planned_at"] == last_planned


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
async def test_multiple_chargers_preserve_config_order(monkeypatch):
    """Parallelizing per-charger HA reads (asyncio.gather) must not change
    response ordering versus the original config-list order."""
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: _config(
            [
                _charger_cfg(
                    id="ev1",
                    sensor="sensor.ev1_power",
                    soc_sensor="sensor.ev1_soc",
                    plug_sensor="binary_sensor.ev1_plug",
                ),
                _charger_cfg(
                    id="ev2",
                    sensor="sensor.ev2_power",
                    soc_sensor="sensor.ev2_soc",
                    plug_sensor="binary_sensor.ev2_plug",
                ),
            ]
        ),
    )

    power_by_entity = {"sensor.ev1_power": 2.0, "sensor.ev2_power": 5.0}
    soc_by_entity = {"sensor.ev1_soc": 40.0, "sensor.ev2_soc": 70.0}
    plug_by_entity = {"binary_sensor.ev1_plug": True, "binary_sensor.ev2_plug": False}

    with (
        patch(
            "backend.api.routers.ev.get_ha_sensor_kw_normalized",
            AsyncMock(side_effect=lambda e: power_by_entity[e]),
        ),
        patch(
            "backend.api.routers.ev.get_ha_sensor_float",
            AsyncMock(side_effect=lambda e: soc_by_entity[e]),
        ),
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(side_effect=lambda e: {"state": "on" if plug_by_entity[e] else "off"}),
        ),
    ):
        result = await ev_router.get_ev_chargers()

    assert [c["id"] for c in result] == ["ev1", "ev2"]
    assert result[0]["power_kw"] == 2.0
    assert result[0]["soc_percent"] == 40.0
    assert result[0]["plugged_in"] is True
    assert result[1]["power_kw"] == 5.0
    assert result[1]["soc_percent"] == 70.0
    assert result[1]["plugged_in"] is False


@pytest.mark.asyncio
async def test_charger_specific_plug_mapping_is_used(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: _config(
            [
                _charger_cfg(
                    plugged_in_states="WaitCar, Charging",
                    plug_sensor="sensor.goe_state",
                )
            ]
        ),
    )

    async def read_plug(entity_id: str) -> dict:
        assert entity_id == "sensor.goe_state"
        return {"state": " charging "}

    with (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=50.0)),
        patch("backend.api.routers.ev.get_ha_entity_state", AsyncMock(side_effect=read_plug)),
    ):
        result = await ev_router.get_ev_chargers()

    assert result[0]["plugged_in"] is True


@pytest.mark.asyncio
async def test_one_charger_sensor_failure_isolated(monkeypatch):
    """A failed sensor read for one charger degrades only that charger's
    fields to None; other chargers are unaffected."""
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: _config(
            [
                _charger_cfg(id="ev1", sensor="sensor.ev1_power"),
                _charger_cfg(id="ev2", sensor="sensor.ev2_power"),
            ]
        ),
    )

    async def _flaky_power(entity_id: str) -> float:
        if entity_id == "sensor.ev1_power":
            raise TimeoutError("HA unreachable")
        return 3.3

    with (
        patch(
            "backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(side_effect=_flaky_power)
        ),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=50.0)),
        patch("backend.api.routers.ev.get_ha_entity_state", AsyncMock(return_value={"state": "on"})),
    ):
        result = await ev_router.get_ev_chargers()

    by_id = {c["id"]: c for c in result}
    assert by_id["ev1"]["power_kw"] is None
    assert by_id["ev1"]["soc_percent"] == 50.0
    assert by_id["ev2"]["power_kw"] == 3.3
    assert by_id["ev2"]["soc_percent"] == 50.0


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


@pytest.mark.asyncio
async def test_charger_without_phases_is_listed_with_disabled_reason(monkeypatch):
    """A current charger missing phases stays visible with a named reason."""
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    cfg = _charger_cfg(id="ev1", name="Garage", type="current", max_current_a=12)
    cfg.pop("rated_power_kw")
    monkeypatch.setattr(
        ev_router, "load_yaml", lambda _p: _config([cfg, _charger_cfg(id="ev2")])
    )
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=40.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    by_id = {c["id"]: c for c in result}
    assert by_id["ev1"]["disabled_reason"] == "Configure phases for Garage to enable planning"
    assert by_id["ev2"]["disabled_reason"] is None


@pytest.mark.asyncio
async def test_unavailable_plug_reports_unreachable_with_last_known_state(monkeypatch):
    """ev-missed-goal-recovery: unavailable plug sensor = unreachable, not unplugged."""
    from backend.core import ev_plug

    monkeypatch.setattr(ev_plug, "_last_known_plugged", {"ev1": True})
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg(id="ev1")]))

    with (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=53.0)),
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(return_value={"state": "unavailable"}),
        ),
    ):
        result = await ev_router.get_ev_chargers()

    assert result[0]["unreachable"] is True
    assert result[0]["plugged_in"] is True


@pytest.mark.asyncio
async def test_unavailable_switch_reports_unreachable(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(
        ev_router,
        "load_yaml",
        lambda _p: _config([_charger_cfg(id="ev1", switch_entity="select.goe_force")]),
    )
    states = {"binary_sensor.ev1_plug": {"state": "on"}, "select.goe_force": {"state": "unknown"}}

    with (
        patch("backend.api.routers.ev.get_ha_sensor_kw_normalized", AsyncMock(return_value=0.0)),
        patch("backend.api.routers.ev.get_ha_sensor_float", AsyncMock(return_value=53.0)),
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(side_effect=lambda e: states[e]),
        ),
    ):
        result = await ev_router.get_ev_chargers()

    assert result[0]["unreachable"] is True
    assert result[0]["plugged_in"] is True


# --- ev-manual-charge API ---


class _FakeExecutor:
    def __init__(self, error: str | None = None):
        self.error = error
        self.set_calls: list[tuple] = []
        self.cleared: list[str] = []

    def set_ev_manual_charge(self, charger_id, target_soc, current_a, **live):
        self.set_calls.append((charger_id, target_soc, current_a, live))
        if self.error:
            raise ValueError(self.error)
        return {"success": True, "charger_id": charger_id, "target_soc": target_soc}

    def clear_ev_manual_charge(self, charger_id):
        self.cleared.append(charger_id)
        return {"success": True, "was_active": True}


def _patch_executor(executor):
    return patch("backend.api.routers.executor.get_executor_instance", return_value=executor)


@pytest.mark.asyncio
async def test_manual_charge_start_passes_live_readings(monkeypatch):
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    executor = _FakeExecutor()
    states = {"sensor.ev1_soc": {"state": "49.0"}, "binary_sensor.ev1_plug": {"state": "on"}}
    with (
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(side_effect=lambda e: states[e]),
        ),
        _patch_executor(executor),
    ):
        result = await ev_router.start_ev_manual_charge(
            "ev1", ev_router.EVManualChargeBody(target_soc=80)
        )

    assert result["success"] is True
    assert executor.set_calls == [
        ("ev1", 80, None, {"current_soc_percent": 49.0, "plug_state": "plugged"})
    ]


@pytest.mark.asyncio
async def test_manual_charge_start_reports_unplugged_to_executor(monkeypatch):
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    executor = _FakeExecutor(error="The car is not connected")
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=49.0, plugged=False)
    with p_power, p_soc, p_plug, _patch_executor(executor):
        with pytest.raises(ev_router.HTTPException) as exc_info:
            await ev_router.start_ev_manual_charge(
                "ev1", ev_router.EVManualChargeBody(target_soc=80)
            )

    assert exc_info.value.status_code == 400
    assert "not connected" in exc_info.value.detail
    assert executor.set_calls[0][3]["plug_state"] == "unplugged"


@pytest.mark.asyncio
async def test_manual_charge_start_rejects_unavailable_plug_despite_last_known(monkeypatch):
    """The start path never falls back to the last known plug reading."""
    from backend.core import ev_plug

    monkeypatch.setattr(ev_plug, "_last_known_plugged", {"ev1": True})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    states = {"sensor.ev1_soc": {"state": "49"}, "binary_sensor.ev1_plug": {"state": "unavailable"}}

    class _PlugCheckingExecutor(_FakeExecutor):
        def set_ev_manual_charge(self, charger_id, target_soc, current_a, **live):
            self.set_calls.append((charger_id, target_soc, current_a, live))
            if live["plug_state"] == "unknown":
                raise ValueError("The car's plug state is unknown (charger unreachable)")
            return {"success": True}

    executor = _PlugCheckingExecutor()
    with (
        patch(
            "backend.api.routers.ev.get_ha_entity_state",
            AsyncMock(side_effect=lambda e: states[e]),
        ),
        _patch_executor(executor),
        pytest.raises(ev_router.HTTPException) as exc_info,
    ):
        await ev_router.start_ev_manual_charge("ev1", ev_router.EVManualChargeBody(target_soc=80))

    assert exc_info.value.status_code == 400
    assert "plug state is unknown" in exc_info.value.detail
    assert executor.set_calls[0][3] == {"current_soc_percent": 49.0, "plug_state": "unknown"}


@pytest.mark.asyncio
async def test_manual_charge_unknown_or_disabled_charger_404(monkeypatch):
    monkeypatch.setattr(
        ev_router, "load_yaml", lambda _p: _config([_charger_cfg(enabled=False)])
    )
    with _patch_executor(_FakeExecutor()):
        for charger_id in ("ev1", "nope"):
            with pytest.raises(ev_router.HTTPException) as exc_info:
                await ev_router.start_ev_manual_charge(
                    charger_id, ev_router.EVManualChargeBody(target_soc=80)
                )
            assert exc_info.value.status_code == 404


@pytest.mark.parametrize("target", [0, 101])
def test_manual_charge_body_rejects_target_out_of_range(target):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ev_router.EVManualChargeBody(target_soc=target)


@pytest.mark.asyncio
async def test_manual_charge_stop(monkeypatch):
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    executor = _FakeExecutor()
    with _patch_executor(executor):
        result = await ev_router.stop_ev_manual_charge("ev1")
    assert result["was_active"] is True
    assert executor.cleared == ["ev1"]


@pytest.mark.asyncio
async def test_chargers_expose_manual_charge_without_treating_it_as_goal(monkeypatch):
    started = datetime.now(UTC).isoformat()
    state = {"ev1": {"manual_charge": {"target_soc": 80, "current_a": None, "started_at": started}}}
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: state)
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))

    p_power, p_soc, p_plug = _patch_ha(power_kw=7.2, soc=49.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()

    entry = result[0]
    assert entry["manual_charge"] == {"target_soc": 80, "current_a": None, "started_at": started}
    assert entry["target_soc_percent"] is None
    assert entry["status"] == "idle"


class _StatusExecutor:
    def __init__(self, status: dict):
        self.status = status

    def get_ev_manual_charge_status(self):
        return self.status


async def _chargers_with(monkeypatch, state: dict, executor) -> dict:
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: state)
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=49.0, plugged=True)
    with p_power, p_soc, p_plug, _patch_executor(executor):
        return (await ev_router.get_ev_chargers())[0]


@pytest.mark.asyncio
async def test_chargers_manual_charge_from_executor_when_file_empty(monkeypatch):
    live = {"target_soc": 80, "current_a": 10, "started_at": "2026-09-25T08:00:00+02:00"}
    executor = _StatusExecutor({"ev1": {**live, "expires_at": "2026-09-26T08:00:00+02:00"}})
    entry = await _chargers_with(monkeypatch, {}, executor)
    assert entry["manual_charge"] == live


@pytest.mark.asyncio
async def test_chargers_ignore_stale_file_manual_charge_when_executor_has_none(monkeypatch):
    stale = {"ev1": {"manual_charge": {"target_soc": 80, "current_a": None, "started_at": "x"}}}
    entry = await _chargers_with(monkeypatch, stale, _StatusExecutor({}))
    assert entry["manual_charge"] is None


@pytest.mark.asyncio
async def test_chargers_manual_charge_from_file_without_executor(monkeypatch):
    manual = {"target_soc": 80, "current_a": None, "started_at": "x"}
    entry = await _chargers_with(monkeypatch, {"ev1": {"manual_charge": manual}}, None)
    assert entry["manual_charge"] == manual


@pytest.mark.asyncio
async def test_chargers_manual_charge_null_when_inactive(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=49.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = await ev_router.get_ev_chargers()
    assert result[0]["manual_charge"] is None


@pytest.mark.asyncio
async def test_clearing_goal_keeps_manual_charge(monkeypatch, tmp_path):
    from backend.core import ev_state

    ev_state.write_ev_state(
        {
            "ev1": {
                "target_soc_percent": 80,
                "manual_charge": {"target_soc": 60, "current_a": None, "started_at": "x"},
            }
        }
    )
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: _config([_charger_cfg()]))
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=49.0, plugged=True)
    with p_power, p_soc, p_plug:
        await ev_router.set_ev_charger_schedule(
            "ev1", ev_router.EVChargerScheduleBody(target_soc_percent=None), MagicMock()
        )

    assert ev_state.read_ev_state() == {
        "ev1": {"manual_charge": {"target_soc": 60, "current_a": None, "started_at": "x"}}
    }


@pytest.mark.asyncio
async def test_chargers_report_type_with_executor_default_and_current_limits(monkeypatch):
    monkeypatch.setattr(ev_router, "_load_ev_state", lambda: {})
    cfg = _config(
        [
            _charger_cfg(id="bin", switch_entity="switch.bin"),
            _charger_cfg(
                id="cur",
                type="current",
                current_entity="number.cur",
                min_current_a=6,
                max_current_a=16,
            ),
        ]
    )
    monkeypatch.setattr(ev_router, "load_yaml", lambda _p: cfg)
    p_power, p_soc, p_plug = _patch_ha(power_kw=0.0, soc=49.0, plugged=True)
    with p_power, p_soc, p_plug:
        result = {c["id"]: c for c in await ev_router.get_ev_chargers()}

    assert result["bin"]["type"] == "binary"
    assert result["bin"]["externally_controlled"] is False
    assert result["bin"]["min_current_a"] is None
    assert result["cur"]["type"] == "current"
    assert (result["cur"]["min_current_a"], result["cur"]["max_current_a"]) == (6, 16)
