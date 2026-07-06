"""universal-load-balancing 5.1: EV charge failure detection based on the
commanded level (not raw scheduled kW), so balancer pause/throttle is never
mistaken for a wallbox failure. Covers the six ev-charge-failure-detection
delta-spec scenarios directly against ExecutorEngine._check_ev_charge_failure.
"""

import contextlib
import tempfile
from pathlib import Path
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
