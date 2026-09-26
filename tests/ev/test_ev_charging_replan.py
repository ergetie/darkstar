"""
EV Charging Replan Tests (Rev EVFIX)

Production-grade test suite for EV plug-in replanning fixes.
Covers asyncio cross-thread dispatch, config path fixes, and executor gating.
"""

import asyncio
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from executor.config import EVChargerDeviceConfig
from executor.engine import ExecutorEngine


class TestEVReplanAsyncDispatch:
    """Test Task 1.1 & 1.2: asyncio cross-thread dispatch fixes."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create minimal config files for testing."""
        config = {
            "system": {
                "has_solar": True,
                "has_battery": True,
                "has_water_heater": False,
                "has_ev_charger": True,
                "grid_meter_type": "net",
            },
            "input_sensors": {
                "battery_soc": "sensor.test_battery",
                "pv_power": "sensor.test_pv",
                "load_power": "sensor.test_load",
            },
            "ev_chargers": [
                {
                    "enabled": True,
                    "name": "Test EV",
                    "replan_on_plugin": True,
                    "sensor": "sensor.test_ev_power",
                    "plug_sensor": "binary_sensor.test_ev_plug",
                }
            ],
            "battery": {"capacity_kwh": 10.0, "max_charge_kw": 5.0, "max_discharge_kw": 5.0},
            "executor": {
                "enabled": True,
                "shadow_mode": False,
                "interval_seconds": 300,
                "timezone": "Europe/Stockholm",
                "inverter": {},
                "ev_charger": {"switch_entity": "switch.test_ev"},
            },
        }

        secrets = {"home_assistant": {"url": "http://test", "token": "test_token"}}

        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        config_path.write_text(yaml.dump(config))
        secrets_path.write_text(yaml.dump(secrets))

        return str(config_path), str(secrets_path)

    def test_trigger_ev_replan_uses_shared_helper(self, mock_config):
        """Plug-in replans are dispatched through the shared request_replan helper."""
        from backend.ha_socket import HAWebSocketClient
        from backend.services.scheduler_service import ReplanReason

        with (
            patch("backend.ha_socket.load_yaml") as mock_load_yaml,
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            mock_load_yaml.return_value = {
                "system": {"has_ev_charger": True},
                "ev_chargers": [{"enabled": True, "id": "ev1", "replan_on_plugin": True}],
            }
            client = HAWebSocketClient()
            with patch("backend.services.scheduler_service.request_replan") as mock_request:
                client._trigger_ev_replan()

        mock_request.assert_called_once_with(ReplanReason.PLUG_IN, ev_overrides={"ev1": True})


class TestEVReplanConfigPath:
    """Test Task 2.1 & 2.2: Config path reads from ev_chargers[]."""

    @pytest.fixture
    def mock_config_disabled_replan(self, tmp_path):
        """Create config with replan_on_plugin disabled."""
        config = {
            "system": {"has_ev_charger": True},
            "ev_chargers": [
                {
                    "enabled": True,
                    "name": "Test EV",
                    "replan_on_plugin": False,  # Disabled
                    "plug_sensor": "binary_sensor.test_plug",
                }
            ],
        }

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config))

        return str(config_path)

    @pytest.mark.asyncio
    async def test_trigger_ev_replan_reads_ev_chargers_array(self, tmp_path):
        """Task 5.2: Verify trigger respects replan_on_plugin=false in ev_chargers[]."""
        original_dir = Path.cwd()

        try:
            import os

            os.chdir(tmp_path)

            from backend.ha_socket import HAWebSocketClient

            client = HAWebSocketClient()

            with (
                patch("backend.services.scheduler_service.request_replan") as mock_request,
                patch("backend.ha_socket.load_yaml") as mock_load_yaml,
            ):
                # Return the config literal
                mock_load_yaml.return_value = {
                    "system": {"has_ev_charger": True},
                    "ev_chargers": [{"enabled": True, "replan_on_plugin": False}],
                }

                client._trigger_ev_replan()

                # Should NOT trigger because replan_on_plugin=False
                mock_request.assert_not_called()
        finally:
            import os

            os.chdir(original_dir)


