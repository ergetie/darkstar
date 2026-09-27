"""universal-load-balancing 5.1: EV charge failure detection based on the
commanded level (not raw scheduled kW), so balancer pause/throttle is never
mistaken for a wallbox failure. Covers the six ev-charge-failure-detection
delta-spec scenarios directly against ExecutorEngine._check_ev_charge_failure.
"""

import contextlib
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.config import ControllerConfig, InverterConfig
from executor.engine import ExecutorEngine


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
    db_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(db_engine)
    yield db_path
    with contextlib.suppress(OSError):
        Path(db_path).unlink()


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
            "system": {"has_solar": True, "has_battery": True, "has_ev_charger": True},
            "ev_chargers": [],
            "water_heaters": [],
        }
        eng = ExecutorEngine()
        eng._has_ev_charger = True
        eng.dispatcher = MagicMock()
        eng.dispatcher.notify_error = AsyncMock()
        eng._full_config = {"automation": {"schedule": {"every_minutes": 60}}}
        eng._request_balancer_replan = MagicMock()
        return eng


class TestWallboxRejectsCommand:
    """Scenario: EV wallbox rejects charge command."""

    @pytest.mark.asyncio
    async def test_fires_after_5_consecutive_zero_ticks(self, engine):
        fired = []
        for _ in range(5):
            fired.append(await engine._check_ev_charge_failure(True, 0.0))

        assert fired == [False, False, False, False, True]
        engine.dispatcher.notify_error.assert_called_once()
        msg = engine.dispatcher.notify_error.call_args[0][0]
        assert "commanded" in msg.lower()
        assert "0.00kW actual" in msg


class TestRampsUpWithinThreshold:
    """Scenario: EV charger ramps up within threshold — no failure, counter resets."""

    @pytest.mark.asyncio
    async def test_no_error_and_counter_resets(self, engine):
        for _ in range(4):
            await engine._check_ev_charge_failure(True, 0.0)
        assert engine._ev_zero_power_ticks == 4

        fired = await engine._check_ev_charge_failure(True, 0.5)

        assert fired is False
        assert engine._ev_zero_power_ticks == 0
        engine.dispatcher.notify_error.assert_not_called()


class TestBalancerPauseIsNotFailure:
    """Scenario: balancer pause is not a failure — counter never increments."""

    @pytest.mark.asyncio
    async def test_paused_charger_does_not_increment_counter(self, engine):
        # commanded_active=False because the balancer paused the charger,
        # even though the schedule wanted 10kW this slot.
        for _ in range(10):
            fired = await engine._check_ev_charge_failure(False, 0.0)
            assert fired is False

        assert engine._ev_zero_power_ticks == 0
        engine.dispatcher.notify_error.assert_not_called()


class TestBalancerThrottledChargingIsNotFailure:
    """Scenario: balancer caps to 6A (~4.1kW), actual ~4kW -> no failure."""

    @pytest.mark.asyncio
    async def test_reduced_but_nonzero_power_is_not_a_failure(self, engine):
        for _ in range(10):
            fired = await engine._check_ev_charge_failure(True, 4.0)
            assert fired is False

        assert engine._ev_zero_power_ticks == 0
        engine.dispatcher.notify_error.assert_not_called()


class TestErrorFiresOnlyOnce:
    """Scenario: error fires only once per EV slot."""

    @pytest.mark.asyncio
    async def test_no_repeat_notification_while_still_zero(self, engine):
        for _ in range(5):
            await engine._check_ev_charge_failure(True, 0.0)
        engine.dispatcher.notify_error.assert_called_once()

        for _ in range(5):
            fired = await engine._check_ev_charge_failure(True, 0.0)
            assert fired is False

        engine.dispatcher.notify_error.assert_called_once()  # still just once


class TestCounterResetsWhenSlotEnds:
    """Scenario: counter and notified flag reset when EV slot ends."""

    @pytest.mark.asyncio
    async def test_reset_then_fresh_session_needs_5_more_ticks(self, engine):
        for _ in range(5):
            await engine._check_ev_charge_failure(True, 0.0)
        assert engine._ev_failure_notified is True

        # Slot ends / charger no longer commanded
        fired = await engine._check_ev_charge_failure(False, 0.0)
        assert fired is False
        assert engine._ev_zero_power_ticks == 0
        assert engine._ev_failure_notified is False

        # New commanded session starts fresh — needs 5 more zero ticks
        for _ in range(4):
            fired = await engine._check_ev_charge_failure(True, 0.0)
            assert fired is False
        fired = await engine._check_ev_charge_failure(True, 0.0)
        assert fired is True
        assert engine.dispatcher.notify_error.call_count == 2


