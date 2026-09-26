"""load-balancing-completion 4.3/5.2: sustained-throttle early replan and
intervention notification gating, tested against the engine's tracking logic
with synthetic balancer statuses (no HA, no full tick)."""

import contextlib
import logging
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
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ExecutorEngine
from executor.load_balancer import (
    EVBalancerOutput,
    LoadBalancerStatus,
    ShedLoadOutput,
)

TZ = pytz.timezone("Europe/Stockholm")
T0 = TZ.localize(datetime(2026, 6, 1, 12, 0, 0))


@pytest.fixture
def engine():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(db_engine)

    charger = EVChargerDeviceConfig(
        id="goe",
        name="go-e Gemini",
        type="current",
        current_entity="number.goe_current",
        switch_entity="switch.goe_allow",
        min_current_a=6,
        max_current_a=16,
    )
    config = ExecutorConfig(
        enabled=True,
        timezone="Europe/Stockholm",
        inverter=InverterConfig(),
        water_heater=WaterHeaterConfig(),
        notifications=NotificationConfig(),
        controller=ControllerConfig(),
        ev_chargers=[charger],
        load_balancing=LoadBalancingConfig(
            enabled=True, main_fuse_a=20, replan_after_throttled_s=600
        ),
    )

    with patch("executor.engine.load_executor_config", return_value=config):
        with patch(
            "executor.engine.load_yaml",
            return_value={"automation": {"schedule": {"every_minutes": 60}}},
        ):
            with patch.object(ExecutorEngine, "_get_db_path", return_value=db_path):
                eng = ExecutorEngine("config.yaml")

    yield eng
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_status(ev_state="throttling", ev_target=6, shed=(), enabled=True):
    return LoadBalancerStatus(
        enabled=enabled,
        state=ev_state,
        reason="test",
        main_fuse_a=20,
        phase_current_a={1: 20.0},
        phase_headroom_a={1: 0.0},
        ev_outputs=[EVBalancerOutput("goe", ev_target, ev_state, "reason text")],
        shed_outputs=[
            ShedLoadOutput(load_id, "water_heater", is_shed, "shed reason")
            for load_id, is_shed in shed
        ],
    )


class TestSustainedThrottleReplan:
    def test_fires_at_threshold(self, engine):
        engine._request_balancer_replan = MagicMock()
        engine._last_balancer_planned_targets = {"goe": 16}
        throttled = make_status(ev_target=6)

        engine._track_balancer_throttling(throttled, T0)
        engine._request_balancer_replan.assert_not_called()

        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=599))
        engine._request_balancer_replan.assert_not_called()

        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=600))
        engine._request_balancer_replan.assert_called_once()

    def test_paused_charger_counts_as_constrained(self, engine):
        engine._request_balancer_replan = MagicMock()
        engine._last_balancer_planned_targets = {"goe": 16}
        paused = make_status(ev_state="paused", ev_target=None)

        engine._track_balancer_throttling(paused, T0)
        engine._track_balancer_throttling(paused, T0 + timedelta(seconds=600))
        engine._request_balancer_replan.assert_called_once()

    def test_respects_one_per_planner_interval(self, engine):
        engine._request_balancer_replan = MagicMock()
        engine._last_balancer_planned_targets = {"goe": 16}
        throttled = make_status(ev_target=6)

        engine._track_balancer_throttling(throttled, T0)
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=600))
        assert engine._request_balancer_replan.call_count == 1

        # Throttling persists: threshold crossed again well before the 60-min
        # planner interval has elapsed -> no second replan.
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=1300))
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=2000))
        assert engine._request_balancer_replan.call_count == 1

        # After a full planner interval it rearms.
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=4300))
        assert engine._request_balancer_replan.call_count == 2

    def test_resets_on_recovery(self, engine):
        engine._request_balancer_replan = MagicMock()
        engine._last_balancer_planned_targets = {"goe": 16}
        throttled = make_status(ev_target=6)
        at_target = make_status(ev_state="idle", ev_target=16)

        engine._track_balancer_throttling(throttled, T0)
        engine._track_balancer_throttling(at_target, T0 + timedelta(seconds=300))
        # Recovery reset the clock: 599s of *new* throttling is below threshold.
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=400))
        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=999))
        engine._request_balancer_replan.assert_not_called()

        engine._track_balancer_throttling(throttled, T0 + timedelta(seconds=1000))
        engine._request_balancer_replan.assert_called_once()

    def test_ignores_planner_intended_reductions(self, engine):
        engine._request_balancer_replan = MagicMock()
        # Planner itself wants 6A (cheap top-up); the balancer is idle at 6A.
        engine._last_balancer_planned_targets = {"goe": 6}
        planner_low = make_status(ev_state="idle", ev_target=6)

        engine._track_balancer_throttling(planner_low, T0)
        engine._track_balancer_throttling(planner_low, T0 + timedelta(seconds=6000))
        engine._request_balancer_replan.assert_not_called()
        assert "goe" not in engine._balancer_throttled_since

    def test_resets_when_slot_stops_planning_charge(self, engine):
        engine._request_balancer_replan = MagicMock()
        engine._last_balancer_planned_targets = {"goe": 16}
        throttled = make_status(ev_target=6)
        engine._track_balancer_throttling(throttled, T0)

        engine._last_balancer_planned_targets = {"goe": None}
        idle = make_status(ev_state="idle", ev_target=None)
        engine._track_balancer_throttling(idle, T0 + timedelta(seconds=300))
        assert "goe" not in engine._balancer_throttled_since


