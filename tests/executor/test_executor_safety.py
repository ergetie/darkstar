"""
Tests for executor safety hardening (harden-executor-safety change).

Covers:
- Manual override suppresses all inverter/EV/water writes (tasks 2.x)
- EV charger obeys force_stop and manual override (tasks 3.x)
- Stale-schedule freshness check triggers hold + alert (tasks 4.x)
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz

from executor.actions import ActionDispatcher, ActionResult, HAClient
from executor.config import (
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ExecutorEngine


def _make_schedule(slots: list, generated_at: datetime | None = None, tz_name: str = "Europe/Stockholm") -> dict:
    tz = pytz.timezone(tz_name)
    ts = generated_at if generated_at is not None else datetime.now(tz)
    return {"schedule": slots, "meta": {"generated_at": ts.isoformat()}}


def _make_slot(start: datetime, charge_kw: float = 0, soc_target: int = 50, ev_charging_kw: float = 0) -> dict:
    end = start + timedelta(minutes=15)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "end_time_kepler": end.isoformat(),
        "battery_charge_kw": charge_kw,
        "battery_discharge_kw": 0,
        "export_kwh": 0,
        "water_heating_kw": 0,
        "soc_target_percent": soc_target,
        "projected_soc_percent": soc_target - 5,
        "ev_charging_kw": ev_charging_kw,
    }


@pytest.fixture
def temp_schedule(tmp_path):
    path = tmp_path / "schedule.json"
    path.write_text("{}")
    return str(path)


@pytest.fixture
def temp_db(tmp_path):
    from sqlalchemy import create_engine as sa_engine
    from backend.learning.models import Base
    db_path = str(tmp_path / "test.db")
    engine = sa_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return db_path


def _make_engine(temp_schedule, temp_db, *, manual_override_entity=None, ev_chargers=None, max_schedule_age_hours=6):
    config = ExecutorConfig(
        enabled=True,
        schedule_path=temp_schedule,
        timezone="Europe/Stockholm",
        automation_toggle_entity="input_boolean.automation",
        manual_override_entity=manual_override_entity,
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        ev_chargers=ev_chargers or [],
        max_schedule_age_hours=max_schedule_age_hours,
    )
    with patch("executor.engine.load_executor_config", return_value=config), \
         patch("executor.engine.load_yaml", return_value={"input_sensors": {}}), \
         patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
        eng = ExecutorEngine("config.yaml")

    mock_ha = MagicMock(spec=HAClient)

    def _state(entity_id):
        if "override" in entity_id:
            return eng._manual_override_state
        if "automation" in entity_id:
            return "on"
        if "soc" in entity_id:
            return "50"
        if "temp" in entity_id or "target" in entity_id:
            return "55"
        return "0.0"

    mock_ha.get_state_value.side_effect = _state
    mock_ha.set_select_option.return_value = True
    mock_ha.set_switch.return_value = True
    mock_ha.set_number.return_value = True
    mock_ha.set_input_number.return_value = True
    eng.ha_client = mock_ha
    eng._manual_override_state = "off"
    eng.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)
    return eng


@pytest.mark.asyncio
class TestManualOverrideSuppressesWrites:
    """Manual override must not write to inverter/EV/water (task 2.x)."""

    async def test_manual_override_active_skips_dispatcher_execute(self, temp_schedule, temp_db):
        """When manual override is on, dispatcher.execute is never called."""
        eng = _make_engine(temp_schedule, temp_db, manual_override_entity="input_boolean.override")
        eng._manual_override_state = "on"

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)])
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_execute = AsyncMock(return_value=[])
        eng.dispatcher.execute = mock_execute

        result = await eng.run_once()

        assert result["success"] is True
        mock_execute.assert_not_called()

    async def test_manual_override_active_still_records_history(self, temp_schedule, temp_db):
        """Execution history is logged even when manual override is active."""
        eng = _make_engine(temp_schedule, temp_db, manual_override_entity="input_boolean.override")
        eng._manual_override_state = "on"

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)])
        Path(temp_schedule).write_text(json.dumps(schedule))

        await eng.run_once()

        records = eng.history.get_history()
        assert len(records) >= 1

    async def test_manual_override_inactive_allows_writes(self, temp_schedule, temp_db):
        """When manual override is off, dispatcher.execute is called normally."""
        eng = _make_engine(temp_schedule, temp_db, manual_override_entity="input_boolean.override")
        eng._manual_override_state = "off"

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)])
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_execute = AsyncMock(return_value=[
            ActionResult(action_type="work_mode", success=True, message="ok")
        ])
        eng.dispatcher.execute = mock_execute

        result = await eng.run_once()

        assert result["success"] is True
        mock_execute.assert_called_once()


@pytest.mark.asyncio
class TestEVChargerOverrideControl:
    """EV charger obeys manual override and force_stop (task 3.x)."""

    def _make_ev_engine(self, temp_schedule, temp_db, manual_override_on=False):
        charger = EVChargerDeviceConfig(
            id="charger1",
            switch_entity="switch.ev_charger",
        )
        eng = _make_engine(
            temp_schedule, temp_db,
            manual_override_entity="input_boolean.override",
            ev_chargers=[charger],
        )
        eng._has_ev_charger = True
        eng._manual_override_state = "on" if manual_override_on else "off"
        return eng

    async def test_force_stop_turns_off_planned_ev_charge(self, temp_schedule, temp_db):
        """force_stop quick action commands EV charger off even if slot plans charging."""
        eng = self._make_ev_engine(temp_schedule, temp_db)
        eng.set_quick_action("force_stop", 15)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        slot_data = _make_slot(slot_start, ev_charging_kw=7.4)
        slot_data["ev_chargers"] = {"charger1": 7.4}
        schedule = _make_schedule([slot_data])
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_ha = eng.ha_client
        mock_ha.get_state_value.side_effect = lambda eid: (
            "on" if eid == "switch.ev_charger" else
            "off" if "override" in eid else  # override entity is OFF (no manual override)
            "on" if "automation" in eid or "input_boolean" in eid else
            "50" if "soc" in eid else
            "55" if "temp" in eid else "0.0"
        )

        mock_set_ev = AsyncMock(return_value=ActionResult(
            action_type="ev_charger_switch", success=True, message="off"
        ))
        eng.dispatcher.set_ev_charger_switch = mock_set_ev

        mock_execute = AsyncMock(return_value=[])
        eng.dispatcher.execute = mock_execute

        await eng.run_once()

        # Charger should have been commanded OFF
        mock_set_ev.assert_called_once()
        call_kwargs = mock_set_ev.call_args
        assert call_kwargs.kwargs.get("turn_on") is False or call_kwargs.args[1] is False

    async def test_manual_override_skips_ev_charger_entirely(self, temp_schedule, temp_db):
        """Manual override active: EV charger switch is never touched."""
        eng = self._make_ev_engine(temp_schedule, temp_db, manual_override_on=True)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        slot_data = _make_slot(slot_start, ev_charging_kw=7.4)
        slot_data["ev_chargers"] = {"charger1": 7.4}
        schedule = _make_schedule([slot_data])
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_set_ev = AsyncMock(return_value=ActionResult(
            action_type="ev_charger_switch", success=True, message="ok"
        ))
        eng.dispatcher.set_ev_charger_switch = mock_set_ev

        await eng.run_once()

        mock_set_ev.assert_not_called()

    async def test_normal_operation_follows_ev_plan(self, temp_schedule, temp_db):
        """No override and no force_stop: EV charger follows the slot plan."""
        eng = self._make_ev_engine(temp_schedule, temp_db, manual_override_on=False)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        slot_data = _make_slot(slot_start, ev_charging_kw=7.4)
        slot_data["ev_chargers"] = {"charger1": 7.4}
        schedule = _make_schedule([slot_data])
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_ha = eng.ha_client
        mock_ha.get_state_value.side_effect = lambda eid: (
            "off" if eid == "switch.ev_charger" else
            "off" if "override" in eid else  # override entity is OFF (no manual override)
            "on" if "automation" in eid or "input_boolean" in eid else
            "50" if "soc" in eid else
            "55" if "temp" in eid else "0.0"
        )

        mock_set_ev = AsyncMock(return_value=ActionResult(
            action_type="ev_charger_switch", success=True, message="on"
        ))
        eng.dispatcher.set_ev_charger_switch = mock_set_ev
        eng.dispatcher.execute = AsyncMock(return_value=[])

        await eng.run_once()

        # Charger should have been commanded ON per the plan
        mock_set_ev.assert_called_once()
        call_kwargs = mock_set_ev.call_args
        assert call_kwargs.kwargs.get("turn_on") is True or call_kwargs.args[1] is True


@pytest.mark.asyncio
class TestStaleScheduleFreshnessCheck:
    """Stale schedule triggers hold + alert (task 4.x)."""

    async def test_stale_schedule_fires_alert_and_holds(self, temp_schedule, temp_db):
        """Schedule older than max_schedule_age_hours triggers notify_error + hold fallback.

        The planned charge from the stale slot must NOT be applied — only idle/hold settings.
        """
        eng = _make_engine(temp_schedule, temp_db, max_schedule_age_hours=6)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # Generated 8 hours ago — stale
        generated_at = now - timedelta(hours=8)
        slot_start = now - timedelta(minutes=5)

        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)], generated_at=generated_at)
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_notify = AsyncMock()
        eng.dispatcher.notify_error = mock_notify

        executed_decisions = []
        orig_execute = eng.dispatcher.execute

        async def capture_execute(decision):
            executed_decisions.append(decision)
            return []

        eng.dispatcher.execute = capture_execute

        result = await eng.run_once()

        assert result["success"] is True
        # Alert must be fired
        mock_notify.assert_called_once()
        assert "stale" in mock_notify.call_args.args[0].lower()
        # The hold fallback ran — decision source is 'override', mode is 'idle' (not 'charge')
        assert executed_decisions, "dispatcher.execute should have been called with hold decision"
        decision = executed_decisions[0]
        assert decision.source == "override"
        assert decision.mode_intent == "idle"

    async def test_fresh_schedule_executes_normally(self, temp_schedule, temp_db):
        """Schedule within max_schedule_age_hours executes as planned."""
        eng = _make_engine(temp_schedule, temp_db, max_schedule_age_hours=6)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        generated_at = now - timedelta(hours=1)
        slot_start = now - timedelta(minutes=5)

        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)], generated_at=generated_at)
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_execute = AsyncMock(return_value=[
            ActionResult(action_type="work_mode", success=True, message="ok")
        ])
        eng.dispatcher.execute = mock_execute

        result = await eng.run_once()

        assert result["success"] is True
        mock_execute.assert_called_once()

    async def test_stale_alert_fires_only_once_per_stale_period(self, temp_schedule, temp_db):
        """Stale-schedule alert is deduplicated: fires once on transition, not every tick."""
        eng = _make_engine(temp_schedule, temp_db, max_schedule_age_hours=6)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        stale_at = now - timedelta(hours=8)
        fresh_at = now - timedelta(hours=1)

        stale_schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)], generated_at=stale_at)
        fresh_schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)], generated_at=fresh_at)

        notify_calls = []
        async def mock_notify(msg):
            notify_calls.append(msg)
        eng.dispatcher.notify_error = mock_notify
        eng.dispatcher.execute = AsyncMock(return_value=[])

        # Three ticks with stale schedule — alert should fire exactly once
        Path(temp_schedule).write_text(json.dumps(stale_schedule))
        for _ in range(3):
            await eng.run_once()
        assert len(notify_calls) == 1, f"Expected 1 alert over 3 stale ticks, got {len(notify_calls)}"

        # One tick with fresh schedule — re-arms without firing
        Path(temp_schedule).write_text(json.dumps(fresh_schedule))
        await eng.run_once()
        assert len(notify_calls) == 1

        # Two more ticks with stale schedule — alert fires once more (re-armed)
        Path(temp_schedule).write_text(json.dumps(stale_schedule))
        for _ in range(2):
            await eng.run_once()
        assert len(notify_calls) == 2, f"Expected 2 alerts total after re-arm, got {len(notify_calls)}"

    async def test_default_max_age_is_6_hours(self, temp_schedule, temp_db):
        """When max_schedule_age_hours is not configured, default of 6h is used."""
        # Default ExecutorConfig has max_schedule_age_hours=6
        eng = _make_engine(temp_schedule, temp_db)
        assert eng.config.max_schedule_age_hours == 6

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # 5h 59min old — should NOT be stale under 6h default
        generated_at = now - timedelta(hours=5, minutes=59)
        slot_start = now - timedelta(minutes=5)

        schedule = _make_schedule([_make_slot(slot_start, charge_kw=5.0)], generated_at=generated_at)
        Path(temp_schedule).write_text(json.dumps(schedule))

        mock_execute = AsyncMock(return_value=[
            ActionResult(action_type="work_mode", success=True, message="ok")
        ])
        eng.dispatcher.execute = mock_execute

        await eng.run_once()

        # Should have executed (not held)
        mock_execute.assert_called_once()
