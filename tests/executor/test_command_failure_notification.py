"""
Tests for command-failure streak notification (fix-observability-gaps #24).

Drives multiple ticks of the real ExecutorEngine with a mocked HA client and
asserts that a repeatedly-failing action type notifies exactly once per
streak, respects notifications.on_error, and can re-notify after a recovery.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import ActionResult, HAClient
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ACTION_FAILURE_NOTIFY_STREAK, ExecutorEngine


@pytest.fixture
def temp_schedule():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        schedule_path = f.name
    yield schedule_path
    Path(schedule_path).unlink(missing_ok=True)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


def make_schedule(slot_start: datetime) -> dict:
    end = slot_start + timedelta(minutes=15)
    return {
        "schedule": [
            {
                "start_time": slot_start.isoformat(),
                "end_time": end.isoformat(),
                "end_time_kepler": end.isoformat(),
                "battery_charge_kw": 0,
                "battery_discharge_kw": 0,
                "export_kwh": 0,
                "water_heating_kw": 0,
                "soc_target_percent": 50,
                "projected_soc_percent": 45,
            }
        ],
        "meta": {"generated_at": datetime.now(pytz.UTC).isoformat()},
    }


@pytest.mark.asyncio
class TestCommandFailureNotification:
    @pytest.fixture
    def build_engine(self, temp_schedule, temp_db):
        def _build(on_error: bool = True):
            with patch("executor.engine.load_executor_config") as mock_config:
                config = ExecutorConfig(
                    enabled=True,
                    schedule_path=temp_schedule,
                    timezone="Europe/Stockholm",
                    automation_toggle_entity="input_boolean.automation",
                    inverter=InverterConfig(),
                    water_heater=WaterHeaterConfig(),
                    notifications=NotificationConfig(on_error=on_error),
                    controller=ControllerConfig(),
                )
                mock_config.return_value = config
                with patch("executor.engine.load_yaml") as mock_yaml:
                    mock_yaml.return_value = {"input_sensors": {}}
                    with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                        engine = ExecutorEngine("config.yaml")

                        mock_ha = MagicMock(spec=HAClient)
                        mock_ha.get_state_value.side_effect = lambda entity_id: "on"
                        mock_ha.set_select_option.return_value = True
                        mock_ha.set_switch.return_value = True
                        mock_ha.set_number.return_value = True
                        mock_ha.set_input_number.return_value = True
                        engine.ha_client = mock_ha

                        from executor.actions import ActionDispatcher

                        engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)
                        engine.dispatcher.notify_error = AsyncMock()
                        return engine

        return _build

    def _write_schedule(self, temp_schedule):
        tz = pytz.timezone("Europe/Stockholm")
        slot_start = datetime.now(tz) - timedelta(minutes=5)
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(make_schedule(slot_start), f)

    async def test_streak_crosses_threshold_notifies_once(self, build_engine, temp_schedule):
        engine = build_engine()
        self._write_schedule(temp_schedule)

        failing_result = ActionResult(
            action_type="water_heat_start", success=False, message="HA rejected command"
        )
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])

        for _ in range(ACTION_FAILURE_NOTIFY_STREAK):
            await engine.run_once()

        engine.dispatcher.notify_error.assert_called_once()
        assert "water_heat_start" in engine.dispatcher.notify_error.call_args[0][0]

    async def test_dedup_holds_while_streak_continues(self, build_engine, temp_schedule):
        engine = build_engine()
        self._write_schedule(temp_schedule)

        failing_result = ActionResult(
            action_type="water_heat_start", success=False, message="HA rejected command"
        )
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])

        for _ in range(ACTION_FAILURE_NOTIFY_STREAK + 1):
            await engine.run_once()

        engine.dispatcher.notify_error.assert_called_once()

    async def test_recovery_then_new_streak_notifies_again(self, build_engine, temp_schedule):
        engine = build_engine()
        self._write_schedule(temp_schedule)

        failing_result = ActionResult(
            action_type="water_heat_start", success=False, message="HA rejected command"
        )
        succeeding_result = ActionResult(action_type="water_heat_start", success=True, message="OK")
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])

        for _ in range(ACTION_FAILURE_NOTIFY_STREAK):
            await engine.run_once()
        assert engine.dispatcher.notify_error.call_count == 1

        # Recovery resets the streak
        engine.dispatcher.execute = AsyncMock(return_value=[succeeding_result])
        await engine.run_once()

        # New failure streak
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])
        for _ in range(ACTION_FAILURE_NOTIFY_STREAK):
            await engine.run_once()

        assert engine.dispatcher.notify_error.call_count == 2

    async def test_notifications_on_error_disabled_suppresses_push(
        self, build_engine, temp_schedule
    ):
        engine = build_engine(on_error=False)
        self._write_schedule(temp_schedule)

        failing_result = ActionResult(
            action_type="water_heat_start", success=False, message="HA rejected command"
        )
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])
        # Restore the real notify_error (gated internally) instead of the AsyncMock override
        engine.dispatcher.notify_error = AsyncMock(wraps=engine.dispatcher.notify_error)
        send_notification = AsyncMock()
        engine.dispatcher._send_notification = send_notification

        for _ in range(ACTION_FAILURE_NOTIFY_STREAK + 1):
            await engine.run_once()

        send_notification.assert_not_called()
