"""Executor plug gating and plug-in reminder (ev-goal-lifecycle-feedback 6.2, 7.4)."""

from __future__ import annotations

import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.config import (
    EVChargerDeviceConfig,
    ExecutorConfig,
    NotificationConfig,
    load_executor_config,
)
from executor.engine import ExecutorEngine
from executor.override import SlotPlan

TZ = pytz.timezone("Europe/Stockholm")


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        path = f.name
    yield path
    with contextlib.suppress(OSError):
        Path(path).unlink()


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    Base.metadata.create_all(create_engine(f"sqlite:///{db_path}"))
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def _charger(charger_id: str = "ev1", **overrides) -> EVChargerDeviceConfig:
    params = {
        "id": charger_id,
        "name": "Go-e",
        "switch_entity": f"switch.{charger_id}",
        "plug_sensor": f"binary_sensor.{charger_id}_plug",
    }
    params.update(overrides)
    return EVChargerDeviceConfig(**params)


def _engine(
    temp_schedule,
    temp_db,
    chargers,
    plug_states: dict[str, str | None],
    reminder_minutes: int | None = None,
):
    """Build an engine; ``reminder_minutes`` enables the global plug-in reminder."""
    notifications = NotificationConfig(
        on_ev_plug_in_reminder=reminder_minutes is not None,
        ev_plug_in_reminder_minutes=reminder_minutes or 30,
    )
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=chargers,
            notifications=notifications,
        )
        with (
            patch("executor.engine.load_yaml", return_value={}),
            patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db),
        ):
            eng = ExecutorEngine("config.yaml")
    eng._has_ev_charger = True

    async def _state(entity_id: str) -> str | None:
        for cid, value in plug_states.items():
            if entity_id == f"binary_sensor.{cid}_plug":
                return value
        return None

    eng.ha_client = MagicMock()
    eng.ha_client.get_state_value = AsyncMock(side_effect=_state)
    eng.dispatcher = MagicMock()
    eng.dispatcher.notify_plug_in_reminder = AsyncMock()
    return eng


def _slot(**kw) -> SlotPlan:
    return SlotPlan(
        ev_charging_kw=kw.get("total", 7.0),
        ev_charger_plans=kw.get("plans", {"ev1": 7.0}),
        ev_keep_on=kw.get("keep_on", {}),
        ev_surplus_kw=kw.get("surplus", {}),
        discharge_kw=2.0,
    )


# --- 6.2 plug gating ---


@pytest.mark.asyncio
async def test_planned_slot_while_unplugged_is_not_actionable(temp_schedule, temp_db):
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"})
    gated = eng._gate_ev_plan_on_plug_state(_slot(), await eng._read_ev_plug_states())

    assert gated.ev_charger_plans["ev1"] == 0.0
    assert gated.ev_charging_kw == 0.0
    # Nothing left to drive the switch or source isolation.
    assert eng._charger_should_be_on(gated, "ev1") is False
    assert gated.discharge_kw == 2.0


@pytest.mark.asyncio
async def test_plugged_charger_plan_unchanged(temp_schedule, temp_db):
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "on"})
    slot = _slot()
    gated = eng._gate_ev_plan_on_plug_state(slot, await eng._read_ev_plug_states())
    assert gated is slot
    assert eng._charger_should_be_on(gated, "ev1") is True


@pytest.mark.asyncio
async def test_plug_in_mid_slot_acts_next_tick(temp_schedule, temp_db):
    plug = {"ev1": "off"}
    eng = _engine(temp_schedule, temp_db, [_charger()], plug)
    first = eng._gate_ev_plan_on_plug_state(_slot(), await eng._read_ev_plug_states())
    assert eng._charger_should_be_on(first, "ev1") is False
    plug["ev1"] = "on"
    second = eng._gate_ev_plan_on_plug_state(_slot(), await eng._read_ev_plug_states())
    assert eng._charger_should_be_on(second, "ev1") is True


@pytest.mark.asyncio
async def test_unknown_plug_state_is_not_actionable(temp_schedule, temp_db):
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "unavailable"})
    states = await eng._read_ev_plug_states()
    assert states["ev1"] == "unknown"
    gated = eng._gate_ev_plan_on_plug_state(
        _slot(keep_on={"ev1": True}, surplus={"ev1": 3.0}), states
    )
    assert gated.ev_keep_on["ev1"] is False
    assert gated.ev_surplus_kw["ev1"] == 0.0
    assert eng._charger_should_be_on(gated, "ev1") is False


@pytest.mark.asyncio
async def test_only_unplugged_charger_is_gated(temp_schedule, temp_db):
    eng = _engine(
        temp_schedule, temp_db, [_charger("ev1"), _charger("ev2")], {"ev1": "off", "ev2": "on"}
    )
    gated = eng._gate_ev_plan_on_plug_state(
        _slot(total=10.0, plans={"ev1": 7.0, "ev2": 3.0}), await eng._read_ev_plug_states()
    )
    assert gated.ev_charger_plans == {"ev1": 0.0, "ev2": 3.0}
    assert gated.ev_charging_kw == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_charger_without_plug_sensor_counts_as_plugged(temp_schedule, temp_db):
    eng = _engine(temp_schedule, temp_db, [_charger(plug_sensor=None)], {})
    slot = _slot()
    assert eng._gate_ev_plan_on_plug_state(slot, await eng._read_ev_plug_states()) is slot