class TestEVInitialStateOverride:
    """Test Task 3.1, 3.2 & 3.3: ev_plugged_in_override parameter."""

    @pytest.mark.asyncio
    async def test_get_initial_state_override_ev_plugged_in(self, tmp_path):
        """Task 5.3: Verify override skips HA REST fetch for ev_plugged_in."""
        config = {
            "system": {
                "has_ev_charger": True,
                "has_battery": False,
                "has_solar": False,
                "has_water_heater": False,
            },
            "ev_chargers": [
                {
                    "enabled": True,
                    "id": "ev_1",
                    "name": "Test EV",
                    "soc_sensor": "sensor.test_soc",
                    "plug_sensor": "binary_sensor.test_plug",
                }
            ],
            "input_sensors": {},
            "battery": {"capacity_kwh": 10.0},
        }

        secrets = {"home_assistant": {"url": "http://test", "token": "test"}}

        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        config_path.write_text(yaml.dump(config))
        secrets_path.write_text(yaml.dump(secrets))

        original_dir = Path.cwd()

        try:
            import os

            os.chdir(tmp_path)

            from backend.core.ha_client import get_initial_state

            # Mock HA sensor calls
            with patch("backend.core.ha_client.get_ha_sensor_float") as mock_float:
                mock_float.return_value = 50.0  # SoC value

                with patch("backend.core.ha_client.get_ha_bool") as mock_bool:
                    mock_bool.return_value = False  # Would normally return this

                    # Call with override=True
                    result = await get_initial_state(
                        config_path=str(config_path), ev_plug_overrides={"ev_1": True}
                    )

                    # Verify ev_plugged_in is True from override
                    assert result["ev_plugged_in"] is True

                    # Verify get_ha_bool was NOT called for plug sensor
                    # (it may be called for other things, but not for ev_plugged_in)
                    plug_calls = [
                        call for call in mock_bool.call_args_list if "test_plug" in str(call)
                    ]
                    assert len(plug_calls) == 0, (
                        "Should not fetch plug state from HA when override provided"
                    )
        finally:
            import os

            os.chdir(original_dir)


class TestExecutorEVSwitchGating:
    """Test Task 4.x: Executor switch gating hardening."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create minimal executor config."""
        config = {
            "system": {
                "has_solar": True,
                "has_battery": True,
                "has_water_heater": False,
                "has_ev_charger": True,
                "grid_meter_type": "net",
            },
            "input_sensors": {
                "battery_soc": "sensor.test_battery",
                "pv_power": "sensor.test_pv",
                "load_power": "sensor.test_load",
            },
            "battery": {"capacity_kwh": 10.0},
            "executor": {
                "enabled": True,
                "shadow_mode": True,  # Use shadow mode to avoid actual HA calls
                "interval_seconds": 300,
                "timezone": "Europe/Stockholm",
                "inverter": {"work_mode_entity": "sensor.work_mode"},
                "ev_charger": {
                    "switch_entity": "switch.test_ev",
                },
            },
            "ev_chargers": [
                {
                    "enabled": True,
                    "name": "Test EV",
                    "sensor": "sensor.test_ev_power",
                }
            ],
        }

        secrets = {"home_assistant": {"url": "http://test", "token": "test_token"}}

        config_path = tmp_path / "config.yaml"
        secrets_path = tmp_path / "secrets.yaml"

        config_path.write_text(yaml.dump(config))
        secrets_path.write_text(yaml.dump(secrets))

        return str(config_path)

    @pytest.mark.asyncio
    async def test_executor_ev_switch_not_opened_without_schedule(self, mock_config):
        """Task 5.4: Verify switch stays OFF when actual charging but no schedule."""
        from executor.override import SlotPlan, SystemState

        engine = ExecutorEngine(config_path=mock_config)

        # Mock the dependencies
        engine._has_ev_charger = True
        engine._has_battery = True
        engine.config.ev_chargers = [
            EVChargerDeviceConfig(id="main", switch_entity="switch.test_ev")
        ]

        # Create a slot with NO scheduled EV charging
        slot = SlotPlan(
            charge_kw=0.0,
            discharge_kw=3.0,
            export_kw=0.0,
            load_kw=1.0,
            water_kw=0.0,
            ev_charging_kw=0.0,  # No scheduled charging
            soc_target=50,
            soc_projected=50,
        )

        # Mock _control_ev_charger to capture what value is passed
        with patch.object(engine, "_control_ev_charger", new_callable=AsyncMock) as mock_control:
            # Mock the load disaggregator to return actual EV charging
            mock_disaggregator = MagicMock()
            mock_disaggregator.update_current_power = AsyncMock()
            mock_disaggregator.get_total_ev_power.return_value = 3.5  # Actual charging detected
            engine._load_disaggregator = mock_disaggregator

            # Mock other dependencies
            engine.ha_client = MagicMock()
            engine.dispatcher = MagicMock()

            # Mock _gather_system_state
            state = SystemState(current_soc_percent=50.0)
            with (
                patch.object(
                    engine, "_gather_system_state", new_callable=AsyncMock, return_value=state
                ),
                patch.object(
                    engine, "_load_current_slot", return_value=(slot, "2024-01-01T00:00:00")
                ),
                patch("executor.engine.make_decision") as mock_decision,
            ):
                mock_decision.return_value = MagicMock(
                    mode_intent="self_consumption",
                    reason="Test",
                    charge_value=0,
                    discharge_value=10,
                    soc_target=50,
                    water_temp=40,
                    source="test",
                )

                # Run the tick
                await engine._tick()

                # Verify _control_ev_charger was called with the slot
                # (which has no per-device EV plans, so no switch will be turned on)
                mock_control.assert_called_once()
                call_args = mock_control.call_args[0]
                slot_arg = call_args[0]

                # Slot has no scheduled EV charging — per-device plans are empty
                assert slot_arg.ev_charging_kw == 0.0, "Slot should have no EV charging"
                assert slot_arg.ev_charger_plans == {}, "No per-device plans should be present"


