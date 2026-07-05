"""
Tests for Executor Engine Integration

Integration tests for the full ExecutorEngine with mocked HA client and schedule.json.
"""

import contextlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytz
from sqlalchemy import create_engine

from backend.learning.models import Base
from executor.actions import HAClient
from executor.config import (
    ControllerConfig,
    EVChargerDeviceConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import EVChargerState, ExecutorEngine, ExecutorStatus
from executor.override import SlotPlan


@pytest.fixture
def temp_schedule():
    """Create a temporary schedule.json file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        schedule_path = f.name

    yield schedule_path

    with contextlib.suppress(OSError):
        Path(schedule_path).unlink()


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    # Create schema
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    yield db_path

    with contextlib.suppress(OSError):
        Path(db_path).unlink()


def make_schedule(slots: list, timezone: str = "Europe/Stockholm") -> dict:
    """Create a schedule payload with given slots."""
    return {
        "schedule": slots,
        "meta": {
            "generated_at": datetime.now(pytz.timezone(timezone)).isoformat(),
        },
    }


def make_slot(
    start: datetime,
    charge_kw: float = 0,
    export_kwh: float = 0,
    water_kw: float = 0,
    soc_target: int = 50,
) -> dict:
    """Create a slot entry."""
    end = start + timedelta(minutes=15)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "end_time_kepler": end.isoformat(),
        "battery_charge_kw": charge_kw,
        "battery_discharge_kw": 0,
        "export_kwh": export_kwh,
        "water_heating_kw": water_kw,
        "soc_target_percent": soc_target,
        "projected_soc_percent": soc_target - 5,
    }


class TestExecutorStatus:
    """Test ExecutorStatus dataclass."""

    def test_default_values(self):
        """ExecutorStatus has sensible defaults."""
        status = ExecutorStatus()
        assert status.enabled is False
        assert status.shadow_mode is False
        assert status.last_run_status == "pending"

    def test_custom_values(self):
        """ExecutorStatus accepts custom values."""
        status = ExecutorStatus(enabled=True, shadow_mode=True)
        assert status.enabled is True
        assert status.shadow_mode is True


class TestExecutorEngineInit:
    """Test ExecutorEngine initialization."""

    def test_creates_history_manager(self, temp_db):
        """Engine creates ExecutionHistory on init."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path="schedule.json",
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    engine = ExecutorEngine("config.yaml")

                    assert engine.history is not None


class TestLoadCurrentSlot:
    """Test ExecutorEngine._load_current_slot."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine with temp files."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    engine = ExecutorEngine("config.yaml")
                    engine.config.schedule_path = temp_schedule
                    yield engine

    def test_no_schedule_file_returns_none(self, engine):
        """Missing schedule file returns None."""
        engine.config.schedule_path = "/nonexistent/schedule.json"
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        slot, slot_start = engine._load_current_slot(now)

        assert slot is None
        assert slot_start is None

    def test_empty_schedule_returns_none(self, engine, temp_schedule):
        """Empty schedule returns None."""
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        slot, _slot_start = engine._load_current_slot(now)

        assert slot is None

    def test_finds_current_slot(self, engine, temp_schedule):
        """Finds slot containing current time."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # Create a slot that spans now
        slot_start = now - timedelta(minutes=5)

        schedule = make_schedule(
            [
                make_slot(slot_start, charge_kw=5.0, soc_target=80),
            ]
        )
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        slot, start_iso = engine._load_current_slot(now)

        assert slot is not None
        assert slot.charge_kw == 5.0
        assert slot.soc_target == 80
        assert start_iso is not None

    def test_no_matching_slot_returns_none(self, engine, temp_schedule):
        """Returns None when no slot matches current time."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        # Create slots in the past
        old_slot = now - timedelta(hours=2)

        schedule = make_schedule(
            [
                make_slot(old_slot, charge_kw=5.0),
            ]
        )
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        slot, _ = engine._load_current_slot(now)

        assert slot is None


class TestParseSlotPlan:
    """Test ExecutorEngine._parse_slot_plan."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_parses_charge_slot(self, engine):
        """Parses a charging slot correctly."""
        slot_data = {
            "battery_charge_kw": 5.0,
            "battery_discharge_kw": 0.0,
            "export_kwh": 0.0,
            "water_heating_kw": 0.0,
            "soc_target_percent": 80,
            "projected_soc_percent": 75,
        }

        slot = engine._parse_slot_plan(slot_data)

        assert slot.charge_kw == 5.0
        assert slot.discharge_kw == 0.0
        assert slot.soc_target == 80

    def test_parses_export_slot(self, engine):
        """Parses an export slot correctly (kWh to kW conversion)."""
        slot_data = {
            "battery_charge_kw": 0.0,
            "export_kwh": 2.0,  # 2 kWh per 15-min slot = 8 kW
            "soc_target_percent": 50,
        }

        slot = engine._parse_slot_plan(slot_data)

        assert slot.export_kw == 8.0  # 2 kWh * 4 = 8 kW

    def test_handles_missing_fields(self, engine):
        """Handles missing/null fields gracefully."""
        slot_data = {
            "soc_target_percent": 60,
        }

        slot = engine._parse_slot_plan(slot_data)

        assert slot.charge_kw == 0.0
        assert slot.export_kw == 0.0
        assert slot.soc_target == 60


class TestQuickActions:
    """Test ExecutorEngine quick action system."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_set_quick_action(self, engine):
        """Can set a quick action."""
        result = engine.set_quick_action("force_charge", 30)

        assert result["success"] is True
        assert result["type"] == "force_charge"
        assert result["duration_minutes"] == 30
        assert "expires_at" in result

    def test_invalid_action_type_raises(self, engine):
        """Invalid action type raises ValueError."""
        with pytest.raises(ValueError):
            engine.set_quick_action("invalid_action", 30)

    def test_invalid_duration_raises(self, engine):
        """Invalid duration raises ValueError."""
        with pytest.raises(ValueError):
            engine.set_quick_action("force_charge", 45)  # Must be 15, 30, or 60

    def test_get_active_quick_action(self, engine):
        """Can retrieve active quick action."""
        engine.set_quick_action("force_charge", 60)

        action = engine.get_active_quick_action()

        assert action is not None
        assert action["type"] == "force_charge"
        assert action["remaining_minutes"] > 0

    def test_clear_quick_action(self, engine):
        """Can clear a quick action."""
        engine.set_quick_action("force_charge", 30)

        result = engine.clear_quick_action()

        assert result["success"] is True
        assert result["was_active"] is True

        # Should now be None
        assert engine.get_active_quick_action() is None


class TestGetStatus:
    """Test ExecutorEngine.get_status."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                enabled=True,
                shadow_mode=False,
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_get_status_returns_dict(self, engine):
        """get_status returns a dictionary with expected keys."""
        status = engine.get_status()

        assert isinstance(status, dict)
        assert "enabled" in status
        assert "shadow_mode" in status
        assert "version" in status
        assert "quick_action" in status

    def test_get_status_reflects_config(self, engine):
        """Status reflects config values."""
        engine.status.enabled = True
        engine.status.shadow_mode = False

        status = engine.get_status()

        assert status["enabled"] is True
        assert status["shadow_mode"] is False


@pytest.mark.asyncio
class TestRunOnce:
    """Test ExecutorEngine.run_once (single tick)."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine with mocked HA client."""
        with patch("executor.engine.load_executor_config") as mock_config:
            config = ExecutorConfig(
                enabled=True,
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
                automation_toggle_entity="input_boolean.automation",
                inverter=InverterConfig(),
                water_heater=WaterHeaterConfig(),
                notifications=NotificationConfig(),
                controller=ControllerConfig(),
            )
            mock_config.return_value = config

            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {"input_sensors": {}}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    engine = ExecutorEngine("config.yaml")

                    # Mock HA client
                    mock_ha = MagicMock(spec=HAClient)

                    # Default mock behavior: return "on" for booleans, "50" for numbers
                    def side_effect_get_state(entity_id):
                        if "input_boolean" in entity_id or "automation" in entity_id:
                            return "on"
                        if "soc" in entity_id:
                            return "50"
                        if "temp" in entity_id or "target" in entity_id:
                            return "55"
                        return "0.0"

                    mock_ha.get_state_value.side_effect = side_effect_get_state
                    mock_ha.set_select_option.return_value = True
                    mock_ha.set_switch.return_value = True
                    mock_ha.set_number.return_value = True
                    mock_ha.set_input_number.return_value = True
                    engine.ha_client = mock_ha

                    # Create dispatcher
                    from executor.actions import ActionDispatcher

                    engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)

                    yield engine

    async def test_run_once_returns_result(self, engine, temp_schedule):
        """run_once returns a result dict."""
        # Create empty schedule
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        result = await engine.run_once()

        assert isinstance(result, dict)
        assert "success" in result
        assert "executed_at" in result
        assert "actions" in result

    async def test_run_once_skips_when_automation_off(self, engine, temp_schedule):
        """run_once skips when automation toggle is off."""
        engine.ha_client.get_state_value.side_effect = None
        engine.ha_client.get_state_value.return_value = "off"

        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        result = await engine.run_once()

        assert result["success"] is True
        # Check that it was skipped
        assert any(a.get("reason") == "automation_disabled" for a in result["actions"])

    async def test_run_once_executes_with_schedule(self, engine, temp_schedule):
        """run_once executes actions when schedule exists."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        schedule = make_schedule(
            [
                make_slot(slot_start, charge_kw=5.0, soc_target=80),
            ]
        )
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        result = await engine.run_once()

        assert result["success"] is True
        assert len(result["actions"]) > 0

    async def test_run_once_logs_to_history(self, engine, temp_schedule):
        """run_once logs execution to history."""
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        await engine.run_once()

        # Check history has the record
        records = engine.history.get_history()
        assert len(records) >= 1

    async def test_tick_calls_set_water_temp_when_enabled(self, engine, temp_schedule):
        """_tick calls set_water_temp when water heater is enabled."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        # Enable water heater and set target entity
        engine._has_water_heater = True
        engine.config.water_heater.target_entity = "input_number.water_heater_target"

        schedule = make_schedule(
            [
                make_slot(slot_start, water_kw=3.0, soc_target=50),
            ]
        )
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # Mock the dispatcher's set_water_temp method (it's async)
        from unittest.mock import AsyncMock

        from executor.actions import ActionResult

        mock_result = ActionResult(
            action_type="water_temp",
            success=True,
            message="Set water temp to 50°C",
            previous_value=40,
            new_value=50,
            entity_id="input_number.water_heater_target",
            skipped=False,
        )
        engine.dispatcher.set_water_temp = AsyncMock(return_value=mock_result)

        result = await engine.run_once()

        # Assert set_water_temp was called
        engine.dispatcher.set_water_temp.assert_called_once()
        # Assert the result is in the actions
        assert any(a.get("type") == "water_temp" for a in result["actions"])

    async def test_ev_charging_kw_logged_in_execution_record(self, engine, temp_schedule):
        """ev_charging_kw from slot plan is included in the execution record (task 6.2)."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        # Write a schedule with ev_charging_kw
        end = slot_start + timedelta(minutes=15)
        slot = {
            "start_time": slot_start.isoformat(),
            "end_time": end.isoformat(),
            "end_time_kepler": end.isoformat(),
            "battery_charge_kw": 0,
            "battery_discharge_kw": 0,
            "export_kwh": 0,
            "water_heating_kw": 0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            "ev_charging_kw": 7.4,
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        result = await engine.run_once()

        assert result is not None
        records = engine.history.get_recent(limit=1)
        assert records
        assert records[0]["ev_charging_kw"] == pytest.approx(7.4)

    async def test_non_ev_slot_logs_zero_ev_charging_kw(self, engine, temp_schedule):
        """Non-EV slot logs ev_charging_kw = 0.0 in execution record."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        schedule = make_schedule([make_slot(slot_start, charge_kw=3.0, soc_target=80)])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        result = await engine.run_once()

        assert result is not None
        records = engine.history.get_recent(limit=1)
        assert records
        assert records[0]["ev_charging_kw"] == pytest.approx(0.0)

    async def test_tick_skips_water_temp_when_disabled(self, engine, temp_schedule):
        """_tick skips set_water_temp when water heater is disabled."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        # Disable water heater
        engine._has_water_heater = False
        engine.config.water_heater.target_entity = "input_number.water_heater_target"

        schedule = make_schedule(
            [
                make_slot(slot_start, water_kw=3.0, soc_target=50),
            ]
        )
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # Mock the dispatcher's set_water_temp method (it's async)
        from unittest.mock import AsyncMock

        engine.dispatcher.set_water_temp = AsyncMock()

        result = await engine.run_once()

        # Assert set_water_temp was NOT called
        engine.dispatcher.set_water_temp.assert_not_called()
        # Assert no water_temp action in results
        assert not any(a.get("type") == "water_temp" for a in result["actions"])

    async def test_ws_broadcast_failure_logs_and_record_persisted(self, engine, temp_schedule):
        """When ws_manager.emit_sync raises, error is logged and record stays in recent_errors."""
        from unittest.mock import AsyncMock, patch

        from executor.actions import ActionResult

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)

        schedule = make_schedule([make_slot(slot_start)])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # Make a dispatcher action fail so an error record is created
        failing_result = ActionResult(
            action_type="test_action",
            success=False,
            message="Forced failure for test",
            skipped=False,
        )
        engine.dispatcher.execute = AsyncMock(return_value=[failing_result])

        with patch("backend.core.websockets.ws_manager") as mock_ws:
            mock_ws.emit_sync.side_effect = RuntimeError("WS unavailable")
            result = await engine.run_once()

        # Record must still be persisted even when broadcast fails
        assert any(r["type"] == "test_action" for r in engine.recent_errors)


class TestGetStatusModeIntent:
    """Tests for mode_intent in get_status() (tasks 6.1 and 6.3)."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine with temp files."""
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    engine = ExecutorEngine("config.yaml")
                    engine.config.schedule_path = temp_schedule
                    yield engine

    @pytest.mark.parametrize(
        "charge_kw,export_kw,discharge_kw,soc_target,ev_kw,soc_pct,expected_mode",
        [
            (5.0, 0.0, 0.0, 80, 0.0, 50.0, "charge"),
            (0.0, 3.0, 3.0, 10, 0.0, 80.0, "export"),
            (0.0, 0.0, 0.0, 10, 0.0, 80.0, "self_consumption"),
            (0.0, 0.0, 0.0, 80, 0.0, 50.0, "idle"),
        ],
    )
    def test_get_status_returns_mode_intent_for_modes(
        self,
        engine,
        temp_schedule,
        charge_kw,
        export_kw,
        discharge_kw,
        soc_target,
        ev_kw,
        soc_pct,
        expected_mode,
    ):
        """get_status() returns correct mode_intent in current_slot_plan (task 6.1)."""
        from executor.override import SystemState

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        end = slot_start + timedelta(minutes=15)

        slot = {
            "start_time": slot_start.isoformat(),
            "end_time": end.isoformat(),
            "end_time_kepler": end.isoformat(),
            "battery_charge_kw": charge_kw,
            "battery_discharge_kw": discharge_kw,
            "export_kwh": export_kw * 0.25,  # kWh for 15-min slot
            "water_heating_kw": 0.0,
            "soc_target_percent": soc_target,
            "projected_soc_percent": soc_target - 5,
            "ev_charging_kw": ev_kw,
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # Provide a cached system state with the test SoC
        engine._last_system_state = SystemState(current_soc_percent=soc_pct)

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert status["current_slot_plan"]["mode_intent"] == expected_mode

    def test_get_status_mode_intent_null_when_no_cached_state(self, engine, temp_schedule):
        """get_status() sets mode_intent to null when no system state is cached (task 6.3)."""
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        end = slot_start + timedelta(minutes=15)

        slot = {
            "start_time": slot_start.isoformat(),
            "end_time": end.isoformat(),
            "end_time_kepler": end.isoformat(),
            "battery_charge_kw": 5.0,
            "battery_discharge_kw": 0.0,
            "export_kwh": 0.0,
            "water_heating_kw": 0.0,
            "soc_target_percent": 80,
            "projected_soc_percent": 75,
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # No cached system state
        engine._last_system_state = None

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert status["current_slot_plan"]["mode_intent"] is None
        # Other fields should still be populated
        assert status["current_slot_plan"]["charge_kw"] == pytest.approx(5.0)

    def test_get_status_mode_intent_null_when_no_profile(self, engine, temp_schedule):
        """get_status() sets mode_intent to null when profile is not loaded (task 6.3)."""
        from executor.override import SystemState

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        slot_start = now - timedelta(minutes=5)
        end = slot_start + timedelta(minutes=15)

        slot = {
            "start_time": slot_start.isoformat(),
            "end_time": end.isoformat(),
            "end_time_kepler": end.isoformat(),
            "battery_charge_kw": 5.0,
            "battery_discharge_kw": 0.0,
            "export_kwh": 0.0,
            "water_heating_kw": 0.0,
            "soc_target_percent": 80,
            "projected_soc_percent": 75,
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        # Profile is None (not loaded)
        engine._last_system_state = SystemState(current_soc_percent=50.0)
        engine.inverter_profile = None

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert status["current_slot_plan"]["mode_intent"] is None
        # Other fields should still be populated
        assert status["current_slot_plan"]["charge_kw"] == pytest.approx(5.0)


class TestParseSlotPlanPerDevice:
    """Task 6.10: _parse_slot_plan correctly extracts per-device EV plans."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_parses_per_device_ev_plans(self, engine):
        """ev_chargers dict in slot data is parsed into ev_charger_plans."""
        slot_data = {
            "soc_target_percent": 50,
            "ev_chargers": {"ev1": 7.4, "ev2": 11.0},
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.ev_charger_plans == {"ev1": 7.4, "ev2": 11.0}

    def test_empty_ev_chargers_dict(self, engine):
        """Empty dict produces empty ev_charger_plans."""
        slot_data = {
            "soc_target_percent": 50,
            "ev_chargers": {},
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.ev_charger_plans == {}

    def test_missing_ev_chargers_field(self, engine):
        """Missing ev_chargers field produces empty ev_charger_plans."""
        slot_data = {"soc_target_percent": 50}
        slot = engine._parse_slot_plan(slot_data)

        assert slot.ev_charger_plans == {}

    def test_old_format_ev_charging_kw_still_parsed(self, engine):
        """Backward compat: old ev_charging_kw scalar is still parsed as aggregate."""
        slot_data = {
            "soc_target_percent": 50,
            "ev_charging_kw": 7.4,
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.ev_charging_kw == pytest.approx(7.4)
        # No chargers configured in this fixture, so no per-device plans
        assert slot.ev_charger_plans == {}

    def test_old_format_fallback_maps_to_first_charger(self, temp_schedule, temp_db):
        """Old-format schedule maps aggregate ev_charging_kw to first configured charger."""
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

        slot_data = {"soc_target_percent": 50, "ev_charging_kw": 7.4}
        slot = eng._parse_slot_plan(slot_data)

        assert slot.ev_charging_kw == pytest.approx(7.4)
        assert slot.ev_charger_plans == {"ev1": pytest.approx(7.4)}


class TestControlEvChargerPerDevice:
    """Task 6.10: _control_ev_charger loops over configured chargers independently."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
                ev_chargers=[
                    EVChargerDeviceConfig(id="ev1", switch_entity="switch.ev1"),
                    EVChargerDeviceConfig(id="ev2", switch_entity="switch.ev2"),
                ],
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    eng = ExecutorEngine("config.yaml")
                    eng._has_ev_charger = True
                    yield eng

    @pytest.mark.asyncio
    async def test_per_device_state_initialized_independently(self, engine):
        """Each charger gets its own EVChargerState entry after control loop."""
        from unittest.mock import AsyncMock, MagicMock

        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="off")

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="switch",
            message="ok",
            entity_id="switch.ev1",
            previous_value=None,
            new_value="off",
            verified_value="off",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=mock_result)

        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,
            export_kw=0.0,
            load_kw=0.0,
            water_kw=0.0,
            ev_charging_kw=0.0,
            soc_target=50,
            soc_projected=50,
            ev_charger_plans={},
        )

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await engine._control_ev_charger(slot, now)

        # Both chargers should have state entries after control loop runs
        assert "ev1" in engine._ev_charger_states
        assert "ev2" in engine._ev_charger_states
        assert isinstance(engine._ev_charger_states["ev1"], EVChargerState)
        assert isinstance(engine._ev_charger_states["ev2"], EVChargerState)

    @pytest.mark.asyncio
    async def test_charger_without_switch_entity_skipped(self, temp_schedule, temp_db):
        """Charger with no switch_entity is skipped (no HA call)."""
        from unittest.mock import AsyncMock

        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
                ev_chargers=[
                    EVChargerDeviceConfig(id="ev_no_switch", switch_entity=None),
                ],
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    eng = ExecutorEngine("config.yaml")
                    eng._has_ev_charger = True

        eng.ha_client = AsyncMock()
        eng.dispatcher = AsyncMock()

        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,
            export_kw=0.0,
            load_kw=0.0,
            water_kw=0.0,
            ev_charging_kw=0.0,
            soc_target=50,
            soc_projected=50,
            ev_charger_plans={"ev_no_switch": 7.4},
        )

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        await eng._control_ev_charger(slot, now)

        # No switch calls should have been made
        eng.dispatcher.set_ev_charger_switch.assert_not_called()

    @pytest.mark.asyncio
    async def test_safety_timeout_stops_charger(self, engine):
        """Charger running without plan for >30 min triggers safety stop."""
        from datetime import timedelta
        from unittest.mock import AsyncMock, MagicMock

        engine.ha_client = AsyncMock()
        engine.ha_client.get_state_value = AsyncMock(return_value="on")

        mock_result = MagicMock(
            success=True,
            skipped=False,
            duration_ms=5,
            action_type="switch",
            message="ok",
            entity_id="switch.ev1",
            previous_value="on",
            new_value="off",
            verified_value="off",
            verification_success=True,
            error_details=None,
        )
        engine.dispatcher = AsyncMock()
        engine.dispatcher.set_ev_charger_switch = AsyncMock(return_value=mock_result)

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Simulate charger has been running for 45 minutes without a plan
        engine._ev_charger_states["ev1"] = EVChargerState(
            charging_active=True,
            charging_started_at=now - timedelta(minutes=45),
            charging_slot_end=now - timedelta(minutes=30),
        )

        # No plan for ev1 (plan = 0.0)
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=0.0,
            export_kw=0.0,
            load_kw=0.0,
            water_kw=0.0,
            ev_charging_kw=0.0,
            soc_target=50,
            soc_projected=50,
            ev_charger_plans={"ev1": 0.0},
        )

        await engine._control_ev_charger(slot, now)

        # The charger should have been turned off due to safety timeout
        calls = engine.dispatcher.set_ev_charger_switch.call_args_list
        assert any(
            ("switch.ev1" in str(c) and "False" in str(c))
            or (c.args and c.args[0] == "switch.ev1" and c.kwargs.get("turn_on") is False)
            for c in calls
        ), "Expected safety-timeout stop call for switch.ev1"


