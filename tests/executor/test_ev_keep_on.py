"""
Tests for keep-on-slot-flag: executor honors ev_keep_on when planned kW is 0.

Covers tasks 3.1-3.5: binary switch-close, current-type minimum-current
target (both via the load balancer input and the no-balancer fallback path),
battery source isolation, backward compat, and status API exposure.
"""

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
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    LoadBalancingConfig,
)
from executor.controller import make_decision
from executor.engine import EVChargerState, ExecutorEngine
from executor.override import SlotPlan, SystemState


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        schedule_path = f.name
    yield schedule_path
    with contextlib.suppress(OSError):
        Path(schedule_path).unlink()


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_schedule(slots: list, timezone: str = "Europe/Stockholm") -> dict:
    return {
        "schedule": slots,
        "meta": {"generated_at": datetime.now(pytz.timezone(timezone)).isoformat()},
    }


def make_binary_engine(temp_schedule, temp_db) -> ExecutorEngine:
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=[EVChargerDeviceConfig(id="ev1", switch_entity="switch.ev1")],
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                eng = ExecutorEngine("config.yaml")
                eng._has_ev_charger = True
                return eng


def make_current_engine(
    temp_schedule, temp_db, charger: EVChargerDeviceConfig, load_balancing=None
) -> ExecutorEngine:
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule,
            timezone="Europe/Stockholm",
            ev_chargers=[charger],
            load_balancing=load_balancing or LoadBalancingConfig(),
        )
        with patch("executor.engine.load_yaml") as mock_yaml:
            mock_yaml.return_value = {}
            with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                eng = ExecutorEngine("config.yaml")
                eng._has_ev_charger = True
                return eng


class TestBinaryChargerKeepOnClosesSwitch:
    """Task 3.1: binary charger — keep-on with 0 planned kW commands the switch ON."""

    @pytest.mark.asyncio
    async def test_switch_commanded_on_for_keep_on_only_slot(self, temp_schedule, temp_db):
        engine = make_binary_engine(temp_schedule, temp_db)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="off")

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="switch",
            message="ok",
            entity_id="switch.ev1",
            previous_value="off",
            new_value="on",
            verified_value="on",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=mock_result)

        slot = SlotPlan(ev_charger_plans={"ev1": 0.0}, ev_keep_on={"ev1": True})
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(slot, now)

        engine.dispatcher.set_ev_charger_switch.assert_called_once_with(
            "switch.ev1", turn_on=True, charging_kw=0.0
        )
        assert engine._ev_charger_states["ev1"].charging_active is True

    @pytest.mark.asyncio
    async def test_switch_stays_off_without_keep_on_or_plan(self, temp_schedule, temp_db):
        """Sanity check: no plan and no keep-on flag → switch is not commanded on."""
        engine = make_binary_engine(temp_schedule, temp_db)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="off")
        engine.dispatcher = AsyncMock()

        slot = SlotPlan(ev_charger_plans={"ev1": 0.0}, ev_keep_on={"ev1": False})
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(slot, now)

        engine.dispatcher.set_ev_charger_switch.assert_not_called()


class TestCurrentChargerKeepOnMinimumCurrent:
    """Task 3.2: current-type charger keep-on → minimum current target, relay commanded."""

    def test_load_balancer_input_uses_configured_minimum(self, temp_schedule, temp_db):
        """_run_load_balancer's planner_target_a for a keep-on-only charger is the
        charger's configured min_current_a (8, a non-default value), not hardcoded 6."""
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=8,
            max_current_a=16,
            phases=[1, 2, 3],
        )
        engine = make_current_engine(
            temp_schedule,
            temp_db,
            charger,
            load_balancing=LoadBalancingConfig(enabled=True, main_fuse_a=32),
        )

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        state = SystemState(
            grid_current_a={1: 0.0, 2: 0.0, 3: 0.0},
            grid_current_updated_at={1: now, 2: now, 3: now},
        )
        slot = SlotPlan(ev_charger_plans={"goe": 0.0}, ev_keep_on={"goe": True})

        status = engine._run_load_balancer(state, slot, now)

        assert engine._last_balancer_planned_targets["goe"] == 8
        assert status.enabled is True
        assert len(status.ev_outputs) == 1
        # Fresh charger, ample headroom: balancer commands the floor directly.
        assert status.ev_outputs[0].target_a == 8

    @pytest.mark.asyncio
    async def test_relay_commanded_at_minimum_current_without_balancer(self, temp_schedule, temp_db):
        """No load balancer configured: _control_ev_charger's no-override path still
        commands the charger's configured minimum current for a keep-on-only slot."""
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=8,
            max_current_a=16,
            phases=[1, 2, 3],
        )
        engine = make_current_engine(temp_schedule, temp_db, charger)
        engine.ha_client = AsyncMock()
        engine.ha_client.get_state = AsyncMock(return_value=None)  # no phase sensors configured

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="ev_charge_current",
            message="ok",
            entity_id="number.goe_current",
            previous_value="0",
            new_value=8,
            verified_value="8",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(return_value=mock_result)

        slot = SlotPlan(ev_charger_plans={"goe": 0.0}, ev_keep_on={"goe": True})
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(slot, now)

        engine.dispatcher.set_ev_charger_current.assert_called_once_with(
            "number.goe_current", 8
        )
        assert engine._ev_charger_states["goe"].current_setpoint_a == 8


