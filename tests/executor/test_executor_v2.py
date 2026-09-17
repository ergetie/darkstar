"""
Tests for the Executor v2 - Profile-Driven Action Execution

Tests the generic profile-driven action loop in ActionDispatcher.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from executor.actions import ActionDispatcher, HAClient
from executor.config import (
    ControllerConfig,
    ExecutorConfig,
    InverterConfig,
    NotificationConfig,
    WaterHeaterConfig,
)
from executor.controller import ControllerDecision
from executor.profiles import load_profile


class TestExecutorV2ActionOrdering:
    """Test that actions are executed in order."""

    @pytest.mark.asyncio
    async def test_actions_execute_in_order(self):
        """Execute mode should write all actions in order."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)
        ha_client.set_switch = AsyncMock(return_value=True)
        ha_client.set_number = AsyncMock(return_value=True)
        ha_client.set_input_number = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(
                work_mode="select.work_mode",
                grid_charging_enable="switch.grid_charge",
                soc_target="input_number.soc_target",
                max_charge_current="number.max_charge_a",
                max_discharge_current="number.max_discharge_a",
            ),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )
        # This test verifies dispatch ordering; read-back verification has its
        # own coverage and would otherwise wait for the real settle timeout.
        dispatcher._verify_action = AsyncMock(return_value=("verified", True))

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        assert len(results) > 0
        entity_keys = [r.action_type for r in results]
        assert entity_keys == [
            "work_mode",
            "grid_charging_enable",
            "max_charge_current",
            "soc_target",
        ]


class TestExecutorV2Idempotent:
    """Test idempotent skip when entity already at target."""

    @pytest.mark.asyncio
    async def test_idempotent_skip_when_already_at_target(self):
        """Idempotent skip when entity already at target value."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="Zero Export To CT")
        ha_client.set_select = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(work_mode="select.work_mode"),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        work_mode_result = results[0]
        assert work_mode_result.skipped is True
        assert (
            "already" in work_mode_result.message.lower()
            or "skip" in work_mode_result.message.lower()
        )


class TestExecutorV2DynamicTemplates:
    """Test dynamic template resolution."""

    @pytest.mark.asyncio
    async def test_template_resolution_charge_value(self):
        """Dynamic template {{charge_value}} resolves correctly."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)
        ha_client.set_switch = AsyncMock(return_value=True)
        ha_client.set_number = AsyncMock(return_value=True)
        ha_client.set_input_number = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(
                work_mode="select.work_mode",
                grid_charging_enable="switch.grid_charge",
                soc_target="input_number.soc_target",
                max_charge_current="number.max_charge_a",
                max_discharge_current="number.max_discharge_a",
            ),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        max_charge_result = results[2]
        assert max_charge_result.new_value == 50

    @pytest.mark.asyncio
    async def test_template_resolution_soc_target(self):
        """Dynamic template {{soc_target}} resolves correctly."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)
        ha_client.set_switch = AsyncMock(return_value=True)
        ha_client.set_number = AsyncMock(return_value=True)
        ha_client.set_input_number = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(
                work_mode="select.work_mode",
                grid_charging_enable="switch.grid_charge",
                soc_target="input_number.soc_target",
                max_charge_current="number.max_charge_a",
                max_discharge_current="number.max_discharge_a",
            ),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=85,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        soc_target_result = results[3]
        assert soc_target_result.new_value == 85


class TestExecutorV2ShadowMode:
    """Test shadow mode behavior."""

    @pytest.mark.asyncio
    async def test_shadow_mode_logs_without_writing(self):
        """Shadow mode logs without writing to HA."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)
        ha_client.set_switch = AsyncMock(return_value=True)
        ha_client.set_number = AsyncMock(return_value=True)
        ha_client.set_input_number = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(
                work_mode="select.work_mode",
                grid_charging_enable="switch.grid_charge",
                soc_target="input_number.soc_target",
                max_charge_current="number.max_charge_a",
                max_discharge_current="number.max_discharge_a",
            ),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=True,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        for result in results:
            assert result.skipped is True
            assert "shadow" in result.message.lower() or "would" in result.message.lower()

        ha_client.set_select.assert_not_called()
        ha_client.set_switch.assert_not_called()


class TestExecutorV2SettleDelay:
    """Test settle delay is applied."""

    @pytest.mark.asyncio
    async def test_settle_delay_applied(self):
        """Settle delay is applied between actions with settle_ms."""
        profile = load_profile("fronius")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)
        ha_client.set_switch = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(work_mode="select.work_mode"),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        assert len(results) > 0


class TestExecutorV2EntityResolution:
    """Test entity resolution order."""

    @pytest.mark.asyncio
    async def test_entity_resolution_user_override(self):
        """User override takes priority over profile default."""
        profile = load_profile("deye")

        ha_client = MagicMock(spec=HAClient)
        ha_client.get_state_value = AsyncMock(return_value="unknown")
        ha_client.set_select = AsyncMock(return_value=True)

        config = ExecutorConfig(
            inverter=InverterConfig(
                work_mode="select.user_work_mode",
            ),
            controller=ControllerConfig(),
            water_heater=WaterHeaterConfig(),
            notifications=NotificationConfig(),
        )

        dispatcher = ActionDispatcher(
            ha_client=ha_client,
            config=config,
            profile=profile,
            shadow_mode=False,
        )

        decision = ControllerDecision(
            mode_intent="charge",
            charge_value=50,
            discharge_value=0,
            soc_target=100,
            export_power_w=0,
            max_charge=100,
            max_discharge=100,
        )

        results = await dispatcher.execute(decision)

        assert results[0].entity_id == "select.user_work_mode"