class TestGetStatusEvChargerPlans:
    """Task 6.10: get_status() includes per-device EV plan."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_get_status_includes_ev_charger_plans(self, engine, temp_schedule):
        """get_status() returns ev_charger_plans in current_slot_plan."""
        from executor.override import SystemState

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
            "ev_charging_kw": 7.4,
            "ev_chargers": {"main_ev": 7.4},
        }
        schedule = make_schedule([slot])
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(schedule, f)

        engine._last_system_state = SystemState(current_soc_percent=50.0)
        engine.inverter_profile = None

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert "ev_charger_plans" in status["current_slot_plan"]
        assert status["current_slot_plan"]["ev_charger_plans"] == {"main_ev": 7.4}


class TestParseSlotPlanWaterHeaters:
    """Task 7.6: _parse_slot_plan correctly extracts per-device water heater plans."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    yield ExecutorEngine("config.yaml")

    def test_parses_new_format_water_heaters_dict(self, engine):
        """water_heaters dict with heating_kw values is parsed into water_heater_plans."""
        slot_data = {
            "soc_target_percent": 50,
            "water_heating_kw": 6.0,
            "water_heaters": {
                "wh1": {"heating_kw": 3.0},
                "wh2": {"heating_kw": 3.0},
            },
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.water_heater_plans == {"wh1": pytest.approx(3.0), "wh2": pytest.approx(3.0)}
        assert slot.water_kw == pytest.approx(6.0)

    def test_parses_flat_kw_values_in_water_heaters(self, engine):
        """water_heaters dict with flat float values (not nested) is also parsed."""
        slot_data = {
            "soc_target_percent": 50,
            "water_heaters": {"wh1": 3.0},
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.water_heater_plans == {"wh1": pytest.approx(3.0)}

    def test_missing_water_heaters_gives_empty_plans(self, engine):
        """Old-format slot with no water_heaters key gives empty water_heater_plans."""
        slot_data = {
            "soc_target_percent": 50,
            "water_heating_kw": 3.0,
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.water_heater_plans == {}
        assert slot.water_kw == pytest.approx(3.0)

    def test_empty_water_heaters_dict(self, engine):
        """Empty water_heaters dict gives empty water_heater_plans."""
        slot_data = {
            "soc_target_percent": 50,
            "water_heaters": {},
        }
        slot = engine._parse_slot_plan(slot_data)

        assert slot.water_heater_plans == {}


@pytest.mark.asyncio
class TestControlWaterHeatersPerDevice:
    """Task 7.6: per-device water heater temperature control in _tick()."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        from executor.actions import ActionDispatcher
        from executor.config import WaterHeaterDeviceConfig, WaterHeaterGlobalConfig

        with patch("executor.engine.load_executor_config") as mock_config:
            config = ExecutorConfig(
                enabled=True,
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
                automation_toggle_entity="input_boolean.automation",
                inverter=InverterConfig(),
                controller=ControllerConfig(),
                notifications=NotificationConfig(),
                water_heater=WaterHeaterGlobalConfig(temp_normal=60, temp_off=40),
                water_heater_devices=[
                    WaterHeaterDeviceConfig(
                        id="wh1",
                        name="Boiler 1",
                        target_entity="input_number.wh1_target",
                        power_kw=3.0,
                    ),
                    WaterHeaterDeviceConfig(
                        id="wh2",
                        name="Boiler 2",
                        target_entity="input_number.wh2_target",
                        power_kw=3.0,
                    ),
                ],
            )
            mock_config.return_value = config
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {"input_sensors": {}}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    eng = ExecutorEngine("config.yaml")

                    mock_ha = MagicMock(spec=HAClient)

                    def side_effect_get_state(entity_id):
                        if "input_boolean" in entity_id or "automation" in entity_id:
                            return "on"
                        if "soc" in entity_id:
                            return "50"
                        if "temp" in entity_id or "target" in entity_id:
                            return "55"
                        return "0.0"

                    mock_ha.get_state_value.side_effect = side_effect_get_state
                    mock_ha.set_select_option.return_value = True
                    mock_ha.set_switch.return_value = True
                    mock_ha.set_number.return_value = True
                    mock_ha.set_input_number.return_value = True
                    eng.ha_client = mock_ha
                    eng.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)
                    eng._has_water_heater = True
                    yield eng

    @pytest.mark.asyncio
    async def test_each_heater_gets_independent_ha_call(self, engine, temp_schedule):
        """Each configured water heater device gets its own set_water_temp call."""
        from unittest.mock import AsyncMock, call

        from executor.actions import ActionResult

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
            "water_heating_kw": 6.0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            "water_heaters": {
                "wh1": {"heating_kw": 3.0},
                "wh2": {"heating_kw": 3.0},
            },
        }
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(make_schedule([slot]), f)

        mock_result = ActionResult(action_type="water_temp", success=True)
        engine.dispatcher.set_water_temp = AsyncMock(return_value=mock_result)

        await engine.run_once()

        # Two separate calls — one per device
        assert engine.dispatcher.set_water_temp.call_count == 2
        calls = engine.dispatcher.set_water_temp.call_args_list
        # Both heaters should be set to normal (heating planned)
        assert call(60, "input_number.wh1_target") in calls
        assert call(60, "input_number.wh2_target") in calls

    @pytest.mark.asyncio
    async def test_heater_off_when_not_planned(self, engine, temp_schedule):
        """Heater with no planned kW gets temp_off temperature."""
        from unittest.mock import AsyncMock, call

        from executor.actions import ActionResult

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
            "water_heating_kw": 3.0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            "water_heaters": {
                "wh1": {"heating_kw": 3.0},
                "wh2": {"heating_kw": 0.0},
            },
        }
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(make_schedule([slot]), f)

        mock_result = ActionResult(action_type="water_temp", success=True)
        engine.dispatcher.set_water_temp = AsyncMock(return_value=mock_result)

        await engine.run_once()

        calls = engine.dispatcher.set_water_temp.call_args_list
        assert call(60, "input_number.wh1_target") in calls
        assert call(40, "input_number.wh2_target") in calls

    @pytest.mark.asyncio
    async def test_old_format_schedule_sets_all_devices_to_off(self, engine, temp_schedule):
        """Old-format schedule (no water_heaters dict) turns all devices to temp_off.

        When the schedule has no per-device breakdown, water_heater_plans is empty,
        so controller sets all devices to temp_off and still makes per-device HA calls.
        """
        from unittest.mock import AsyncMock, call

        from executor.actions import ActionResult

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
            "water_heating_kw": 3.0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            # No "water_heaters" dict — old format
        }
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(make_schedule([slot]), f)

        mock_result = ActionResult(action_type="water_temp", success=True)
        engine.dispatcher.set_water_temp = AsyncMock(return_value=mock_result)

        await engine.run_once()

        # Both devices controlled, set to temp_off (no per-device plan available)
        assert engine.dispatcher.set_water_temp.call_count == 2
        calls = engine.dispatcher.set_water_temp.call_args_list
        assert call(40, "input_number.wh1_target") in calls
        assert call(40, "input_number.wh2_target") in calls

    async def test_get_status_includes_water_heater_plans(self, engine, temp_schedule):
        """get_status() returns water_heater_plans in current_slot_plan."""
        from executor.override import SystemState

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
            "water_heating_kw": 6.0,
            "soc_target_percent": 50,
            "projected_soc_percent": 45,
            "water_heaters": {"wh1": {"heating_kw": 3.0}, "wh2": {"heating_kw": 3.0}},
        }
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump(make_schedule([slot]), f)

        engine._last_system_state = SystemState(current_soc_percent=50.0)
        engine.inverter_profile = None

        status = engine.get_status()

        assert status["current_slot_plan"] is not None
        assert "water_heater_plans" in status["current_slot_plan"]
        assert status["current_slot_plan"]["water_heater_plans"] == {
            "wh1": pytest.approx(3.0),
            "wh2": pytest.approx(3.0),
        }


class TestConfigCaching:
    """Tests for config mtime-based caching (executor-performance-fixes)."""

    def test_config_reload_skipped_when_mtime_unchanged(self, tmp_path):
        """Task 1.5: Config reload is skipped when file mtime is unchanged."""
        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        # Create a minimal config
        config_content = """
system:
  timezone: "Europe/Stockholm"
  has_solar: true
  has_battery: true
  has_water_heater: true
  has_ev_charger: false
executor:
  enabled: true
  shadow_mode: false
  interval_seconds: 60
  timezone: "Europe/Stockholm"
  controller:
    mode: "auto"
  inverter:
    control_unit: "percent"
"""
        config_path.write_text(config_content)
        secrets_path.write_text("home_assistant:\n  url: http://test\n  token: test_token\n")

        engine = ExecutorEngine(str(config_path), str(secrets_path))

        # Before first reload, mtime should be None
        assert engine._config_mtime is None

        # First call should load config (mtime is None initially)
        engine.reload_config()

        # After reload, mtime should be set
        assert engine._config_mtime is not None

        # Second call should skip reload (mtime unchanged)
        with patch("executor.engine.load_executor_config") as mock_load:
            engine.reload_config()
            mock_load.assert_not_called()

    def test_config_reloaded_when_mtime_changes(self, tmp_path):
        """Task 1.6: Config is re-parsed when file mtime changes."""
        import time

        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        # Create initial config
        config_content = """
system:
  timezone: "Europe/Stockholm"
  has_solar: true
  has_battery: true
  has_water_heater: true
  has_ev_charger: false
executor:
  enabled: true
  shadow_mode: false
  interval_seconds: 60
  timezone: "Europe/Stockholm"
  controller:
    mode: "auto"
  inverter:
    control_unit: "percent"
"""
        config_path.write_text(config_content)
        secrets_path.write_text("home_assistant:\n  url: http://test\n  token: test_token\n")

        engine = ExecutorEngine(str(config_path), str(secrets_path))

        # First call loads config
        engine.reload_config()
        initial_mtime = engine._config_mtime
        assert initial_mtime is not None

        # Wait a moment and update the file
        time.sleep(0.1)
        config_path.write_text(config_content + "\n# modified")

        # Second call should reload (mtime changed)
        with patch("executor.engine.load_executor_config") as mock_load:
            mock_config = MagicMock()
            mock_config.enabled = True
            mock_config.shadow_mode = False
            mock_load.return_value = mock_config

            engine.reload_config()
            mock_load.assert_called_once()
            assert engine._config_mtime != initial_mtime


class TestNordpoolPriceFetch:
    """Tests for Nordpool price fetch fix (executor-performance-fixes)."""

    @pytest.fixture
    def engine_with_battery(self, tmp_path):
        """Create engine with battery enabled."""
        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        config_content = """
system:
  timezone: "Europe/Stockholm"
  has_solar: true
  has_battery: true
  has_water_heater: true
battery:
  capacity_kwh: 27.0
executor:
  enabled: true
  shadow_mode: false
  interval_seconds: 300
  timezone: "Europe/Stockholm"
  has_battery: true
  controller:
    mode: "auto"
    system_voltage_v: 48.0
    charge_efficiency: 0.92
  inverter:
    control_unit: "percent"
"""
        config_path.write_text(config_content)
        secrets_path.write_text("home_assistant:\n  url: http://test\n  token: test_token\n")

        engine = ExecutorEngine(str(config_path), str(secrets_path))
        engine.config.has_battery = True
        return engine

    @pytest.mark.asyncio
    async def test_nordpool_price_fetched_via_await(self, engine_with_battery):
        """Task 2.3: Nordpool price is fetched successfully via await in executor tick."""
        from datetime import datetime
        from unittest.mock import AsyncMock

        import pytz

        from executor.controller import ControllerDecision
        from executor.override import SystemState

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        mock_prices = [
            {
                "start_time": now.replace(minute=0, second=0, microsecond=0),
                "import_price_sek_kwh": 1.25,
            }
        ]

        state = SystemState(current_soc_percent=50.0)
        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=10,
            discharge_value=0,
            soc_target=80,
            water_temp=50,
        )

        with patch("backend.core.prices.get_nordpool_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_prices

            await engine_with_battery._update_battery_cost(state, decision, None)

            mock_fetch.assert_called_once_with("config.yaml")

    @pytest.mark.asyncio
    async def test_nordpool_fallback_on_exception(self, engine_with_battery):
        """Task 2.4: Executor falls back to 0.5 SEK/kWh when Nordpool fetch raises an exception."""
        from unittest.mock import AsyncMock

        from backend.battery_cost import BatteryCostTracker
        from executor.controller import ControllerDecision
        from executor.override import SystemState

        state = SystemState(current_soc_percent=50.0)
        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=10,
            discharge_value=0,
            soc_target=80,
            water_temp=50,
        )

        with patch("backend.core.prices.get_nordpool_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Network error")

            with patch.object(BatteryCostTracker, "update_cost") as mock_update:
                await engine_with_battery._update_battery_cost(state, decision, None)

                # Check that update_cost was called with fallback price 0.5
                mock_update.assert_called_once()
                call_args = mock_update.call_args
                assert call_args.kwargs["import_price_sek"] == 0.5


@pytest.mark.asyncio
class TestWaterBoostCancellationNotification:
    """Test that the boost-cancellation notification is awaited (#24)."""

    @pytest.fixture
    def engine(self, temp_schedule, temp_db):
        """Create an engine with a real HA mock."""
        with patch("executor.engine.load_executor_config") as mock_config:
            config = ExecutorConfig(
                enabled=True,
                schedule_path=temp_schedule,
                timezone="Europe/Stockholm",
                automation_toggle_entity="input_boolean.automation",
                inverter=InverterConfig(),
                water_heater=WaterHeaterConfig(),
                notifications=NotificationConfig(),
                controller=ControllerConfig(),
            )
            mock_config.return_value = config

            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {"input_sensors": {}, "battery": {"min_soc_percent": 10.0}}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    engine = ExecutorEngine("config.yaml")

                    mock_ha = MagicMock(spec=HAClient)
                    mock_ha.get_state_value.return_value = "on"
                    mock_ha.set_select_option.return_value = True
                    mock_ha.set_switch.return_value = True
                    mock_ha.set_number.return_value = True
                    mock_ha.set_input_number.return_value = True
                    engine.ha_client = mock_ha

                    from executor.actions import ActionDispatcher

                    engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)

                    yield engine

    async def test_boost_cancelled_notification_is_awaited(self, engine, temp_schedule):
        """Notification is sent (and awaited) when boost is cancelled due to low SoC."""
        from datetime import timedelta
        from unittest.mock import AsyncMock

        import pytz

        tz = pytz.timezone("Europe/Stockholm")

        # Activate a water boost
        engine.set_water_boost(60)
        assert engine.get_water_boost_status() is not None

        # SoC = 5% < min_soc(10) + 10 = 20% → boost should be cancelled
        from executor.engine import SystemState

        low_soc_state = SystemState(current_soc_percent=5.0)
        engine._full_config["battery"] = {"min_soc_percent": 10.0}

        mock_notify = AsyncMock()
        engine.dispatcher._send_notification = mock_notify  # type: ignore[attr-defined]

        with patch.object(
            engine, "_gather_system_state", new=AsyncMock(return_value=low_soc_state)
        ):
            with Path(temp_schedule).open("w", encoding="utf-8") as f:
                json.dump({"schedule": []}, f)

            await engine.run_once()

        # Notification must have been awaited (not just called)
        mock_notify.assert_awaited_once()
        # Boost should be cleared
        assert engine.get_water_boost_status() is None


class TestCreateExecutionRecordErrorMessage:
    """Fix-observability-gaps #3: execution_log.error_message is populated at write time."""

    @pytest.fixture
    def engine(self, temp_db):
        with patch("executor.engine.load_executor_config") as mock_config:
            mock_config.return_value = ExecutorConfig(
                schedule_path="schedule.json",
                timezone="Europe/Stockholm",
            )
            with patch("executor.engine.load_yaml") as mock_yaml:
                mock_yaml.return_value = {}
                with patch.object(ExecutorEngine, "_get_db_path", return_value=temp_db):
                    return ExecutorEngine("config.yaml")

    def _make_record(self, engine, action_results, success):
        from executor.controller import ControllerDecision
        from executor.override import OverrideResult, SystemState

        return engine._create_execution_record(
            now_iso="2026-01-15T10:00:00+01:00",
            slot=SlotPlan(),
            slot_start="2026-01-15T10:00:00+01:00",
            state=SystemState(),
            decision=ControllerDecision(
                mode_intent="idle", charge_value=0, discharge_value=0, soc_target=50, water_temp=50
            ),
            override=OverrideResult(),
            action_results=action_results,
            success=success,
            duration_ms=10,
        )

    def test_failed_tick_persists_non_null_error_message(self, engine):
        from executor.actions import ActionResult

        action_results = [
            ActionResult(
                action_type="water_heat_start", success=False, message="HA rejected command"
            ),
            ActionResult(action_type="inverter_mode", success=True, message="OK"),
        ]
        record = self._make_record(engine, action_results, success=False)

        row_id = engine.history.log_execution(record)
        persisted = engine.history.get_history(limit=1)[0]

        assert row_id > 0
        assert persisted["error_message"] is not None
        assert "water_heat_start" in persisted["error_message"]
        assert "inverter_mode" not in persisted["error_message"]

    def test_successful_tick_has_null_error_message(self, engine):
        from executor.actions import ActionResult

        action_results = [
            ActionResult(action_type="water_heat_start", success=True, message="OK"),
        ]
        record = self._make_record(engine, action_results, success=True)

        engine.history.log_execution(record)
        persisted = engine.history.get_history(limit=1)[0]

        assert persisted["error_message"] is None