class TestFullTickWiring:
    """Confirms commanded_active (post-balancer) drives the counter through a
    real _tick(), not just the isolated _check_ev_charge_failure method."""

    @pytest.mark.asyncio
    async def test_commanded_current_type_charger_with_zero_actual_increments(
        self, temp_schedule, temp_db
    ):
        import json
        from datetime import datetime, timedelta
        from pathlib import Path

        import pytz

        from tests.executor.test_load_balancer_wiring import make_engine, make_ev_slot, make_schedule

        eng = make_engine(temp_schedule, temp_db, load_balancing_enabled=False)
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        schedule = make_schedule([make_ev_slot(slot_start, "goe", 11.0)])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        await eng.run_once()  # commands 15A; disaggregator has no registered EV -> actual=0

        assert eng._ev_zero_power_ticks == 1
        assert eng._ev_failure_notified is False

    @pytest.mark.asyncio
    async def test_balancer_paused_charger_does_not_increment(self, temp_schedule, temp_db):
        import json
        from datetime import datetime, timedelta
        from pathlib import Path

        import pytz

        from tests.executor.test_load_balancer_wiring import make_engine, make_ev_slot, make_schedule

        # L1 headroom is deeply negative -> balancer pauses the charger
        eng = make_engine(
            temp_schedule,
            temp_db,
            load_balancing_enabled=True,
            grid_currents={1: 40.0, 2: 5.0, 3: 5.0},
        )
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        schedule = make_schedule([make_ev_slot(slot_start, "goe", 11.0)])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        for _ in range(6):
            await eng.run_once()

        assert eng._last_balancer_status.state == "paused"
        assert eng._ev_zero_power_ticks == 0
        assert eng._ev_failure_notified is False


T0 = datetime(2026, 9, 24, 10, 15)


async def _fail(engine, start: datetime) -> datetime:
    """Drive 5 zero-power ticks (10 s apart) so the failure fires; return last tick time."""
    t = start
    for i in range(5):
        t = start + timedelta(seconds=10 * i)
        await engine._check_ev_charge_failure(True, 0.0, now=t)
    return t


class TestFailureRecoveryReplan:
    """ev-goal-shortfall-recovery 5.4: failure/recovery replan with its own cooldown."""

    @pytest.mark.asyncio
    async def test_failure_requests_replan(self, engine):
        await _fail(engine, T0)
        engine._request_balancer_replan.assert_called_once()
        engine.dispatcher.notify_error.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovery_requests_replan(self, engine):
        """Incident timing: failure ~10:16, power back 10:22 -> both replan."""
        await _fail(engine, T0)
        await engine._check_ev_charge_failure(True, 4.1, now=T0 + timedelta(minutes=7))
        # Only the first >0.1 kW tick requests a replan.
        await engine._check_ev_charge_failure(True, 4.1, now=T0 + timedelta(minutes=30))
        assert engine._request_balancer_replan.call_count == 2

    @pytest.mark.asyncio
    async def test_recovery_within_cooldown_is_deferred_not_dropped(self, engine):
        last = await _fail(engine, T0)
        await engine._check_ev_charge_failure(True, 4.1, now=last + timedelta(minutes=2))
        engine._request_balancer_replan.assert_called_once()
        assert engine._ev_failure_recovery_pending is True
        # Still charging after the cooldown -> the deferred recovery replan fires once.
        await engine._check_ev_charge_failure(True, 4.1, now=last + timedelta(minutes=5))
        await engine._check_ev_charge_failure(True, 4.1, now=last + timedelta(minutes=6))
        assert engine._request_balancer_replan.call_count == 2
        assert engine._ev_failure_recovery_pending is False

    @pytest.mark.asyncio
    async def test_deferred_recovery_waits_for_power(self, engine):
        """After the cooldown, a zero-power tick does not fire the recovery replan."""
        last = await _fail(engine, T0)
        await engine._check_ev_charge_failure(True, 4.1, now=last + timedelta(minutes=2))
        await engine._check_ev_charge_failure(True, 0.0, now=last + timedelta(minutes=6))
        engine._request_balancer_replan.assert_called_once()
        await engine._check_ev_charge_failure(True, 4.1, now=last + timedelta(minutes=7))
        assert engine._request_balancer_replan.call_count == 2

    @pytest.mark.asyncio
    async def test_balancer_rate_limit_does_not_block_failure_replan(self, engine):
        engine._last_balancer_replan_at = T0 - timedelta(minutes=5)
        await _fail(engine, T0)
        engine._request_balancer_replan.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_replan_does_not_consume_balancer_slot(self, engine):
        last = await _fail(engine, T0)
        assert engine._executor_replan_allowed(last + timedelta(minutes=1)) is True

    @pytest.mark.asyncio
    async def test_power_without_prior_failure_does_not_replan(self, engine):
        await engine._check_ev_charge_failure(True, 4.1, now=T0)
        engine._request_balancer_replan.assert_not_called()

    @pytest.mark.asyncio
    async def test_command_end_clears_pending_recovery(self, engine):
        await _fail(engine, T0)
        await engine._check_ev_charge_failure(False, 0.0, now=T0 + timedelta(minutes=30))
        await engine._check_ev_charge_failure(True, 4.1, now=T0 + timedelta(minutes=90))
        engine._request_balancer_replan.assert_called_once()