@pytest.mark.asyncio
async def test_manual_charge_unaffected_by_gate(temp_schedule, temp_db):
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"})
    gated = eng._gate_ev_plan_on_plug_state(_slot(), await eng._read_ev_plug_states())
    with patch.object(eng, "_ev_manual_charge_active", return_value=True):
        assert eng._charger_should_be_on(gated, "ev1") is True


# --- 7.4 plug-in reminder ---


def _write_schedule(path: str, start: datetime, kw: float = 7.0, charger: str = "ev1") -> None:
    slots = []
    for i in range(12):
        s = start + timedelta(minutes=15 * (i - 4))
        slots.append(
            {
                "start_time": s.isoformat(),
                "end_time": (s + timedelta(minutes=15)).isoformat(),
                "ev_chargers": {charger: kw if i >= 4 else 0.0},
            }
        )
    Path(path).write_text(json.dumps({"schedule": slots, "meta": {}}))


@pytest.mark.asyncio
async def test_reminder_sent_once_within_lead(temp_schedule, temp_db):
    start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, start)
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"}, 30)
    states = await eng._read_ev_plug_states()

    await eng._check_plug_in_reminders(start - timedelta(minutes=45), states)
    eng.dispatcher.notify_plug_in_reminder.assert_not_awaited()

    for minute in (30, 20, 10, 1):
        await eng._check_plug_in_reminders(start - timedelta(minutes=minute), states)

    eng.dispatcher.notify_plug_in_reminder.assert_awaited_once_with(
        "Go-e: charging planned at 22:00 but the car isn't plugged in"
    )


@pytest.mark.asyncio
async def test_no_reminder_when_plugged(temp_schedule, temp_db):
    start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, start)
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "on"}, 30)
    await eng._check_plug_in_reminders(start - timedelta(minutes=10), await eng._read_ev_plug_states())
    eng.dispatcher.notify_plug_in_reminder.assert_not_awaited()


@pytest.mark.asyncio
async def test_reminder_disabled(temp_schedule, temp_db):
    start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, start)
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"})
    await eng._check_plug_in_reminders(start - timedelta(minutes=1), await eng._read_ev_plug_states())
    eng.dispatcher.notify_plug_in_reminder.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_window_renotifies(temp_schedule, temp_db):
    first = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, first)
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"}, 30)
    states = await eng._read_ev_plug_states()
    await eng._check_plug_in_reminders(first - timedelta(minutes=10), states)

    # A replan moves charging to 02:00.
    second = TZ.localize(datetime(2026, 9, 26, 2, 0))
    _write_schedule(temp_schedule, second)
    await eng._check_plug_in_reminders(second - timedelta(minutes=30), states)

    assert eng.dispatcher.notify_plug_in_reminder.await_count == 2
    assert "02:00" in eng.dispatcher.notify_plug_in_reminder.await_args.args[0]


@pytest.mark.asyncio
async def test_plugging_in_resets_dedupe(temp_schedule, temp_db):
    start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, start)
    plug = {"ev1": "off"}
    eng = _engine(temp_schedule, temp_db, [_charger()], plug, 30)
    await eng._check_plug_in_reminders(start - timedelta(minutes=10), await eng._read_ev_plug_states())
    plug["ev1"] = "on"
    await eng._check_plug_in_reminders(start - timedelta(minutes=5), await eng._read_ev_plug_states())
    plug["ev1"] = "off"
    await eng._check_plug_in_reminders(start - timedelta(minutes=2), await eng._read_ev_plug_states())
    assert eng.dispatcher.notify_plug_in_reminder.await_count == 2


@pytest.mark.asyncio
async def test_global_lead_time_applies_to_every_charger(temp_schedule, temp_db):
    start = TZ.localize(datetime(2026, 9, 25, 22, 0))
    _write_schedule(temp_schedule, start)
    eng = _engine(temp_schedule, temp_db, [_charger()], {"ev1": "off"}, 15)
    states = await eng._read_ev_plug_states()
    await eng._check_plug_in_reminders(start - timedelta(minutes=20), states)
    eng.dispatcher.notify_plug_in_reminder.assert_not_awaited()
    await eng._check_plug_in_reminders(start - timedelta(minutes=15), states)
    eng.dispatcher.notify_plug_in_reminder.assert_awaited_once()


def test_config_parses_global_plug_in_reminder(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "executor:\n  enabled: true\n  notifications:\n"
        "    on_ev_plug_in_reminder: true\n    ev_plug_in_reminder_minutes: 15\n"
    )
    notif = load_executor_config(str(cfg)).notifications
    assert notif.on_ev_plug_in_reminder is True
    assert notif.ev_plug_in_reminder_minutes == 15


@pytest.mark.parametrize("raw", ["soon", 0, 5000])
def test_config_invalid_lead_time_uses_default(tmp_path, raw):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "executor:\n  notifications:\n    on_ev_plug_in_reminder: true\n"
        f"    ev_plug_in_reminder_minutes: {raw}\n"
    )
    assert load_executor_config(str(cfg)).notifications.ev_plug_in_reminder_minutes == 30


def test_config_defaults_reminder_off(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("executor:\n  enabled: true\n")
    notif = load_executor_config(str(cfg)).notifications
    assert notif.on_ev_plug_in_reminder is False
    assert notif.ev_plug_in_reminder_minutes == 30
