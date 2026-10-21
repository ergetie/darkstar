"""battery-load-balancing 3.x: engine integration of the battery give-way
entry (input building, cap application, replan, notification gating and the
status payload) with synthetic state and statuses (no HA, no full tick)."""

import contextlib
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    GiveWayOrderEntry,
    InverterConfig,
    LoadBalancingConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.controller import ControllerDecision
from executor.engine import ExecutorEngine
from executor.load_balancer import BatteryBalancerOutput, LoadBalancerStatus
from executor.override import SystemState
from executor.profiles import load_profile
from tests.executor.fake_relief import InstantRelief

TZ = pytz.timezone("Europe/Stockholm")
T0 = TZ.localize(datetime(2026, 6, 1, 12, 0, 0))


@pytest.fixture
def engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(db_engine)

    config = ExecutorConfig(
        enabled=True,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(nominal_voltage_v=48.0),
        load_balancing=LoadBalancingConfig(
            enabled=True,
            main_fuse_a=20,
            nominal_voltage_v=230.0,
            notify_interventions=True,
            give_way_order=[GiveWayOrderEntry(kind="battery", id="battery")],
        ),
    )

    with (
        patch("executor.engine.load_executor_config", return_value=config),
        patch(
            "executor.engine.load_yaml",
            return_value={"automation": {"schedule": {"every_minutes": 60}}},
        ),
        patch.object(ExecutorEngine, "_get_db_path", return_value=db_path),
    ):
        eng = ExecutorEngine("config.yaml")

    eng.inverter_profile = load_profile("deye")
    yield eng
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def battery_status(planned_w, cap_w, state, enabled=True):
    return LoadBalancerStatus(
        enabled=enabled,
        state=state,
        reason="test",
        main_fuse_a=20,
        phase_current_a={1: 24.0, 2: 16.0, 3: 16.0},
        phase_headroom_a={1: -4.0, 2: 4.0, 3: 4.0},
        battery_output=BatteryBalancerOutput(planned_w, cap_w, state, "battery reason"),
    )


def charge_decision(charge_value):
    return ControllerDecision(mode_intent="charge", charge_value=charge_value, reason="plan")


def _state(import_kw=10.0, battery_charge_kw=None):
    now = T0
    return SystemState(
        current_import_kw=import_kw,
        current_battery_charge_kw=battery_charge_kw,
        grid_current_a={1: 24.0, 2: 16.0, 3: 16.0},
        grid_current_updated_at={1: now, 2: now, 3: now},
    )


class TestCapApplication:
    def test_deye_amps_cap_rounds_down_to_step(self, engine):
        decision = charge_decision(185.0)
        engine._apply_battery_cap(decision, battery_status(8880.0, 7200.0, "throttling"))
        assert decision.mode_intent == "charge"
        assert decision.charge_value == 150.0
        assert engine._battery_cap_w == pytest.approx(150.0 * 48.0)
        assert "Load balancer" in decision.reason

    def test_deye_below_minimum_dispatches_idle(self, engine):
        decision = charge_decision(185.0)
        engine._apply_battery_cap(decision, battery_status(8880.0, 400.0, "throttling"))
        assert decision.mode_intent == "idle"
        assert engine._battery_cap_w == 0.0

    def test_below_minimum_reports_paused_in_status(self, engine):
        decision = charge_decision(185.0)
        status = battery_status(8880.0, 400.0, "throttling")
        engine._apply_battery_cap(decision, status)
        assert status.battery_output.state == "paused"
        assert status.battery_output.cap_w == 0.0

    def test_minimum_not_multiple_of_step_dispatches_minimum(self, engine):
        engine.inverter_profile.behavior.min_charge_a = 12.0
        decision = charge_decision(185.0)
        # 13 A rounds down to 10 A (step 5), below the 12 A minimum, but the
        # cap itself fits the minimum: dispatch 12 A instead of pausing.
        engine._apply_battery_cap(decision, battery_status(8880.0, 13.0 * 48.0, "throttling"))
        assert decision.mode_intent == "charge"
        assert decision.charge_value == 12.0

    def test_paused_dispatches_idle(self, engine):
        decision = charge_decision(185.0)
        engine._apply_battery_cap(decision, battery_status(8880.0, 0.0, "paused"))
        assert decision.mode_intent == "idle"

    def test_fronius_watts_cap(self, engine):
        engine.inverter_profile = load_profile("fronius")
        decision = charge_decision(10000.0)
        engine._apply_battery_cap(decision, battery_status(10000.0, 7240.0, "throttling"))
        assert decision.mode_intent == "charge"
        assert decision.charge_value == 7200.0
        assert engine._battery_cap_w == 7200.0

    def test_uncapped_leaves_decision(self, engine):
        decision = charge_decision(185.0)
        engine._battery_cap_w = 5000.0
        engine._apply_battery_cap(decision, battery_status(8880.0, 8880.0, "idle"))
        assert decision.charge_value == 185.0
        assert not decision.urgent_reduction

    def test_cap_state_is_kept_at_the_plan_so_a_plan_rise_ramps(self, engine):
        """Cap equal to the plan is not cleared: when the plan then rises, the
        applied cap starts from the old level instead of jumping to the plan."""
        decision = charge_decision(62.5)  # 3 kW at 48 V
        engine._apply_battery_cap(decision, battery_status(3000.0, 3000.0, "idle"))
        assert engine._battery_cap_w == 3000.0
        rise = charge_decision(125.0)  # plan now 6 kW
        inp = engine._battery_balancer_input(_state(import_kw=0.0), rise)
        assert inp.planned_w == pytest.approx(6000.0)
        assert inp.applied_cap_w == pytest.approx(3000.0)

    def test_cap_state_dropped_when_not_charging(self, engine):
        engine._battery_cap_w = 3000.0
        decision = ControllerDecision(mode_intent="idle", charge_value=0.0)
        engine._apply_battery_cap(decision, battery_status(0.0, 0.0, "idle"))
        assert engine._battery_cap_w is None

    def test_cut_is_flagged_urgent_for_the_write_layer(self, engine):
        decision = charge_decision(185.0)
        status = battery_status(8880.0, 7200.0, "throttling")
        status.battery_output.urgent = True
        engine._apply_battery_cap(decision, status)
        assert decision.urgent_reduction

    def test_non_charge_intent_untouched(self, engine):
        decision = ControllerDecision(mode_intent="self_consumption", charge_value=185.0)
        engine._apply_battery_cap(decision, battery_status(8880.0, 0.0, "paused"))
        assert decision.mode_intent == "self_consumption"