class TestInterventionNotifications:
    @pytest.mark.asyncio
    async def test_shed_notifies_once(self, engine):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        shed = make_status(ev_state="idle", ev_target=16, shed=[("wh", True)])
        await engine._notify_balancer_interventions(shed)
        await engine._notify_balancer_interventions(shed)  # still shed: no repeat

        engine.dispatcher.notify_balancer_intervention.assert_called_once()
        assert "wh" in engine.dispatcher.notify_balancer_intervention.call_args.args[0]

    @pytest.mark.asyncio
    async def test_pause_and_stale_notify_once_each(self, engine):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        engine._pause_goal_risk = MagicMock(return_value=(True, "deadline near"))
        paused = make_status(ev_state="paused", ev_target=None)
        await engine._notify_balancer_interventions(paused)
        await engine._notify_balancer_interventions(paused)
        assert engine.dispatcher.notify_balancer_intervention.call_count == 1

        stale = make_status(ev_state="stale_fallback", ev_target=6)
        await engine._notify_balancer_interventions(stale)
        await engine._notify_balancer_interventions(stale)
        assert engine.dispatcher.notify_balancer_intervention.call_count == 2

    @pytest.mark.asyncio
    async def test_throttle_and_ramp_never_notify(self, engine):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        await engine._notify_balancer_interventions(make_status(ev_state="throttling", ev_target=10))
        await engine._notify_balancer_interventions(make_status(ev_state="throttling", ev_target=12))
        await engine._notify_balancer_interventions(make_status(ev_state="idle", ev_target=16))

        engine.dispatcher.notify_balancer_intervention.assert_not_called()

    @pytest.mark.asyncio
    async def test_repeated_pause_after_recovery_notifies_again(self, engine):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        engine._pause_goal_risk = MagicMock(return_value=(True, "deadline near"))
        await engine._notify_balancer_interventions(make_status(ev_state="paused", ev_target=None))
        await engine._notify_balancer_interventions(make_status(ev_state="idle", ev_target=16))
        await engine._notify_balancer_interventions(make_status(ev_state="paused", ev_target=None))

        assert engine.dispatcher.notify_balancer_intervention.call_count == 2

    @pytest.mark.asyncio
    async def test_toggle_off_suppresses_all(self, engine):
        engine.config.load_balancing.notify_interventions = False
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        await engine._notify_balancer_interventions(
            make_status(ev_state="paused", ev_target=None, shed=[("wh", True)])
        )
        engine.dispatcher.notify_balancer_intervention.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabling_toggle_later_does_not_fire_for_preexisting_state(self, engine):
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()

        engine.config.load_balancing.notify_interventions = False
        shed = make_status(ev_state="idle", ev_target=16, shed=[("wh", True)])
        await engine._notify_balancer_interventions(shed)

        engine.config.load_balancing.notify_interventions = True
        await engine._notify_balancer_interventions(shed)  # wh already shed before

        engine.dispatcher.notify_balancer_intervention.assert_not_called()