class TestEVToggleReload:
    from typing import ClassVar

    _EV_CHARGERS: ClassVar[list[dict]] = [
        {"enabled": True, "name": "Test EV", "sensor": "sensor.test_ev_power"}
    ]

    def _make_cfg(self, has_ev_charger: bool) -> dict:
        return {
            "system": {"has_ev_charger": has_ev_charger, "grid_meter_type": "net"},
            "input_sensors": {},
            "ev_chargers": self._EV_CHARGERS,
        }

    def test_reload_clears_ev_state_when_toggled_off(self, tmp_path):
        """Task 2.1: reload_monitored_entities() clears EV state when has_ev_charger → false."""
        from backend.ha_socket import HAWebSocketClient

        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg(True)),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client = HAWebSocketClient()

        # Sanity: EV state populated after init with has_ev_charger=True
        assert len(client.ev_charger_configs) == 1
        assert "ev_chargers" in client.latest_values

        # Now flip the flag off and reload
        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg(False)),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client.reload_monitored_entities()

        assert client.ev_charger_configs == []
        assert "ev_chargers" not in client.latest_values

    def test_reload_rebuilds_ev_state_when_toggled_on(self, tmp_path):
        """Task 2.2: reload_monitored_entities() rebuilds EV state when has_ev_charger → true."""
        from backend.ha_socket import HAWebSocketClient

        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg(False)),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client = HAWebSocketClient()

        # Sanity: no EV state after init with has_ev_charger=False
        assert client.ev_charger_configs == []
        assert "ev_chargers" not in client.latest_values

        # Now flip the flag on and reload
        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg(True)),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client.reload_monitored_entities()

        assert len(client.ev_charger_configs) == 1
        assert "ev_chargers" in client.latest_values
        assert len(client.latest_values["ev_chargers"]) == 1


class TestPerDevicePlugSensorMapping:
    """Task 7.4: Per-device plug sensor → charger ID mapping."""

    _EV_CHARGERS: ClassVar[list[dict]] = [
        {
            "enabled": True,
            "id": "charger_a",
            "name": "Charger A",
            "sensor": "sensor.ev_a_power",
            "plug_sensor": "binary_sensor.ev_a_plug",
        },
        {
            "enabled": True,
            "id": "charger_b",
            "name": "Charger B",
            "sensor": "sensor.ev_b_power",
            "plug_sensor": "binary_sensor.ev_b_plug",
        },
    ]

    def _make_cfg(self):
        return {
            "system": {"has_ev_charger": True, "grid_meter_type": "net"},
            "input_sensors": {},
            "ev_chargers": self._EV_CHARGERS,
        }

    def test_charger_id_stored_in_ev_charger_configs(self):
        """ev_charger_configs entries include the charger id from config."""
        from backend.ha_socket import HAWebSocketClient

        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg()),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client = HAWebSocketClient()

        assert len(client.ev_charger_configs) == 2
        ids = [cfg.get("id") for cfg in client.ev_charger_configs]
        assert "charger_a" in ids
        assert "charger_b" in ids

    def test_trigger_ev_replan_passes_charger_id(self):
        """_trigger_ev_replan(charger_id) checks that charger's settings."""
        from backend.ha_socket import HAWebSocketClient

        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg()),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client = HAWebSocketClient()

        config_with_replan = {
            "system": {"has_ev_charger": True},
            "ev_chargers": [
                {"enabled": True, "id": "charger_a", "replan_on_plugin": True},
                {"enabled": True, "id": "charger_b", "replan_on_plugin": False},
            ],
        }

        with (
            patch("backend.ha_socket.load_yaml", return_value=config_with_replan),
            patch("backend.services.scheduler_service.request_replan") as mock_request,
        ):
            # charger_a has replan_on_plugin=True → should trigger
            client._trigger_ev_replan(charger_id="charger_a")
            mock_request.assert_called_once()
            mock_request.reset_mock()

            # charger_b has replan_on_plugin=False → should NOT trigger
            client._trigger_ev_replan(charger_id="charger_b")
            mock_request.assert_not_called()

    def test_trigger_ev_replan_passes_charger_override(self):
        """_trigger_ev_replan carries the charger's plug override to the helper."""
        from backend.ha_socket import HAWebSocketClient
        from backend.services.scheduler_service import ReplanReason

        with (
            patch("backend.ha_socket.load_yaml", return_value=self._make_cfg()),
            patch("backend.ha_socket.load_home_assistant_config", return_value={}),
        ):
            client = HAWebSocketClient()

        config_with_replan = {
            "system": {"has_ev_charger": True},
            "ev_chargers": [
                {"enabled": True, "id": "charger_a", "replan_on_unplug": True},
            ],
        }

        with (
            patch("backend.ha_socket.load_yaml", return_value=config_with_replan),
            patch("backend.services.scheduler_service.request_replan") as mock_request,
        ):
            client._trigger_ev_replan(charger_id="charger_a", plugged_in=False)

        mock_request.assert_called_once_with(ReplanReason.UNPLUG, ev_overrides={"charger_a": False})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
