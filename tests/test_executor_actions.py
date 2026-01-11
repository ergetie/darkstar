"""
Tests for Executor Actions (HAClient and ActionDispatcher)

Tests with mocked HTTP requests to avoid needing a live Home Assistant instance.
"""

from unittest.mock import MagicMock, patch

import pytest

from executor.actions import ActionDispatcher, ActionResult, HAClient
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.controller import ControllerDecision


class TestActionResult:
    """Test the ActionResult dataclass."""

    def test_required_fields(self):
        """ActionResult requires action_type and success."""
        result = ActionResult(action_type="work_mode", success=True)
        assert result.action_type == "work_mode"
        assert result.success is True

    def test_default_values(self):
        """ActionResult has sensible defaults."""
        result = ActionResult(action_type="test", success=True)
        assert result.message == ""
        assert result.previous_value is None
        assert result.new_value is None
        assert result.skipped is False
        assert result.duration_ms == 0


class TestHAClientGetState:
    """Test HAClient.get_state and get_state_value."""

    def test_get_state_success(self):
        """get_state returns parsed JSON on success."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "entity_id": "switch.test",
                "state": "on",
            }
            mock_session.get.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            result = client.get_state("switch.test")

            assert result == {"entity_id": "switch.test", "state": "on"}
            mock_session.get.assert_called_once()

    def test_get_state_failure_returns_none(self):
        """get_state returns None on request error."""
        import requests

        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_session.get.side_effect = requests.RequestException("Connection error")

            client = HAClient("http://ha:8123", "token123")
            result = client.get_state("switch.test")

            assert result is None

    def test_get_state_value_extracts_state(self):
        """get_state_value returns just the state string."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_response.json.return_value = {"state": "Export First"}
            mock_session.get.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            result = client.get_state_value("select.work_mode")

            assert result == "Export First"


class TestHAClientCallService:
    """Test HAClient.call_service."""

    def test_call_service_success(self):
        """call_service returns True on success."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_session.post.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            result = client.call_service("switch", "turn_on", "switch.test")

            assert result is True
            mock_session.post.assert_called_once()

    def test_call_service_failure(self):
        """call_service returns False on error."""
        import requests

        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_session.post.side_effect = requests.RequestException("Failed")

            client = HAClient("http://ha:8123", "token123")
            result = client.call_service("switch", "turn_on", "switch.test")

            assert result is False

    def test_set_select_option(self):
        """set_select_option calls select.select_option."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_session.post.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            client.set_select_option("select.mode", "Export First")

            # Verify the call was made to the correct endpoint
            call_args = mock_session.post.call_args
            assert "select/select_option" in call_args[0][0]

    def test_set_switch_on(self):
        """set_switch(True) calls switch.turn_on."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_session.post.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            client.set_switch("switch.charging", True)

            call_args = mock_session.post.call_args
            assert "switch/turn_on" in call_args[0][0]

    def test_set_switch_off(self):
        """set_switch(False) calls switch.turn_off."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_session.post.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            client.set_switch("switch.charging", False)

            call_args = mock_session.post.call_args
            assert "switch/turn_off" in call_args[0][0]


class TestHAClientSendNotification:
    """Test HAClient.send_notification."""

    def test_send_notification_parses_service(self):
        """send_notification correctly parses service name."""
        with patch("executor.actions.requests.Session") as MockSession:
            mock_session = MockSession.return_value
            mock_response = MagicMock()
            mock_session.post.return_value = mock_response

            client = HAClient("http://ha:8123", "token123")
            result = client.send_notification(
                "notify.mobile_app",
                "Test Title",
                "Test Message",
            )

            assert result is True
            call_args = mock_session.post.call_args
            assert "notify/mobile_app" in call_args[0][0]

    def test_send_notification_invalid_format(self):
        """send_notification returns False for invalid service format."""
        with patch("executor.actions.requests.Session"):
            client = HAClient("http://ha:8123", "token123")
            result = client.send_notification("invalid", "Title", "Msg")

            assert result is False


class TestActionDispatcherIdempotency:
    """Test ActionDispatcher idempotent execution."""

    @pytest.fixture
    def mock_ha_client(self):
        """Create a mock HA client."""
        return MagicMock(spec=HAClient)

    @pytest.fixture
    def executor_config(self):
        """Create an executor config."""
        return ExecutorConfig(
            inverter=InverterConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
            controller=ControllerConfig(),
        )

    def test_work_mode_skips_if_already_set(self, mock_ha_client, executor_config):
        """Work mode action is skipped if already at target."""
        mock_ha_client.get_state_value.return_value = "Export First"

        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        result = dispatcher._set_work_mode("Export First")

        assert result.skipped is True
        assert "Already at" in result.message
        mock_ha_client.set_select_option.assert_not_called()

    def test_work_mode_executes_if_different(self, mock_ha_client, executor_config):
        """Work mode action executes if target differs from current."""
        mock_ha_client.get_state_value.return_value = "Zero Export To CT"
        mock_ha_client.set_select_option.return_value = True

        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        result = dispatcher._set_work_mode("Export First")

        assert result.skipped is False
        assert result.success is True
        mock_ha_client.set_select_option.assert_called_once()

    def test_grid_charging_skips_if_already_set(self, mock_ha_client, executor_config):
        """Grid charging is skipped if already at target state."""
        mock_ha_client.get_state_value.return_value = "on"

        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        result = dispatcher._set_grid_charging(True)

        assert result.skipped is True
        mock_ha_client.set_switch.assert_not_called()

    def test_soc_target_skips_if_already_set(self, mock_ha_client, executor_config):
        """SoC target is skipped if already at target."""
        mock_ha_client.get_state_value.return_value = "80"

        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        result = dispatcher._set_soc_target(80)

        assert result.skipped is True
        mock_ha_client.set_input_number.assert_not_called()


