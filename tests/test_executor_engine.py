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

from executor.actions import HAClient
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.engine import ExecutorEngine, ExecutorStatus


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
        engine.set_quick_action("force_export", 60)

        action = engine.get_active_quick_action()

        assert action is not None
        assert action["type"] == "force_export"
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
                    mock_ha.get_state_value.return_value = "on"  # Automation on
                    mock_ha.set_select_option.return_value = True
                    mock_ha.set_switch.return_value = True
                    mock_ha.set_number.return_value = True
                    mock_ha.set_input_number.return_value = True
                    engine.ha_client = mock_ha

                    # Create dispatcher
                    from executor.actions import ActionDispatcher

                    engine.dispatcher = ActionDispatcher(mock_ha, config, shadow_mode=False)

                    yield engine

    def test_run_once_returns_result(self, engine, temp_schedule):
        """run_once returns a result dict."""
        # Create empty schedule
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        result = engine.run_once()

        assert isinstance(result, dict)
        assert "success" in result
        assert "executed_at" in result
        assert "actions" in result

    def test_run_once_skips_when_automation_off(self, engine, temp_schedule):
        """run_once skips when automation toggle is off."""
        engine.ha_client.get_state_value.return_value = "off"

        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        result = engine.run_once()

        assert result["success"] is True
        # Check that it was skipped
        assert any(a.get("reason") == "automation_disabled" for a in result["actions"])

    def test_run_once_executes_with_schedule(self, engine, temp_schedule):
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

        result = engine.run_once()

        assert result["success"] is True
        assert len(result["actions"]) > 0

    def test_run_once_logs_to_history(self, engine, temp_schedule):
        """run_once logs execution to history."""
        with Path(temp_schedule).open("w", encoding="utf-8") as f:
            json.dump({"schedule": []}, f)

        engine.run_once()

        # Check history has the record
        records = engine.history.get_history()
        assert len(records) >= 1
