"""universal-load-balancing 5.2: execution-log throttling for high-frequency ticks."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import pytz

from executor.actions import ActionResult
from executor.config import ControllerConfig, InverterConfig
from executor.controller import ControllerDecision
from executor.engine import ExecutorEngine
from executor.load_balancer import LoadBalancerStatus
from executor.override import OverrideResult, OverrideType


@pytest.fixture
def engine():
    with (
        patch("executor.engine.load_executor_config") as mock_load,
        patch("executor.engine.load_yaml") as mock_yaml,
        patch("executor.engine.ExecutionHistory"),
        patch("executor.engine.LoadDisaggregator"),
    ):
        mock_load.return_value = MagicMock(
            enabled=True,
            shadow_mode=False,
            timezone="Europe/Stockholm",
            controller=ControllerConfig(),
            inverter=InverterConfig(),
            water_heater=None,
            ev_chargers=[],
            load_balancing=MagicMock(enabled=False, main_fuse_a=None, loads=[]),
        )
        mock_yaml.return_value = {
            "system": {"has_solar": True, "has_battery": True, "has_ev_charger": False},
            "ev_chargers": [],
            "water_heaters": [],
        }
        return ExecutorEngine()


def decision(mode="idle") -> ControllerDecision:
    return ControllerDecision(mode_intent=mode)


def disabled_balancer_status(state="disabled") -> LoadBalancerStatus:
    return LoadBalancerStatus(
        enabled=False, state=state, reason="", main_fuse_a=None,
        phase_current_a={}, phase_headroom_a={},
    )


def no_override() -> OverrideResult:
    return OverrideResult(override_needed=False, override_type=OverrideType.NONE)


TZ = pytz.timezone("Europe/Stockholm")


class TestIdleSlotHeartbeat:
    def test_first_tick_in_a_slot_always_logs(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 5))
        should_log, reasons = engine._should_log_execution(
            now, decision(), [], no_override(), disabled_balancer_status()
        )
        assert should_log is True
        assert reasons  # first tick trips the mode_intent/balancer "change" flags

    def test_second_idle_tick_in_the_same_slot_is_a_pure_heartbeat(self, engine):
        base = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(base, decision(), [], no_override(), disabled_balancer_status())

        # New slot, nothing else changed -> only the heartbeat reason fires
        next_slot = TZ.localize(datetime(2026, 1, 1, 12, 15, 0))
        should_log, reasons = engine._should_log_execution(
            next_slot, decision(), [], no_override(), disabled_balancer_status()
        )
        assert should_log is True
        assert reasons == ["heartbeat"]

    def test_idle_5s_ticks_within_slot_yield_exactly_one_record(self, engine):
        logged_count = 0
        base = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        for i in range(0, 15 * 60, 5):  # a full 15-min slot at 5s ticks
            now = base.replace(second=0) + timedelta(seconds=i)
            should_log, _ = engine._should_log_execution(
                now, decision(), [], no_override(), disabled_balancer_status()
            )
            if should_log:
                logged_count += 1
        assert logged_count == 1

    def test_transition_mid_slot_yields_an_extra_record(self, engine):
        base = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        should_log_1, _ = engine._should_log_execution(
            base, decision("idle"), [], no_override(), disabled_balancer_status()
        )
        should_log_2, _ = engine._should_log_execution(
            base.replace(minute=5), decision("idle"), [], no_override(), disabled_balancer_status()
        )
        # Mode changes mid-slot
        should_log_3, reasons_3 = engine._should_log_execution(
            base.replace(minute=7), decision("charge"), [], no_override(), disabled_balancer_status()
        )
        should_log_4, _ = engine._should_log_execution(
            base.replace(minute=10), decision("charge"), [], no_override(), disabled_balancer_status()
        )

        assert should_log_1 is True  # heartbeat
        assert should_log_2 is False  # still idle, same slot
        assert should_log_3 is True  # mode_intent transition
        assert "mode_intent" in reasons_3[0]
        assert should_log_4 is False  # no further change, heartbeat already satisfied

    def test_new_slot_gets_its_own_heartbeat(self, engine):
        base = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(base, decision(), [], no_override(), disabled_balancer_status())

        next_slot = TZ.localize(datetime(2026, 1, 1, 12, 15, 0))
        should_log, reasons = engine._should_log_execution(
            next_slot, decision(), [], no_override(), disabled_balancer_status()
        )
        assert should_log is True
        assert "heartbeat" in reasons


class TestChangeDrivenLogging:
    def test_dispatched_action_forces_log(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        result = ActionResult(action_type="water_temp", success=True, skipped=False)
        should_log, reasons = engine._should_log_execution(
            now.replace(minute=1), decision(), [result], no_override(), disabled_balancer_status()
        )
        assert should_log is True
        assert "action dispatched" in reasons

    def test_skipped_action_does_not_force_log(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        result = ActionResult(action_type="water_temp", success=True, skipped=True)
        should_log, _ = engine._should_log_execution(
            now.replace(minute=1), decision(), [result], no_override(), disabled_balancer_status()
        )
        assert should_log is False

    def test_override_transition_forces_log(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        override = OverrideResult(override_needed=True, override_type=OverrideType.MANUAL_OVERRIDE)
        should_log, reasons = engine._should_log_execution(
            now.replace(minute=1), decision(), [], override, disabled_balancer_status()
        )
        assert should_log is True
        assert any("override" in r for r in reasons)

    def test_balancer_state_transition_forces_log(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        throttling_status = LoadBalancerStatus(
            enabled=True, state="throttling", reason="capped", main_fuse_a=20,
            phase_current_a={1: 22.0}, phase_headroom_a={1: -2.0},
        )
        should_log, reasons = engine._should_log_execution(
            now.replace(minute=1), decision(), [], no_override(), throttling_status
        )
        assert should_log is True
        assert any("balancer" in r for r in reasons)


class TestFailureNeverThrottled:
    """9.2: a record with success=0 (e.g. ev_charge_failed, which doesn't
    necessarily produce a non-skipped/failed action_result) must always pass
    the throttle gate, even mid-slot with nothing else changed.
    """

    def test_failure_tick_logs_even_mid_slot_with_nothing_else_changed(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        # Consume the slot's heartbeat first so a plain change-free tick would
        # otherwise be throttled.
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        should_log, reasons = engine._should_log_execution(
            now.replace(minute=5),
            decision(),
            [],
            no_override(),
            disabled_balancer_status(),
            record_success=False,
        )
        assert should_log is True
        assert "execution failed" in reasons

    def test_successful_tick_mid_slot_is_still_throttled(self, engine):
        now = TZ.localize(datetime(2026, 1, 1, 12, 0, 0))
        engine._should_log_execution(now, decision(), [], no_override(), disabled_balancer_status())

        should_log, _ = engine._should_log_execution(
            now.replace(minute=5),
            decision(),
            [],
            no_override(),
            disabled_balancer_status(),
            record_success=True,
        )
        assert should_log is False
