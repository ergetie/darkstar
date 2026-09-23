"""fix-ev-current-charger-control 3.5: EV action logging, dedup, backoff, failure wording."""

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
from executor.actions import ActionDispatcher, ActionResult, HACallError
from executor.config import (
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
)
from executor.engine import EVChargerState, ExecutorEngine
from executor.override import SlotPlan

TZ = pytz.timezone("Europe/Stockholm")


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


@pytest.fixture
def engine(temp_schedule, temp_db):
    charger = EVChargerDeviceConfig(
        id="goe",
        type="current",
        current_entity="number.goe_current",
        switch_entity="select.goe_frc",
        charge_enabled_value="charge",
        charge_disabled_value="dont_charge",
        min_current_a=6,
        max_current_a=16,
        phases=[1, 2, 3],
    )
    with patch("executor.engine.load_executor_config") as mock_config:
        mock_config.return_value = ExecutorConfig(
            schedule_path=temp_schedule, timezone="Europe/Stockholm", ev_chargers=[charger]
        )
        with (
            patch("executor.engine.load_yaml", return_value={}),
            patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db),
        ):
            eng = ExecutorEngine("config.yaml")
    eng._has_ev_charger = True
    eng.ha_client = AsyncMock()
    eng.ha_client.get_state = AsyncMock(return_value=None)
    eng.history = MagicMock()
    return eng


def records(eng) -> list:
    return [c.args[0] for c in eng.history.log_execution.call_args_list]


def slot(ev_kw: float) -> SlotPlan:
    return SlotPlan(ev_charging_kw=ev_kw, ev_charger_plans={"goe": ev_kw})


def failing_current_dispatcher(error: str = "HTTP 500: min 6") -> AsyncMock:
    dispatcher = AsyncMock()
    dispatcher.set_ev_charger_current = AsyncMock(
        side_effect=lambda entity, amps: ActionResult(
            action_type="ev_charge_current",
            success=False,
            message=f"Failed to set {entity} to {amps}A: {error}",
            entity_id=entity,
            new_value=amps,
            error_details=error,
        )
    )
    dispatcher.set_ev_charger_switch = AsyncMock(
        return_value=ActionResult(action_type="ev_charge_start", success=True, skipped=True)
    )
    return dispatcher


class TestEvActionRecords:
    @pytest.mark.asyncio
    async def test_failed_current_write_is_recorded(self, engine):
        engine.dispatcher = failing_current_dispatcher()
        await engine._control_ev_charger(slot(4.14), datetime.now(TZ))

        (record,) = records(engine)
        assert record.source == "ev_charger"
        assert record.success == 0
        assert record.commanded_work_mode == "ev_charge_current"
        assert "HTTP 500" in record.error_message
        detail = record.action_results[0]
        assert detail["charger_id"] == "goe"
        assert detail["new_value"] == 6
        assert detail["entity_id"] == "number.goe_current"

    @pytest.mark.asyncio
    async def test_failed_switch_write_is_recorded(self, engine):
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_current = AsyncMock(
            return_value=ActionResult(action_type="ev_charge_current", success=True, new_value=6)
        )
        engine.dispatcher.set_ev_charger_switch = AsyncMock(
            return_value=ActionResult(
                action_type="ev_charge_start",
                success=False,
                message="Failed to set select.goe_frc to charge: timeout",
                entity_id="select.goe_frc",
                new_value="charge",
                error_details="timeout",
            )
        )
        await engine._control_ev_charger(slot(4.14), datetime.now(TZ))

        modes = [(r.commanded_work_mode, r.success) for r in records(engine)]
        assert modes == [("ev_charge_current", 1), ("ev_charge_start", 0)]
        assert records(engine)[1].error_message == "timeout"
        assert records(engine)[1].action_results[0]["new_value"] == "charge"

    @pytest.mark.asyncio
    async def test_skipped_results_not_recorded(self, engine):
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(
            return_value=ActionResult(action_type="ev_charge_stop", success=True, skipped=True)
        )
        await engine._control_ev_charger(slot(0.0), datetime.now(TZ))
        assert records(engine) == []

    @pytest.mark.asyncio
    async def test_phase_mode_change_gets_dedicated_record(self, engine):
        charger = engine.config.ev_chargers[0]
        charger.phase_switching_enabled = True
        charger.phase_mode_entity = "select.goe_psm"
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_phase_mode = AsyncMock(
            return_value=ActionResult(
                action_type="ev_phase_mode",
                success=True,
                entity_id="select.goe_psm",
                new_value="1",
            )
        )
        phase_ctrl = MagicMock(failed=False)
        phase_ctrl.decide.return_value = MagicMock(should_switch=True, commanded_mode=1)

        await engine._apply_phase_mode_decision(charger, phase_ctrl, 2.0, datetime.now(TZ))

        (record,) = records(engine)
        assert record.commanded_work_mode == "ev_phase_mode"
        assert record.source == "ev_charger"
        assert record.action_results[0]["new_value"] == "1"