class TestGoalAtRiskPauseNotifications:
    """load-balancer-graceful-degradation 5.3: pauses notify only when the goal is at risk."""

    @staticmethod
    def _goal(deadline, planned_at=None, edited=None):
        return {
            "deadline": deadline.isoformat(),
            "required_kwh": 10.0,
            "last_updated": (edited or T0 - timedelta(hours=3)).isoformat(),
            "last_planned_at": (planned_at or T0 - timedelta(hours=1)).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_pause_without_risk_does_not_notify_but_is_logged(self, engine, caplog):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()
        deadline = T0 + timedelta(hours=30)
        engine._last_schedule_meta = {
            "ev_goal_diagnostics": {
                "goe": {"deadline": deadline.isoformat(), "shortfall_kwh": 0.0, "reason": None}
            }
        }
        with patch(
            "backend.core.ev_state.read_ev_state", return_value={"goe": self._goal(deadline)}
        ):
            caplog.set_level(logging.INFO, logger="executor.engine")
            for _ in range(3):
                await engine._notify_balancer_interventions(
                    make_status(ev_state="paused", ev_target=None), None, T0
                )
                await engine._notify_balancer_interventions(
                    make_status(ev_state="throttling", ev_target=6), None, T0
                )
        engine.dispatcher.notify_balancer_intervention.assert_not_called()
        assert "not notifying" in caplog.text

    @pytest.mark.asyncio
    async def test_pause_near_deadline_in_goal_slot_notifies_once(self, engine):
        from executor.override import SlotPlan

        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()
        deadline = T0 + timedelta(minutes=90)
        engine._last_schedule_meta = {
            "ev_goal_diagnostics": {
                "goe": {"deadline": deadline.isoformat(), "shortfall_kwh": 0.0, "reason": None}
            }
        }
        slot = SlotPlan(ev_charger_plans={"goe": 7.0})
        with patch(
            "backend.core.ev_state.read_ev_state", return_value={"goe": self._goal(deadline)}
        ):
            paused = make_status(ev_state="paused", ev_target=None)
            await engine._notify_balancer_interventions(paused, slot, T0)
            await engine._notify_balancer_interventions(paused, slot, T0)
        engine.dispatcher.notify_balancer_intervention.assert_called_once()
        message = engine.dispatcher.notify_balancer_intervention.call_args.args[0]
        assert "go-e Gemini" in message and "goal at risk" in message

    @pytest.mark.asyncio
    async def test_relief_throttling_never_notifies(self, engine):
        engine.config.load_balancing.notify_interventions = True
        engine.dispatcher = MagicMock()
        engine.dispatcher.notify_balancer_intervention = AsyncMock()
        status = make_status(ev_state="throttling", ev_target=6)
        status.ev_outputs[0].relief_1p_requested = True
        await engine._notify_balancer_interventions(status, None, T0)
        engine.dispatcher.notify_balancer_intervention.assert_not_called()


class TestBalancerReliefDispatch:
    """load-balancer-graceful-degradation 4.3: relief is dispatched after the
    balancer through the phase controller (dwell and fail-safe still apply)."""

    @staticmethod
    def _relief_status():
        status = make_status(ev_state="throttling", ev_target=6)
        status.ev_outputs[0].relief_1p_requested = True
        status.ev_outputs[0].reason = "1-phase on L1 — relieving L3"
        return status

    @staticmethod
    def _enable_switching(engine):
        charger = engine.config.ev_chargers[0]
        charger.phase_switching_enabled = True
        charger.phase_mode_entity = "select.goe_psm"
        charger.phase_1_value = "one_phase"
        engine.dispatcher = MagicMock()

    @pytest.mark.asyncio
    async def test_relief_switches_to_1_phase_and_holds(self, engine):
        from executor.actions import ActionResult
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock(
            return_value=ActionResult(action_type="ev_phase_mode", success=True)
        )
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(hours=1))
        engine._ev_phase_controllers["goe"] = ctrl

        results = await engine._apply_balancer_relief(self._relief_status(), T0)

        engine.dispatcher.set_ev_phase_mode.assert_awaited_once_with(
            "select.goe_psm", 1, "one_phase"
        )
        assert len(results) == 1
        assert ctrl.commanded_mode == 1 and ctrl.relief_hold
        payload = engine.get_load_balancer_status()
        ev_status = payload["ev"][0]
        assert ev_status["relief_1p"] is True
        assert ev_status["relief_reason"] == "1-phase on L1 — relieving L3"
        assert ev_status["phase_1_line"] == 1

    @pytest.mark.asyncio
    async def test_relief_blocked_by_dwell(self, engine):
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock()
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(seconds=200))
        engine._ev_phase_controllers["goe"] = ctrl

        assert await engine._apply_balancer_relief(self._relief_status(), T0) == []
        engine.dispatcher.set_ev_phase_mode.assert_not_awaited()
        assert ctrl.commanded_mode == 3

    @pytest.mark.asyncio
    async def test_failed_relief_write_latches_fail_safe(self, engine):
        from executor.actions import ActionResult
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock(
            return_value=ActionResult(action_type="ev_phase_mode", success=False)
        )
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(hours=1))
        engine._ev_phase_controllers["goe"] = ctrl

        await engine._apply_balancer_relief(self._relief_status(), T0)
        assert ctrl.failed and not ctrl.relief_hold
        assert not ctrl.relief_available(T0, 600)

    @staticmethod
    def _refit_status():
        status = make_status(ev_state="throttling", ev_target=8)
        status.ev_outputs[0].relief_1p_requested = True
        status.ev_outputs[0].refit_from_pause = True
        status.ev_outputs[0].reason = "Resuming 1-phase on L1 at 8A"
        return status

    @pytest.mark.asyncio
    async def test_failed_refit_switch_keeps_charger_paused(self, engine):
        """D17: a quick re-fit into 1-phase only starts charging once the
        switch is applied; a failed write keeps the charger paused and
        restarts the balancer's confirm window."""
        from executor.actions import ActionResult
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock(
            return_value=ActionResult(action_type="ev_phase_mode", success=False)
        )
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(hours=1))
        engine._ev_phase_controllers["goe"] = ctrl
        engine._load_balancer._ev_last_refit_at["goe"] = T0

        status = self._refit_status()
        await engine._apply_balancer_relief(status, T0)

        out = status.ev_outputs[0]
        assert out.target_a is None and out.state == "paused"
        assert status.state == "paused"
        assert engine._load_balancer._ev_paused_at["goe"] == T0
        assert "goe" not in engine._load_balancer._ev_last_refit_at

    @pytest.mark.asyncio
    async def test_refit_refused_by_dwell_keeps_charger_paused(self, engine):
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock()
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(seconds=200))
        engine._ev_phase_controllers["goe"] = ctrl

        status = self._refit_status()
        await engine._apply_balancer_relief(status, T0)
        engine.dispatcher.set_ev_phase_mode.assert_not_awaited()
        assert status.ev_outputs[0].target_a is None

    @pytest.mark.asyncio
    async def test_refit_aborted_when_writes_are_skipped(self, engine):
        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock()
        status = self._refit_status()
        await engine._apply_balancer_relief(status, T0, writes_allowed=False)
        engine.dispatcher.set_ev_phase_mode.assert_not_awaited()
        assert status.ev_outputs[0].target_a is None

    @pytest.mark.asyncio
    async def test_applied_refit_switch_resumes_at_refit_amps(self, engine):
        from executor.actions import ActionResult
        from executor.ev_surplus import PhaseModeController

        self._enable_switching(engine)
        engine.dispatcher.set_ev_phase_mode = AsyncMock(
            return_value=ActionResult(action_type="ev_phase_mode", success=True)
        )
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, T0 - timedelta(hours=1))
        engine._ev_phase_controllers["goe"] = ctrl

        status = self._refit_status()
        await engine._apply_balancer_relief(status, T0)
        assert status.ev_outputs[0].target_a == 8
        assert ctrl.commanded_mode == 1 and ctrl.relief_hold