class TestBalancerInput:
    def test_reported_scenario_end_to_end(self, engine):
        """Deye 185 A (8.88 kW) grid charge, L1 at 24 A on a 20 A fuse."""
        engine._load_balancer._relief_trigger = InstantRelief(engine.config.load_balancing)
        engine._battery_cap_w = 8880.0
        decision = charge_decision(185.0)
        status = engine._run_load_balancer(_state(), None, T0, decision)
        assert status.battery_output is not None
        assert status.battery_output.state == "throttling"
        assert status.battery_output.cap_w == pytest.approx(8880.0 - 4 * 230 * 3)
        engine._apply_battery_cap(decision, status)
        # 6120 W / 48 V = 127.5 A -> 125 A
        assert decision.charge_value == 125.0

    def test_reducible_ignores_lagging_measured_charge(self, engine):
        """A measured charge below the cap must not shrink what a cut may use."""
        engine._battery_cap_w = 8880.0
        inp = engine._battery_balancer_input(
            _state(import_kw=10.0, battery_charge_kw=2.0), charge_decision(185.0)
        )
        assert inp.reducible_w == pytest.approx(8880.0)
        assert inp.measured_w == pytest.approx(2000.0)
        assert inp.min_w == pytest.approx(480.0)

    def test_self_consumption_inactive(self, engine):
        inp = engine._battery_balancer_input(
            _state(), ControllerDecision(mode_intent="self_consumption", charge_value=185.0)
        )
        assert inp.active is False

    def test_no_profile_no_input_and_entry_dropped(self, engine):
        engine.inverter_profile = None
        status = engine._run_load_balancer(_state(), None, T0, charge_decision(185.0))
        assert status.battery_output is None
        assert all(e.kind != "battery" for e in engine.config.load_balancing.give_way_order)


class TestReplanAndNotify:
    @pytest.mark.asyncio
    async def test_battery_pause_never_notifies(self, engine):
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()
        await engine._notify_balancer_interventions(battery_status(8880, 0, "paused"), None, T0)
        engine.dispatcher.notify_balancer_intervention.assert_not_called()


class TestStatusPayload:
    def test_battery_object_in_status(self, engine):
        engine._last_balancer_status = battery_status(10000.0, 7000.0, "throttling")
        payload = engine.get_load_balancer_status()
        assert payload["battery"] == {
            "planned_w": 10000,
            "cap_w": 7000,
            "state": "throttling",
            "reason": "battery reason",
            "phases": [1, 2, 3],
        }

    def test_battery_none_when_disabled(self, engine):
        engine._last_balancer_status = None
        assert engine.get_load_balancer_status()["battery"] is None


def test_removed_battery_clears_cap_and_keeps_scheduled_charge(engine):
    engine.config.load_balancing.auto_include_devices = False
    engine.config.load_balancing.give_way_order = []
    engine._battery_cap_w = 500.0
    decision = charge_decision(100)
    state = SystemState(current_import_kw=5.0, current_battery_charge_kw=5.0)
    status = engine._run_load_balancer(state, None, T0, decision)
    assert status.battery_output is None
    assert engine._battery_cap_w is None
    engine._apply_battery_cap(decision, status)
    assert decision.charge_value == 100
    assert engine.config.load_balancing.give_way_order == []