class TestEvFailureDedup:
    def test_identical_failures_within_window_recorded_once(self, engine):
        now = datetime.now(TZ)
        failure = ActionResult(
            action_type="ev_charge_current",
            success=False,
            new_value=6,
            error_details="HTTP 500",
        )
        for i in range(10):
            engine._log_ev_action("goe", failure, "ev_charge_current", now + timedelta(seconds=i))

        assert len(records(engine)) == 1

        success = ActionResult(action_type="ev_charge_current", success=True, new_value=6)
        engine._log_ev_action("goe", success, "ev_charge_current", now + timedelta(seconds=20))

        last = records(engine)[-1]
        assert last.action_results[0]["repeat_count"] == 9
        assert "repeated 9 times" in last.action_results[0]["message"]

    def test_failure_after_window_recorded_again(self, engine):
        now = datetime.now(TZ)
        failure = ActionResult(
            action_type="ev_charge_current", success=False, new_value=6, error_details="HTTP 500"
        )
        engine._log_ev_action("goe", failure, "ev_charge_current", now)
        engine._log_ev_action("goe", failure, "ev_charge_current", now + timedelta(seconds=30))
        engine._log_ev_action("goe", failure, "ev_charge_current", now + timedelta(minutes=6))

        assert len(records(engine)) == 2
        assert records(engine)[1].action_results[0]["repeat_count"] == 1

    def test_different_error_is_recorded(self, engine):
        now = datetime.now(TZ)
        for error in ("HTTP 500", "timeout"):
            engine._log_ev_action(
                "goe",
                ActionResult(
                    action_type="ev_charge_current", success=False, new_value=6, error_details=error
                ),
                "ev_charge_current",
                now,
            )
        assert len(records(engine)) == 2


class TestEvFailureBackoff:
    @pytest.mark.asyncio
    async def test_backoff_skips_ha_calls_until_expired(self, engine):
        engine.dispatcher = failing_current_dispatcher()
        now = datetime.now(TZ)

        await engine._control_ev_charger(slot(4.14), now)
        assert engine.dispatcher.set_ev_charger_current.call_count == 1

        # Within the first 60 s backoff: no HA call at all
        await engine._control_ev_charger(slot(4.14), now + timedelta(seconds=30))
        assert engine.dispatcher.set_ev_charger_current.call_count == 1
        engine.dispatcher.set_ev_charger_switch.assert_not_called()

        # After 60 s: retried, then the second failure doubles the delay to 120 s
        await engine._control_ev_charger(slot(4.14), now + timedelta(seconds=61))
        assert engine.dispatcher.set_ev_charger_current.call_count == 2
        backoff = engine._ev_write_backoff["goe"]
        assert backoff.failures == 2
        assert backoff.until == now + timedelta(seconds=61 + 120)

    def test_backoff_delay_is_capped(self, engine):
        now = datetime.now(TZ)
        failure = ActionResult(action_type="ev_charge_current", success=False)
        for _ in range(8):
            engine._ev_record_write_outcome("goe", "charge:6", failure, now)
        assert engine._ev_write_backoff["goe"].until == now + timedelta(seconds=600)

    @pytest.mark.asyncio
    async def test_desired_state_change_resets_backoff(self, engine):
        engine.dispatcher = failing_current_dispatcher()
        now = datetime.now(TZ)
        engine._ev_charger_states["goe"] = EVChargerState()

        await engine._control_ev_charger(slot(4.14), now)
        assert "goe" in engine._ev_write_backoff

        engine.dispatcher.set_ev_charger_switch = AsyncMock(
            return_value=ActionResult(
                action_type="ev_charge_stop", success=True, new_value="dont_charge"
            )
        )
        # Plan changes to stop while still in backoff: stop is attempted immediately
        await engine._control_ev_charger(slot(0.0), now + timedelta(seconds=5))

        engine.dispatcher.set_ev_charger_switch.assert_called_once()
        assert engine.dispatcher.set_ev_charger_switch.call_args.kwargs["turn_on"] is False
        assert "goe" not in engine._ev_write_backoff

    @pytest.mark.asyncio
    async def test_success_resets_backoff(self, engine):
        now = datetime.now(TZ)
        engine._ev_record_write_outcome(
            "goe", "charge:6", ActionResult(action_type="x", success=False), now
        )
        engine._ev_record_write_outcome(
            "goe", "charge:6", ActionResult(action_type="x", success=True), now
        )
        assert "goe" not in engine._ev_write_backoff


class TestDispatcherFailureWording:
    @pytest.fixture
    def dispatcher(self):
        config = ExecutorConfig(
            inverter=InverterConfig(),
            controller=ControllerConfig(),
            notifications=NotificationConfig(),
        )
        ha = MagicMock()
        ha.get_state_value = AsyncMock(return_value="16")
        ha.set_number = AsyncMock(side_effect=HACallError("HTTP 500", status_code=500))
        ha.set_select_option = AsyncMock(side_effect=HACallError("HTTP 400", status_code=400))
        return ActionDispatcher(ha_client=ha, config=config, shadow_mode=False)

    @pytest.mark.asyncio
    async def test_current_failure_logs_entity_and_value(self, dispatcher, caplog):
        with caplog.at_level(logging.ERROR, logger="executor.actions"):
            result = await dispatcher.set_ev_charger_current("number.goe_current", 6)

        assert result.success is False
        assert "number.goe_current" in result.message
        assert "6A" in result.message
        assert "set to" not in result.message
        line = next(m for m in caplog.messages if "number.goe_current" in m)
        assert "6A" in line
        assert "HTTP 500" in line

    @pytest.mark.asyncio
    async def test_switch_failure_names_option(self, dispatcher, caplog):
        with caplog.at_level(logging.ERROR, logger="executor.actions"):
            result = await dispatcher.set_ev_charger_switch(
                "select.goe_frc",
                turn_on=True,
                enabled_value="charge",
                disabled_value="dont_charge",
            )

        assert result.success is False
        assert "select.goe_frc to charge" in result.message
        assert any("select.goe_frc to charge" in m for m in caplog.messages)