class TestKeepOnBlocksBatteryDischarge:
    """Task 3.3: keep-on slot with 0 measured EV power blocks battery discharge via
    source isolation (controller mode_intent, matching engine._follow_plan)."""

    def test_keep_on_forces_idle_over_self_consumption(self):
        state = SystemState(current_soc_percent=65.0, min_soc_percent=10.0)
        slot = SlotPlan(
            discharge_kw=0.0,  # engine's isolation path already blocks discharge
            ev_charging_kw=0.0,
            ev_keep_on={"ev1": True},
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(slot, state, None, ControllerConfig(), InverterConfig(), None, None)

        assert decision.mode_intent == "idle"

    def test_no_keep_on_and_no_ev_power_allows_self_consumption(self):
        """Sanity: without keep-on or measured power, SoC above target → self_consumption."""
        state = SystemState(current_soc_percent=65.0, min_soc_percent=10.0)
        slot = SlotPlan(
            discharge_kw=3.0,
            ev_charging_kw=0.0,
            ev_keep_on={},
            soc_target=60,
            soc_projected=65,
        )

        decision = make_decision(slot, state, None, ControllerConfig(), InverterConfig(), None, None)

        assert decision.mode_intent == "self_consumption"


class TestParseSlotPlanBackwardCompat:
    """Task 3.4: slot without ev_keep_on key parses to empty flags (backward compat)."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule, timezone="Europe/Stockholm"
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_missing_ev_keep_on_key_parses_empty(self, engine):
        slot_data = {"soc_target_percent": 50, "ev_charging_kw": 7.4}
        slot = engine._parse_slot_plan(slot_data)

        assert slot.ev_keep_on == {}

    def test_charger_should_be_on_falls_back_to_planned_power(self, engine):
        slot = SlotPlan(ev_charger_plans={"ev1": 7.4}, ev_keep_on={})
        assert engine._charger_should_be_on(slot, "ev1") is True

        slot_off = SlotPlan(ev_charger_plans={"ev1": 0.0}, ev_keep_on={})
        assert engine._charger_should_be_on(slot_off, "ev1") is False


class TestGetStatusExposesKeepOn:
    """Task 3.5: get_status().current_slot_plan.ev_keep_on returns the flag dict."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule, timezone="Europe/Stockholm"
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_get_status_includes_ev_keep_on(self, engine, temp_schedule):
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        end = slot_start + timedelta(minutes=15)

        slot = {
            "start_time": slot_start.isoformat(),
            "end_time": end.isoformat(),
            "end_time_kepler": end.isoformat(),
            "battery_charge_kw": 0.0,
            "battery_discharge_kw": 0.0,
            "export_kwh": 0.0,
            "water_heating_kw": 0.0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            "ev_charging_kw": 0.0,
            "ev_chargers": {"ev1": 0.0},
            "ev_keep_on": {"ev1": True},
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        engine._last_system_state = SystemState(current_soc_percent=50.0)
        engine.inverter_profile = None

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert status["current_slot_plan"]["ev_keep_on"] == {"ev1": True}


class TestPhaseModeUsesSharedShouldBeOnPredicate:
    """Verify fix from opsx:verify: phase-mode target selection derives
    keep-on-only status from the shared `_charger_should_be_on` predicate
    (previously reimplemented inline, risking divergence from the other two
    decision sites)."""

    @pytest.mark.asyncio
    async def test_keep_on_only_targets_one_phase_minimum(self, temp_schedule, temp_db):
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=8,
            max_current_a=16,
            phases=[1, 2, 3],
            phase_switching_enabled=True,
            phase_mode_entity="select.goe_phase_mode",
        )
        engine = make_current_engine(temp_schedule, temp_db, charger)
        engine.dispatcher = AsyncMock()

        state = SystemState(current_export_kw=0.0, current_import_kw=0.0)
        slot = SlotPlan(ev_charger_plans={"goe": 0.0}, ev_keep_on={"goe": True})

        with patch.object(
            engine, "_apply_phase_mode_decision", AsyncMock(return_value=None)
        ) as mock_apply:
            await engine._update_ev_surplus_and_phase_mode(state, slot, datetime.now(pytz.UTC))

        mock_apply.assert_called_once()
        call_args = mock_apply.call_args
        target_power_kw = call_args[0][2]
        # one_phase_min_kw(8) == 8 * 230 / 1000 == 1.84
        assert target_power_kw == pytest.approx(1.84)

    @pytest.mark.asyncio
    async def test_genuinely_planned_charging_targets_planned_kw(self, temp_schedule, temp_db):
        """Sanity check: real planned power (not keep-on) still uses the plan
        value directly, unaffected by the shared-predicate refactor."""
        charger = EVChargerDeviceConfig(
            id="goe",
            type="current",
            current_entity="number.goe_current",
            min_current_a=8,
            max_current_a=16,
            phases=[1, 2, 3],
            phase_switching_enabled=True,
            phase_mode_entity="select.goe_phase_mode",
        )
        engine = make_current_engine(temp_schedule, temp_db, charger)
        engine.dispatcher = AsyncMock()

        state = SystemState(current_export_kw=0.0, current_import_kw=0.0)
        slot = SlotPlan(ev_charger_plans={"goe": 5.0}, ev_keep_on={})

        with patch.object(
            engine, "_apply_phase_mode_decision", AsyncMock(return_value=None)
        ) as mock_apply:
            await engine._update_ev_surplus_and_phase_mode(state, slot, datetime.now(pytz.UTC))

        target_power_kw = mock_apply.call_args[0][2]
        assert target_power_kw == 5.0


class TestEvReasonNoteBatteryless:
    """Verify fix from opsx:verify: the keep-on reason-text marker is no
    longer gated on _has_battery, so battery-less systems still surface it
    in the tick's reason text (previously only isolation, which requires a
    battery, could ever append the marker)."""

    def test_isolating_with_keep_on_appends_marker(self):
        note = ExecutorEngine._build_ev_reason_note(
            True, ev_charging_kw=0.0, actual_ev_power_kw=0.0, keep_on_charger_ids=["ev1"]
        )
        assert note == "EV source isolation: 0.0kW scheduled, 0.00kW actual | EV keep-on active: ev1"

    def test_isolating_without_keep_on_no_marker(self):
        note = ExecutorEngine._build_ev_reason_note(
            True, ev_charging_kw=2.0, actual_ev_power_kw=1.5, keep_on_charger_ids=[]
        )
        assert note == "EV source isolation: 2.0kW scheduled, 1.50kW actual"
        assert "keep-on" not in note.lower()

    def test_not_isolating_with_keep_on_still_surfaces_marker(self):
        """The battery-less case: isolation never triggers (no battery to
        isolate), but keep-on is active — the reason text must still name it."""
        note = ExecutorEngine._build_ev_reason_note(
            False, ev_charging_kw=0.0, actual_ev_power_kw=0.0, keep_on_charger_ids=["ev1", "ev2"]
        )
        assert note == "EV keep-on active: ev1, ev2"

    def test_not_isolating_without_keep_on_returns_none(self):
        note = ExecutorEngine._build_ev_reason_note(
            False, ev_charging_kw=0.0, actual_ev_power_kw=0.0, keep_on_charger_ids=[]
        )
        assert note is None
