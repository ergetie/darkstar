"""
Tests for Executor Actions (HAClient and ActionDispatcher)

Tests with mocked HTTP requests to avoid needing a live Home Assistant instance.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from executor.actions import ActionResult, HACallError, HAClient


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

    @pytest.mark.asyncio
    async def test_get_state_success(self):
        """get_state returns parsed JSON on success."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "entity_id": "switch.test",
                "state": "on",
            }
        )
        mock_response.raise_for_status = MagicMock()

        # Create mock session that returns mock_response as context manager
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.get.return_value = mock_cm

        # Patch _get_session to return our mock
        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.get_state("switch.test")
            assert result == {"entity_id": "switch.test", "state": "on"}

    @pytest.mark.asyncio
    async def test_get_state_failure_returns_none(self):
        """get_state returns None on request error."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock session that raises an error
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection error"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.get.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.get_state("switch.test")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_state_value_extracts_state(self):
        """get_state_value returns just the state string."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(return_value={"state": "Export First"})
        mock_response.raise_for_status = MagicMock()

        # Create mock session
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.get.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.get_state_value("select.work_mode")
            assert result == "Export First"


class TestHAClientCallService:
    """Test HAClient.call_service."""

    @pytest.mark.asyncio
    async def test_call_service_success(self):
        """call_service returns True on success."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        # Create mock session
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.call_service("switch", "turn_on", "switch.test")
            assert result is True

    @pytest.mark.asyncio
    async def test_call_service_failure(self):
        """call_service raises HACallError on request exception (REV F52 Phase 5)."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock session that raises an error
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("Connection refused"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            with pytest.raises(HACallError) as exc_info:
                await client.call_service("switch", "turn_on", "switch.test")

            assert exc_info.value.exception_type == "ClientError"

    @pytest.mark.asyncio
    async def test_call_service_timeout_raises_ha_call_error(self):
        """call_service raises HACallError on TimeoutError."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock session that raises TimeoutError
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=TimeoutError("Request timed out"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            with pytest.raises(HACallError) as exc_info:
                await client.call_service("switch", "turn_on", "switch.test")

            assert exc_info.value.exception_type == "TimeoutError"


class TestHAClientSetMethods:
    """Test HAClient setter methods."""

    @pytest.mark.asyncio
    async def test_set_select_option(self):
        """set_select_option calls select_option service."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        # Create mock session
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.set_select_option("select.mode", "Self Use")
            assert result is True

    @pytest.mark.asyncio
    async def test_set_switch(self):
        """set_switch calls turn_on/turn_off service."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        # Create mock session
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.set_switch("switch.test", True)
            assert result is True

    @pytest.mark.asyncio
    async def test_set_number(self):
        """set_number calls set_value service."""
        client = HAClient("http://ha:8123", "token123")

        # Create mock response
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()

        # Create mock session
        mock_session = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.post.return_value = mock_cm

        with patch.object(client, "_get_session", return_value=mock_session):
            result = await client.set_number("number.soc_target", 80.0)
            assert result is True


class TestHAClientValidation:
    """Test HAClient input validation."""

    @pytest.mark.asyncio
    async def test_get_state_with_none_entity(self):
        """get_state returns None for None entity_id."""
        client = HAClient("http://ha:8123", "token123")
        result = await client.get_state(None)  # type: ignore[arg-type]
        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_with_empty_entity(self):
        """get_state returns None for empty entity_id."""
        client = HAClient("http://ha:8123", "token123")
        result = await client.get_state("")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_with_whitespace_entity(self):
        """get_state returns None for whitespace-only entity_id."""
        client = HAClient("http://ha:8123", "token123")
        result = await client.get_state("   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_state_with_literal_none_string(self):
        """get_state returns None for literal 'None' string."""
        client = HAClient("http://ha:8123", "token123")
        result = await client.get_state("None")
        assert result is None


class TestHAClientSafetyGuards:
    """Test HAClient safety guards."""

    @pytest.mark.asyncio
    async def test_cannot_control_sensor_entity(self):
        """Safety guard prevents controlling sensor entities."""
        client = HAClient("http://ha:8123", "token123")

        with pytest.raises(HACallError) as exc_info:
            await client.set_number("sensor.temperature", 25.0)

        assert (
            "read-only" in str(exc_info.value).lower()
            or "invalid domain" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_cannot_control_binary_sensor(self):
        """Safety guard prevents controlling binary_sensor entities."""
        client = HAClient("http://ha:8123", "token123")

        with pytest.raises(HACallError) as exc_info:
            await client.set_switch("binary_sensor.motion", True)

        assert (
            "read-only" in str(exc_info.value).lower()
            or "invalid domain" in str(exc_info.value).lower()
        )


class TestHAClientCrossThreadSafety:
    """Test HAClient handles cross-thread event loop usage correctly.

    These tests verify the fix for: RuntimeError: Timeout context manager
    should be used inside a task, which occurred when the executor's
    background thread tried to use an HTTP client session created in
    the FastAPI main thread's event loop.
    """

    @pytest.mark.asyncio
    async def test_session_recreated_on_different_event_loop(self):
        """Session is recreated when used from a different event loop."""
        from unittest.mock import MagicMock, patch

        client = HAClient("http://ha:8123", "token123")

        # Create mock sessions for loop 1 and loop 2
        mock_session1 = MagicMock()
        mock_session1.closed = False
        mock_session2 = MagicMock()
        mock_session2.closed = False

        # Track which session was created
        sessions_created = []

        def mock_session_factory(*args, **kwargs):
            if len(sessions_created) == 0:
                sessions_created.append(mock_session1)
                return mock_session1
            else:
                sessions_created.append(mock_session2)
                return mock_session2

        # First call: Create session in loop 1
        loop1 = MagicMock()
        with (
            patch("executor.actions.aiohttp.ClientSession", side_effect=mock_session_factory),
            patch("asyncio.get_running_loop", return_value=loop1),
        ):
            session1 = await client._get_session()

        # Mark session1 as closed to trigger recreation
        mock_session1.closed = True

        # Second call: Use from loop 2 (simulates executor thread)
        loop2 = MagicMock()
        with (
            patch("executor.actions.aiohttp.ClientSession", side_effect=mock_session_factory),
            patch("asyncio.get_running_loop", return_value=loop2),
        ):
            session2 = await client._get_session()

        # Verify we got a different session, and both are retained per-loop
        # (never closed cross-loop — only a closed session is recreated).
        assert session1 is mock_session1
        assert session2 is mock_session2
        assert session1 is not session2
        assert client._sessions[loop2] is mock_session2

    @pytest.mark.asyncio
    async def test_session_reused_on_same_event_loop(self):
        """Session is reused when called from the same event loop."""
        from unittest.mock import MagicMock, patch

        client = HAClient("http://ha:8123", "token123")

        # Create mock session
        mock_session = MagicMock()
        mock_session.closed = False

        # Use same loop for both calls
        loop = MagicMock()

        with (
            patch("executor.actions.aiohttp.ClientSession", return_value=mock_session),
            patch("asyncio.get_running_loop", return_value=loop),
        ):
            session1 = await client._get_session()
            session2 = await client._get_session()

        # Verify we got the same session
        assert session1 is mock_session
        assert session2 is mock_session
        assert session1 is session2
        assert client._sessions[loop] is mock_session

    @pytest.mark.asyncio
    async def test_close_from_one_loop_does_not_close_session_on_another_loop(self):
        """Backend-owned session ownership (task 6.4): saving a schedule from
        the API's event loop must not close a real aiohttp session that was
        created on a different (e.g. the executor's) event loop."""
        import threading

        client = HAClient("http://ha:8123", "token123")

        other_loop = asyncio.new_event_loop()
        other_session_holder: dict[str, aiohttp.ClientSession] = {}

        def _run_other_loop():
            asyncio.set_event_loop(other_loop)
            session = other_loop.run_until_complete(client._get_session())
            other_session_holder["session"] = session
            other_loop.run_forever()

        thread = threading.Thread(target=_run_other_loop, daemon=True)
        thread.start()
        # Wait until the other loop has created its session.
        for _ in range(100):
            if "session" in other_session_holder:
                break
            await asyncio.sleep(0.01)
        assert "session" in other_session_holder

        # Create AND close a session on THIS (the current test's) event loop.
        this_session = await client._get_session()
        await client.close()

        other_session = other_session_holder["session"]
        assert this_session is not other_session
        assert not other_session.closed, "closing on one loop must not close another loop's session"

        # Clean up the other loop's session and thread.
        async def _cleanup():
            await other_session.close()

        fut = asyncio.run_coroutine_threadsafe(_cleanup(), other_loop)
        fut.result(timeout=5)
        other_loop.call_soon_threadsafe(other_loop.stop)
        thread.join(timeout=5)
        other_loop.close()


class TestSetWaterTemp:
    """Test ActionDispatcher.set_water_temp() method."""

    @pytest.fixture
    def base_config(self):
        """Create base config for water heater tests."""
        from executor.config import (
            ControllerConfig,
            ExecutorConfig,
            InverterConfig,
            NotificationConfig,
            WaterHeaterConfig,
            WaterHeaterDeviceConfig,
        )

        return ExecutorConfig(
            inverter=InverterConfig(),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(
                temp_normal=50,
                temp_off=40,
            ),
            water_heater_devices=[
                WaterHeaterDeviceConfig(
                    id="main",
                    name="Main Heater",
                    target_entity="input_number.water_heater_target",
                    power_kw=3.0,
                )
            ],
            notifications=NotificationConfig(),
        )

    @pytest.mark.asyncio
    async def test_set_water_temp_skips_when_already_at_target(self, base_config):
        """Idempotency: skip when current temperature equals target."""
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        # Mock HA client returns current temp = 50 (same as target)
        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value="50")

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=base_config,
            shadow_mode=False,
        )

        result = await dispatcher.set_water_temp(50, "input_number.water_heater_target")

        # Assert skipped because already at target
        assert result.success is True
        assert result.skipped is True
        assert result.action_type == "water_temp"
        assert result.previous_value == 50
        assert result.new_value == 50
        assert "Already at 50°C" in result.message

        # Assert no HA write was attempted
        ha_client.set_input_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_water_temp_respects_shadow_mode(self, base_config):
        """Shadow mode: return skipped result without HA call."""
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        # Mock HA client returns current temp = 40
        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value="40")

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=base_config,
            shadow_mode=True,  # Enable shadow mode
        )

        result = await dispatcher.set_water_temp(50, "input_number.water_heater_target")

        # Assert skipped due to shadow mode
        assert result.success is True
        assert result.skipped is True
        assert result.action_type == "water_temp"
        assert result.previous_value == 40
        assert result.new_value == 50
        assert "[SHADOW]" in result.message
        assert "40°C → 50°C" in result.message

        # Assert no HA write was attempted
        ha_client.set_input_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_water_temp_skips_when_entity_not_configured(self, base_config):
        """Skip when target entity is not configured."""
        from unittest.mock import MagicMock

        from executor.actions import ActionDispatcher

        ha_client = MagicMock()

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=base_config,
            shadow_mode=False,
        )

        # Pass None explicitly (or call without entity) to test not-configured path
        result = await dispatcher.set_water_temp(50, None)

        # Assert skipped due to entity not configured
        assert result.success is True
        assert result.skipped is True
        assert result.action_type == "water_temp"
        assert "not configured" in result.message.lower()

        # Assert no HA calls were made
        ha_client.get_state_value.assert_not_called()
        ha_client.set_input_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_water_temp_success(self, base_config):
        """Successfully set water temperature when conditions are met."""
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        # Mock HA client returns current temp = 40, set succeeds
        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value="40")
        ha_client.set_input_number = AsyncMock(return_value=True)

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=base_config,
            shadow_mode=False,
        )

        result = await dispatcher.set_water_temp(50, "input_number.water_heater_target")

        # Assert successful execution
        assert result.success is True
        assert result.skipped is False
        assert result.action_type == "water_temp"
        assert result.previous_value == 40
        assert result.new_value == 50
        assert "Changed 40°C → 50°C" in result.message

        # Assert HA write was attempted
        ha_client.set_input_number.assert_called_once_with("input_number.water_heater_target", 50.0)