class TestActionDispatcherShadowMode:
    """Test ActionDispatcher shadow mode (no real actions)."""

    @pytest.fixture
    def mock_ha_client(self):
        """Create a mock HA client."""
        client = MagicMock(spec=HAClient)
        client.get_state_value.return_value = "Zero Export To CT"
        return client

    @pytest.fixture
    def executor_config(self):
        """Create an executor config."""
        return ExecutorConfig(
            shadow_mode=True,
            inverter=InverterConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
            controller=ControllerConfig(),
        )

    def test_shadow_mode_logs_but_doesnt_execute(self, mock_ha_client, executor_config):
        """Shadow mode logs intended actions but doesn't execute."""
        dispatcher = ActionDispatcher(mock_ha_client, executor_config, shadow_mode=True)
        result = dispatcher._set_work_mode("Export First")

        assert result.success is True
        assert result.skipped is True
        assert "[SHADOW]" in result.message
        mock_ha_client.set_select_option.assert_not_called()

    def test_shadow_mode_charge_current(self, mock_ha_client, executor_config):
        """Shadow mode logs charge current changes."""
        dispatcher = ActionDispatcher(mock_ha_client, executor_config, shadow_mode=True)
        result = dispatcher._set_charge_current(100.0)

        assert result.success is True
        assert "[SHADOW]" in result.message
        mock_ha_client.set_number.assert_not_called()

    def test_shadow_mode_max_export_power(self, mock_ha_client, executor_config):
        """Shadow mode logs max export power changes."""
        dispatcher = ActionDispatcher(mock_ha_client, executor_config, shadow_mode=True)
        result = dispatcher._set_max_export_power(5000.0)

        assert result.success is True
        assert "[SHADOW]" in result.message
        assert result.new_value == 5000.0
        mock_ha_client.set_number.assert_not_called()


class TestActionDispatcherExecute:
    """Test ActionDispatcher.execute full flow."""

    @pytest.fixture
    def mock_ha_client(self):
        """Create a mock HA client that returns current states."""
        client = MagicMock(spec=HAClient)
        # Return different states for different entities
        client.get_state_value.side_effect = lambda e: {
            "select.inverter_work_mode": "Zero Export To CT",
            "switch.inverter_battery_grid_charging": "off",
            "input_number.vvbtemp": "40",
        }.get(e)
        client.set_select_option.return_value = True
        client.set_switch.return_value = True
        client.set_number.return_value = True
        client.set_input_number.return_value = True
        return client

    @pytest.fixture
    def executor_config(self):
        """Create an executor config."""
        return ExecutorConfig(
            inverter=InverterConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(
                on_charge_start=False,
                on_export_start=False,
            ),
            controller=ControllerConfig(),
        )

    def test_execute_returns_results_for_all_actions(self, mock_ha_client, executor_config):
        """execute() returns results for all actions taken."""
        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        decision = ControllerDecision(
            work_mode="Export First",
            grid_charging=False,
            charge_current_a=0,
            discharge_current_a=190,
            soc_target=50,
            water_temp=60,
            write_charge_current=False,
            write_discharge_current=True,
        )

        results = dispatcher.execute(decision)

        # Should have: work_mode, grid_charging, discharge_current, soc_target, water_temp, max_export_power
        # (no charge_current because write_charge_current=False)
        assert len(results) == 6
        action_types = [r.action_type for r in results]
        assert "work_mode" in action_types
        assert "grid_charging" in action_types
        assert "discharge_current" in action_types
        assert "soc_target" in action_types
        assert "water_temp" in action_types
        assert "max_export_power" in action_types

    def test_execute_only_writes_current_when_flagged(self, mock_ha_client, executor_config):
        """Charge/discharge current only written when flags are True."""
        dispatcher = ActionDispatcher(mock_ha_client, executor_config)
        decision = ControllerDecision(
            work_mode="Zero Export To CT",
            grid_charging=False,
            charge_current_a=100,
            discharge_current_a=50,
            soc_target=50,
            water_temp=40,
            write_charge_current=False,  # Don't write
            write_discharge_current=False,  # Don't write
        )

        results = dispatcher.execute(decision)

        action_types = [r.action_type for r in results]
        assert "charge_current" not in action_types
        assert "discharge_current" not in action_types
        assert (
            "max_export_power" in action_types
        )  # Still called as it doesn't have a write flag yet
