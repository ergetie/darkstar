"""
Tests for Executor Actions (HAClient and ActionDispatcher)

Tests with mocked HTTP requests to avoid needing a live Home Assistant instance.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from executor.actions import (
    ActionDispatcher,
    ActionResult,
    HACallError,
    HAClient,
    _clamp_to_entity_range,
)
from executor.controller import ControllerDecision
from executor.profiles import ModeAction, load_profile


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

        other_loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
        other_session_holder: dict[str, aiohttp.ClientSession] = {}
        cleanup_requested = threading.Event()

        def _run_other_loop():
            # Create and use the loop in the thread that owns it.  The test
            # environment's selector loop does not reliably wake from a
            # cross-thread call_soon_threadsafe(), so use an explicit handoff
            # and run cleanup on this owning thread instead.
            other_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(other_loop)
            other_loop_holder["loop"] = other_loop
            session = other_loop.run_until_complete(client._get_session())
            other_session_holder["session"] = session
            cleanup_requested.wait(timeout=5)
            other_loop.run_until_complete(session.close())

        thread = threading.Thread(target=_run_other_loop, daemon=True)
        thread.start()
        # Wait until the other loop has created its session.
        for _ in range(100):
            if "session" in other_session_holder and "loop" in other_loop_holder:
                break
            await asyncio.sleep(0.01)
        assert "session" in other_session_holder
        other_loop = other_loop_holder["loop"]

        # Create AND close a session on THIS (the current test's) event loop.
        this_session = await client._get_session()
        await client.close()

        other_session = other_session_holder["session"]
        assert this_session is not other_session
        assert not other_session.closed, "closing on one loop must not close another loop's session"

        # Clean up the other loop's session on its owning thread.
        cleanup_requested.set()
        # The worker exits immediately after cleanup; keep this synchronous so
        # the test does not create a default-executor worker that pytest must
        # wait for during asyncio loop shutdown.
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert other_session.closed
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
        ha_client.get_state = AsyncMock(return_value={"state": "50", "attributes": {}})

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
        ha_client.get_state = AsyncMock(return_value={"state": "40", "attributes": {}})

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
        ha_client.get_state = AsyncMock(return_value={"state": "40", "attributes": {}})
        ha_client.set_number = AsyncMock(return_value=True)

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
        ha_client.set_number.assert_called_once_with("input_number.water_heater_target", 50.0)


class TestSetWaterSwitch:
    """Test switch-controlled water heater actions."""

    @pytest.fixture
    def base_config(self):
        from executor.config import (
            ControllerConfig,
            ExecutorConfig,
            InverterConfig,
            NotificationConfig,
            WaterHeaterConfig,
        )

        return ExecutorConfig(
            inverter=InverterConfig(),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(temp_off=40),
            notifications=NotificationConfig(),
        )

    def _dispatcher(self, base_config, current="off", shadow_mode=False):
        from executor.actions import ActionDispatcher

        ha_client = MagicMock()
        ha_client.get_state_value = AsyncMock(return_value=current)
        ha_client.set_switch = AsyncMock(return_value=True)
        dispatcher = ActionDispatcher(ha_client, base_config, shadow_mode=shadow_mode)
        dispatcher._verify_action = AsyncMock(
            return_value=("on" if current == "on" else "off", True)
        )
        return dispatcher, ha_client

    @pytest.mark.asyncio
    async def test_turns_on_and_off(self, base_config):
        for desired, expected in ((True, "on"), (False, "off")):
            dispatcher, ha_client = self._dispatcher(
                base_config, current="off" if desired else "on"
            )
            result = await dispatcher.set_water_switch("switch.vvb", desired)
            assert result.success is True
            assert result.action_type == "water_switch"
            assert result.new_value == expected
            ha_client.set_switch.assert_awaited_once_with("switch.vvb", desired)

    @pytest.mark.asyncio
    async def test_skips_when_already_in_state(self, base_config):
        dispatcher, ha_client = self._dispatcher(base_config, current="on")

        result = await dispatcher.set_water_switch("switch.vvb", True)

        assert result.skipped is True
        ha_client.set_switch.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_in_shadow_mode(self, base_config):
        dispatcher, ha_client = self._dispatcher(base_config, current="off", shadow_mode=True)

        result = await dispatcher.set_water_switch("switch.vvb", True)

        assert result.success is True
        assert result.skipped is True
        ha_client.set_switch.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_number_entity(self, base_config):
        dispatcher, ha_client = self._dispatcher(base_config)

        result = await dispatcher.set_water_switch("number.vvb", True)

        assert result.success is False
        assert "Invalid domain" in result.message
        ha_client.get_state_value.assert_not_called()


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
        ha_client.get_state = AsyncMock(return_value={"state": "6", "attributes": {}})
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
        ha_client.get_state = AsyncMock(return_value={"state": "10", "attributes": {}})
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
        ha_client.get_state = AsyncMock(return_value={"state": "6", "attributes": {}})
        ha_client.set_number = AsyncMock(return_value=True)

        dispatcher = ActionDispatcher(ha_client=ha_client, config=base_config, shadow_mode=True)

        result = await dispatcher.set_ev_charger_current("number.goe_current", 10)

        assert result.success is True
        assert result.skipped is True
        assert "[SHADOW]" in result.message
        ha_client.set_number.assert_not_called()


class TestVerificationReadBack:
    """Read-back verification must tolerate inverters whose HA state lags the write."""

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

    @pytest.fixture
    def dispatcher(self, base_config):
        from unittest.mock import MagicMock

        from executor.actions import ActionDispatcher

        return ActionDispatcher(ha_client=MagicMock(), config=base_config, shadow_mode=False)

    @pytest.mark.asyncio
    async def test_retries_until_slow_entity_settles(self, dispatcher, monkeypatch):
        """A modbus-polled select reports its old option for a while after the write."""
        from unittest.mock import AsyncMock

        import executor.actions as actions_mod

        monkeypatch.setattr(actions_mod, "VERIFY_POLL_INTERVAL_MS", 1)
        dispatcher.ha.get_state_value = AsyncMock(
            side_effect=["Forced mode", "Forced mode", "Self-consumption mode"]
        )

        value, ok = await dispatcher._verify_action("select.ems_mode", "Self-consumption mode")

        assert ok is True
        assert value == "Self-consumption mode"
        assert dispatcher.ha.get_state_value.await_count == 3

    @pytest.mark.asyncio
    async def test_gives_up_after_max_wait(self, dispatcher, monkeypatch):
        from unittest.mock import AsyncMock

        import executor.actions as actions_mod

        monkeypatch.setattr(actions_mod, "VERIFY_MAX_WAIT_MS", 3)
        monkeypatch.setattr(actions_mod, "VERIFY_POLL_INTERVAL_MS", 1)
        dispatcher.ha.get_state_value = AsyncMock(return_value="Forced mode")

        value, ok = await dispatcher._verify_action("select.ems_mode", "Self-consumption mode")

        assert ok is False
        assert value == "Forced mode"

    @pytest.mark.asyncio
    async def test_no_extra_read_when_already_correct(self, dispatcher):
        from unittest.mock import AsyncMock

        dispatcher.ha.get_state_value = AsyncMock(return_value="Self-consumption mode")

        value, ok = await dispatcher._verify_action("select.ems_mode", "Self-consumption mode")

        assert ok is True
        assert value == "Self-consumption mode"
        assert dispatcher.ha.get_state_value.await_count == 1

    @pytest.mark.asyncio
    async def test_unavailable_entity_reports_unknown(self, dispatcher, monkeypatch):
        from unittest.mock import AsyncMock

        import executor.actions as actions_mod

        monkeypatch.setattr(actions_mod, "VERIFY_MAX_WAIT_MS", 3)
        monkeypatch.setattr(actions_mod, "VERIFY_POLL_INTERVAL_MS", 1)
        dispatcher.ha.get_state_value = AsyncMock(return_value=None)

        value, ok = await dispatcher._verify_action("select.ems_mode", "Self-consumption mode")

        assert value is None
        assert ok is None


class TestClampToEntityRange:
    """Pure range/step clamp for numeric writes."""

    def test_above_max(self):
        value, note = _clamp_to_entity_range(18200.0, {"min": 0, "max": 17500, "step": 1})
        assert value == 17500
        assert note is not None and "max" in note

    def test_below_negative_min(self):
        value, note = _clamp_to_entity_range(
            -18000.0, {"min": -17500, "max": 17500, "step": 100}
        )
        assert value == -17500
        assert note is not None and "min" in note

    def test_step_snaps_from_min(self):
        value, _ = _clamp_to_entity_range(430.0, {"min": 50, "max": 1000, "step": 100})
        assert value == 450

    def test_half_step_rounds_up(self):
        value, _ = _clamp_to_entity_range(250.0, {"min": 0, "max": 1000, "step": 100})
        assert value == 300

    def test_rounding_past_max_snaps_down(self):
        value, _ = _clamp_to_entity_range(1040.0, {"min": 0, "max": 1050, "step": 100})
        assert value == 1000

    def test_rounding_below_min_snaps_up(self):
        value, _ = _clamp_to_entity_range(52.0, {"min": 55, "max": 1000, "step": 100})
        assert value == 55

    def test_fractional_step_has_no_float_noise(self):
        value, _ = _clamp_to_entity_range(0.34, {"min": 0, "max": 1, "step": 0.1})
        assert value == 0.3

    @pytest.mark.parametrize(
        "attributes",
        [
            None,
            {},
            {"min": "unavailable", "max": "unknown", "step": "any"},
            {"step": 0},
            {"step": -5},
            {"min": float("nan"), "max": float("inf")},
            {"min": 100, "max": 0},
        ],
    )
    def test_unusable_attributes_leave_value_unchanged(self, attributes):
        value, note = _clamp_to_entity_range(18200.0, attributes)
        assert value == 18200.0
        assert note is None

    def test_only_usable_bound_applied(self):
        value, _ = _clamp_to_entity_range(18200.0, {"max": 17500, "min": "unavailable"})
        assert value == 17500

    def test_numeric_string_attributes(self):
        value, _ = _clamp_to_entity_range(18200.0, {"min": "0", "max": "17500.0", "step": "100"})
        assert value == 17500

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "abc"])
    def test_non_finite_or_non_numeric_value_unchanged(self, value):
        result, note = _clamp_to_entity_range(value, {"min": 0, "max": 10, "step": 1})
        assert result is value or (result != result and value != value)
        assert note is None

    def test_value_within_range_keeps_original_object(self):
        value, note = _clamp_to_entity_range(5, {"min": 0, "max": 10, "step": 1})
        assert value == 5 and isinstance(value, int)
        assert note is None


def _profile_dispatcher(
    *, state: dict | None, set_number: AsyncMock | None = None
) -> tuple[ActionDispatcher, MagicMock, ModeAction]:
    """Dispatcher on the Fronius profile writing export_with_load_w to an input_number."""
    from executor.config import ExecutorConfig, InverterConfig

    ha = MagicMock(spec=HAClient)
    ha.get_state = AsyncMock(return_value=state)
    ha.get_state_value = AsyncMock(return_value=state["state"] if state else None)
    ha.set_number = set_number or AsyncMock(return_value=True)
    config = ExecutorConfig(
        inverter=InverterConfig(
            custom_entities={"grid_discharge_power": "input_number.darkstar_power_rec_w"}
        )
    )
    dispatcher = ActionDispatcher(ha, config, shadow_mode=False, profile=load_profile("fronius"))
    action = ModeAction(entity="grid_discharge_power", value="{{export_with_load_w}}")
    return dispatcher, ha, action


def _decision(export_with_load_w: float) -> ControllerDecision:
    return ControllerDecision(
        mode_intent="export",
        export_power_w=export_with_load_w,
        export_with_load_w=export_with_load_w,
    )


class TestProfilePathClamp:
    @pytest.mark.asyncio
    async def test_writes_clamped_value_and_reports_it(self):
        state = {"state": "10000", "attributes": {"min": 0, "max": 17500, "step": 100}}
        dispatcher, ha, action = _profile_dispatcher(state=state)
        with patch("executor.actions.asyncio.sleep", new_callable=AsyncMock):
            result = await dispatcher._execute_action(action, _decision(18200.0), "export")
        ha.set_number.assert_awaited_once_with("input_number.darkstar_power_rec_w", 17500.0)
        assert result.new_value == 17500
        assert "requested 18200" in result.message

    @pytest.mark.asyncio
    async def test_entity_at_limit_is_skipped(self):
        state = {"state": "17500", "attributes": {"min": 0, "max": 17500, "step": 100}}
        dispatcher, ha, action = _profile_dispatcher(state=state)
        result = await dispatcher._execute_action(action, _decision(18200.0), "export")
        assert result.skipped is True
        assert "Already at" in result.message
        ha.set_number.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_state_unavailable_writes_unclamped(self):
        dispatcher, ha, action = _profile_dispatcher(state=None)
        with patch("executor.actions.asyncio.sleep", new_callable=AsyncMock):
            result = await dispatcher._execute_action(action, _decision(18200.0), "export")
        ha.set_number.assert_awaited_once_with("input_number.darkstar_power_rec_w", 18200.0)
        assert result.new_value == 18200.0

    @pytest.mark.asyncio
    async def test_clamp_warning_logged_once_per_hour(self, caplog):
        state = {"state": "10000", "attributes": {"min": 0, "max": 17500}}
        dispatcher, _, action = _profile_dispatcher(state=state)
        clock = [1000.0]
        with (
            patch("executor.actions.time.monotonic", side_effect=lambda: clock[0]),
            patch("executor.actions.asyncio.sleep", new_callable=AsyncMock),
            caplog.at_level("DEBUG", logger="executor.actions"),
        ):
            for _ in range(12):
                clock[0] += 60.0
                await dispatcher._execute_action(action, _decision(18200.0), "export")
            warnings = [r for r in caplog.records if r.levelname == "WARNING" and "Clamped" in r.message]
            assert len(warnings) == 1
            clock[0] += 3600.0
            await dispatcher._execute_action(action, _decision(18200.0), "export")
        warnings = [r for r in caplog.records if r.levelname == "WARNING" and "Clamped" in r.message]
        assert len(warnings) == 2


class TestProfilePathErrorText:
    @pytest.mark.asyncio
    async def test_http_error_populates_error_details_and_message(self):
        state = {"state": "10000", "attributes": {}}
        set_number = AsyncMock(
            side_effect=HACallError(
                "HA service call failed", status_code=400, response_body="value out of range"
            )
        )
        dispatcher, _, action = _profile_dispatcher(state=state, set_number=set_number)
        result = await dispatcher._execute_action(action, _decision(18200.0), "export")
        assert result.success is False
        assert result.error_details is not None
        assert "HTTP 400" in result.error_details
        assert "value out of range" in result.error_details
        assert result.message.startswith("Failed to set input_number.darkstar_power_rec_w: ")
        assert "value out of range" in result.message
        assert result.ha_unavailable is False

    @pytest.mark.asyncio
    async def test_statusless_error_marks_ha_unavailable(self):
        state = {"state": "10000", "attributes": {}}
        set_number = AsyncMock(
            side_effect=HACallError("retries exhausted", exception_type="ClientConnectorError")
        )
        dispatcher, _, action = _profile_dispatcher(state=state, set_number=set_number)
        result = await dispatcher._execute_action(action, _decision(18200.0), "export")
        assert result.success is False
        assert result.ha_unavailable is True


class TestWriteEntityClamp:
    """Non-profile numeric writes go through `_write_entity` and are clamped too."""

    @pytest.mark.asyncio
    async def test_write_entity_clamps_fetching_state_once(self):
        state = {"state": "1", "attributes": {"min": 0, "max": 17500}}
        dispatcher, ha, _ = _profile_dispatcher(state=state)
        ok = await dispatcher._write_entity("number.max_export", 18200.0, "number")
        assert ok is True
        ha.get_state.assert_awaited_once_with("number.max_export")
        ha.set_number.assert_awaited_once_with("number.max_export", 17500.0)

    @pytest.mark.asyncio
    async def test_supplied_state_is_not_refetched(self):
        dispatcher, ha, _ = _profile_dispatcher(state=None)
        await dispatcher._write_entity(
            "number.max_export",
            18200.0,
            "number",
            entity_state={"state": "1", "attributes": {"max": 100}},
        )
        ha.get_state.assert_not_awaited()
        ha.set_number.assert_awaited_once_with("number.max_export", 100.0)

    @pytest.mark.asyncio
    async def test_non_number_domains_do_not_fetch_state(self):
        dispatcher, ha, _ = _profile_dispatcher(state=None)
        ha.set_switch = AsyncMock(return_value=True)
        await dispatcher._write_entity("switch.x", "1", "switch")
        ha.get_state.assert_not_awaited()


class TestClampedNonProfileWritesVerifyAgainstClamp:
    """A clamped non-profile numeric write is skipped, written and verified at the clamped value."""

    @staticmethod
    def _dispatcher(entity_state: dict, verify_state: str):
        from executor.config import ExecutorConfig, InverterConfig, WaterHeaterConfig

        ha = MagicMock(spec=HAClient)
        ha.get_state = AsyncMock(return_value=entity_state)
        ha.get_state_value = AsyncMock(return_value=verify_state)
        ha.set_number = AsyncMock(return_value=True)
        config = ExecutorConfig(
            inverter=InverterConfig(grid_max_export_power="number.max_export"),
            water_heater=WaterHeaterConfig(temp_off=40),
        )
        return ActionDispatcher(ha, config, shadow_mode=False), ha

    @pytest.mark.asyncio
    async def test_water_temp_clamped_write_verifies_clamped_value(self):
        dispatcher, ha = self._dispatcher(
            {"state": "40", "attributes": {"min": 35, "max": 60, "step": 1}}, verify_state="60"
        )
        result = await dispatcher.set_water_temp(75, "number.water_target")

        assert result.success is True
        assert result.new_value == 60
        assert result.verification_success is True
        assert result.verified_value == 60
        ha.set_number.assert_awaited_once_with("number.water_target", 60.0)

    @pytest.mark.asyncio
    async def test_water_temp_already_at_limit_is_skipped(self):
        dispatcher, ha = self._dispatcher(
            {"state": "60", "attributes": {"min": 35, "max": 60, "step": 1}}, verify_state="60"
        )
        result = await dispatcher.set_water_temp(75, "number.water_target")

        assert result.skipped is True
        assert result.success is True
        ha.set_number.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_max_export_power_clamped_write_verifies_clamped_value(self):
        dispatcher, ha = self._dispatcher(
            {"state": "5000", "attributes": {"min": 0, "max": 17500, "step": 100}},
            verify_state="17500",
        )
        result = await dispatcher._set_max_export_power(18200.0)

        assert result is not None
        assert result.success is True
        assert result.new_value == 17500
        assert result.verification_success is True
        ha.set_number.assert_awaited_once_with("number.max_export", 17500)

    @pytest.mark.asyncio
    async def test_ev_current_clamped_write_verifies_clamped_value(self):
        dispatcher, ha = self._dispatcher(
            {"state": "6", "attributes": {"min": 6, "max": 16, "step": 1}}, verify_state="16"
        )
        result = await dispatcher.set_ev_charger_current("number.ev_current", 20)

        assert result.success is True
        assert result.new_value == 16
        assert result.verification_success is True
        ha.set_number.assert_awaited_once_with("number.ev_current", 16.0)