class TestPhaseSwitchGraceWindow:
    """ev-planned-phase-switching 4.2: 60 s grace after a commanded phase switch."""

    SWITCH_AT = datetime(2026, 9, 27, 12, 0, 50)

    @staticmethod
    def _arm(engine, last_switch: datetime) -> None:
        from executor.engine import EVChargerState
        from executor.ev_surplus import PhaseModeController

        engine._ev_charger_states = {"goe": EVChargerState(charging_active=True)}
        ctrl = PhaseModeController()
        ctrl.on_switch_success(3, last_switch)
        engine._ev_phase_controllers = {"goe": ctrl}

    async def _ticks(self, engine, start: datetime, count: int) -> list[bool]:
        return [
            await engine._check_ev_charge_failure(True, 0.0, now=start + timedelta(seconds=5 * i))
            for i in range(count)
        ]

    @pytest.mark.asyncio
    async def test_switch_over_pause_is_not_a_failure(self, engine):
        self._arm(engine, self.SWITCH_AT)
        # 12:00:55 .. 12:01:15 at zero power.
        fired = await self._ticks(engine, self.SWITCH_AT + timedelta(seconds=5), 5)
        assert fired == [False] * 5
        assert engine._ev_zero_power_ticks == 0
        engine.dispatcher.notify_error.assert_not_called()
        engine._request_balancer_replan.assert_not_called()

    @pytest.mark.asyncio
    async def test_real_failure_after_switch_is_still_detected(self, engine):
        self._arm(engine, self.SWITCH_AT)
        # 90 s of zero power, one tick every 5 s from the switch.
        fired = await self._ticks(engine, self.SWITCH_AT + timedelta(seconds=5), 18)
        # Ticks within 60 s (5..55 s: 11 ticks) are not counted; the 5th
        # counted tick is at 60+20 = 80 s -> index 15.
        assert fired.index(True) == 15
        assert fired.count(True) == 1
        engine.dispatcher.notify_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_counter_is_paused_not_reset(self, engine):
        before = self.SWITCH_AT - timedelta(seconds=15)
        self._arm(engine, before - timedelta(hours=1))
        await self._ticks(engine, before, 3)
        assert engine._ev_zero_power_ticks == 3

        self._arm(engine, self.SWITCH_AT)
        in_window = await self._ticks(engine, self.SWITCH_AT, 12)
        assert in_window == [False] * 12
        assert engine._ev_zero_power_ticks == 3

        after = await self._ticks(engine, self.SWITCH_AT + timedelta(seconds=60), 2)
        assert after == [False, True]

    @pytest.mark.asyncio
    async def test_uncommanded_charger_switch_does_not_pause(self, engine):
        from executor.engine import EVChargerState

        self._arm(engine, self.SWITCH_AT)
        engine._ev_charger_states["goe"] = EVChargerState(charging_active=False)
        fired = await self._ticks(engine, self.SWITCH_AT + timedelta(seconds=5), 5)
        assert fired[-1] is True
