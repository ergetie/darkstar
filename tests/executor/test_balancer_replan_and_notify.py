"""load-balancing-completion 4.3/5.2: sustained-throttle early replan and
intervention notification gating, tested against the engine's tracking logic
with synthetic balancer statuses (no HA, no full tick)."""

import contextlib
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