class TestSetEvChargerCurrent:
    """universal-load-balancing 3.1: ActionDispatcher.set_ev_charger_current()."""

    @pytest.fixture
    def base_config(self):
        from executor.config import (
            ControllerConfig,
            ExecutorConfig,
            InverterConfig,
            NotificationConfig,
        )

        return ExecutorConfig(
            inverter=InverterConfig(),
            controller=ControllerConfig(),
            notifications=NotificationConfig(),
        )

    @pytest.mark.asyncio
    async def test_writes_new_setpoint(self, base_config):
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(side_effect=["6", "10"])  # before, then verify
        ha_client.set_number = AsyncMock(return_value=True)

        dispatcher = ActionDispatcher(ha_client=ha_client, config=base_config, shadow_mode=False)

        result = await dispatcher.set_ev_charger_current("number.goe_current", 10)

        assert result.success is True
        assert result.skipped is False
        assert result.action_type == "ev_charge_current"
        assert result.previous_value == "6"
        assert result.new_value == 10
        assert result.verified_value == "10"
        assert result.verification_success is True
        ha_client.set_number.assert_called_once_with("number.goe_current", 10.0)

    @pytest.mark.asyncio
    async def test_skips_when_already_at_target(self, base_config):
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value="10")
        ha_client.set_number = AsyncMock(return_value=True)

        dispatcher = ActionDispatcher(ha_client=ha_client, config=base_config, shadow_mode=False)

        result = await dispatcher.set_ev_charger_current("number.goe_current", 10)

        assert result.success is True
        assert result.skipped is True
        assert "already 10A" in result.message
        ha_client.set_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_shadow_mode_does_not_write(self, base_config):
        from unittest.mock import AsyncMock, MagicMock

        from executor.actions import ActionDispatcher

        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value="6")
        ha_client.set_number = AsyncMock(return_value=True)

        dispatcher = ActionDispatcher(ha_client=ha_client, config=base_config, shadow_mode=True)

        result = await dispatcher.set_ev_charger_current("number.goe_current", 10)

        assert result.success is True
        assert result.skipped is True
        assert "[SHADOW]" in result.message
        ha_client.set_number.assert_not_called()
