from unittest.mock import AsyncMock, MagicMock

import pytest

from executor.actions import ActionDispatcher, HACallError
from executor.config import ExecutorConfig, EVChargerDeviceConfig


def _dispatcher(current: str, *, shadow_mode: bool = False) -> tuple[ActionDispatcher, MagicMock]:
    ha = MagicMock()
    ha.get_state_value = AsyncMock(return_value=current)
    ha.set_select_option = AsyncMock(return_value=True)
    ha.set_switch = AsyncMock(return_value=True)
    dispatcher = ActionDispatcher(ha, ExecutorConfig(), shadow_mode=shadow_mode)
    dispatcher._verify_action = AsyncMock(return_value=(current, True))
    return dispatcher, ha


@pytest.mark.asyncio
async def test_select_charge_mapping_writes_option_and_reports_it():
    dispatcher, ha = _dispatcher("Off")
    result = await dispatcher.set_ev_charger_switch(
        "select.ev_mode",
        True,
        enabled_value="On",
        disabled_value="Off",
    )

    ha.set_select_option.assert_awaited_once_with("select.ev_mode", "On")
    assert result.action_type == "ev_charge_start"
    assert result.new_value == "On"


@pytest.mark.asyncio
async def test_select_charge_stop_is_explicit_from_neutral_and_idempotent():
    dispatcher, ha = _dispatcher("Neutral")
    result = await dispatcher.set_ev_charger_switch(
        "select.ev_mode",
        False,
        enabled_value="On",
        disabled_value="Off",
    )
    ha.set_select_option.assert_awaited_once_with("select.ev_mode", "Off")
    assert result.new_value == "Off"

    dispatcher, ha = _dispatcher("Off")
    result = await dispatcher.set_ev_charger_switch(
        "input_select.ev_mode",
        False,
        enabled_value="On",
        disabled_value="Off",
    )
    ha.set_select_option.assert_not_called()
    assert result.skipped is True
    assert result.new_value == "Off"


@pytest.mark.asyncio
async def test_switch_control_keeps_services_and_string_result():
    dispatcher, ha = _dispatcher("off")
    result = await dispatcher.set_ev_charger_switch("switch.ev_mode", True)
    ha.set_switch.assert_awaited_once_with("switch.ev_mode", True)
    assert result.new_value == "on"


@pytest.mark.asyncio
async def test_select_shadow_mode_reports_mapped_target_without_writing():
    dispatcher, ha = _dispatcher("Neutral", shadow_mode=True)
    result = await dispatcher.set_ev_charger_switch(
        "select.ev_mode",
        False,
        enabled_value="On",
        disabled_value="Off",
    )
    ha.set_select_option.assert_not_called()
    assert result.skipped is True
    assert result.new_value == "Off"


@pytest.mark.asyncio
async def test_select_write_failure_is_reported():
    dispatcher, ha = _dispatcher("Neutral")
    ha.set_select_option.side_effect = HACallError("HA rejected option")
    result = await dispatcher.set_ev_charger_switch(
        "select.ev_mode",
        True,
        enabled_value="On",
        disabled_value="Off",
    )
    assert result.success is False
    assert result.new_value == "On"


@pytest.mark.asyncio
async def test_phase_mapping_is_used_for_write_and_verification():
    dispatcher, ha = _dispatcher("Auto")
    result = await dispatcher.set_ev_phase_mode("select.ev_phase", 3, "Force_3")
    ha.set_select_option.assert_awaited_once_with("select.ev_phase", "Force_3")
    dispatcher._verify_action.assert_awaited_once_with("select.ev_phase", "Force_3")
    assert result.new_value == "Force_3"


def test_ev_config_exposes_mapping_fields():
    charger = EVChargerDeviceConfig(
        id="goe",
        charge_enabled_value="On",
        charge_disabled_value="Off",
        phase_1_value="Force_1",
        phase_3_value="Force_3",
    )
    assert charger.charge_enabled_value == "On"
    assert charger.charge_disabled_value == "Off"
    assert charger.phase_1_value == "Force_1"
    assert charger.phase_3_value == "Force_3"
