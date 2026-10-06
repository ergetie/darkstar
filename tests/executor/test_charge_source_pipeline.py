"""Charging-source contract from solver output to real inverter profile actions."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from executor.actions import ActionDispatcher, HAClient
from executor.config import ExecutorConfig
from executor.controller import Controller
from executor.engine import ExecutorEngine
from executor.override import SystemState
from executor.profiles import load_profile
from planner.output.formatter import dataframe_to_json_response
from planner.solver.adapter import kepler_result_to_dataframe
from planner.solver.types import KeplerResult, KeplerResultSlot


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_name", ["fronius", "deye"])
@pytest.mark.parametrize(
    "grid_import_kwh,grid_export_kwh,expected_mode",
    [
        pytest.param(0.0, 0.0, "self_consumption", id="all-solar-surplus-absorbed"),
        pytest.param(0.0, 0.25, "self_consumption", id="solar-with-export"),
        pytest.param(0.75, 0.0, "charge", id="grid-only"),
        pytest.param(0.25, 0.0, "charge", id="mixed-solar-grid"),
    ],
)
async def test_solver_charging_source_reaches_profile_actions(
    profile_name, grid_import_kwh, grid_export_kwh, expected_mode
):
    """Formatting and EV-independent dispatch must not invent grid-charge intent."""
    start = datetime(2030, 1, 1, 12, tzinfo=UTC)
    result = KeplerResult(
        slots=[
            KeplerResultSlot(
                start_time=start,
                end_time=start + timedelta(minutes=15),
                charge_kwh=0.75,
                discharge_kwh=0.0,
                grid_import_kwh=grid_import_kwh,
                grid_export_kwh=grid_export_kwh,
                soc_kwh=10.75,
                cost_sek=0.0,
            )
        ],
        total_cost_sek=0.0,
        is_optimal=True,
        status_msg="Optimal",
    )
    frame = kepler_result_to_dataframe(result, capacity_kwh=20.0, initial_soc_kwh=10.0)
    formatted = dataframe_to_json_response(frame, now_override=start)
    # Exercise the actual JSON boundary, including preservation of numeric zero.
    schedule_slot = json.loads(json.dumps(formatted))[0]

    profile = load_profile(profile_name)
    config = ExecutorConfig()
    config.inverter.custom_entities = {
        key: f"{definition.domain}.test_{key}" for key, definition in profile.entities.items()
    }
    # Parsing itself needs only the real config, not live HA or a history database.
    engine = ExecutorEngine.__new__(ExecutorEngine)
    engine.config = config
    slot = engine._parse_slot_plan(schedule_slot)

    assert slot.charge_kw == pytest.approx(3.0)
    assert slot.grid_charge_kw == pytest.approx(grid_import_kwh * 4)
    decision = Controller(config.controller, config.inverter, profile=profile).decide(
        slot, SystemState(current_soc_percent=50.0)
    )
    assert decision.mode_intent == expected_mode

    # Only HA I/O and timing are mocked; controller, profile YAML, action
    # resolution, writes, and write verification all use production code.
    states = {}

    async def write(entity_id, value):
        states[entity_id] = ("on" if value else "off") if isinstance(value, bool) else str(value)
        return True

    ha = MagicMock(spec=HAClient)
    ha.get_state_value = AsyncMock(side_effect=lambda entity_id: states.get(entity_id))
    ha.set_select_option = AsyncMock(side_effect=write)
    ha.set_number = AsyncMock(side_effect=write)
    ha.set_switch = AsyncMock(side_effect=write)
    dispatcher = ActionDispatcher(ha, config, profile=profile)
    with patch("executor.actions.asyncio.sleep", new_callable=AsyncMock):
        actions = await dispatcher.execute(decision)

    assert actions
    assert all(action.success and action.verification_success is True for action in actions)
    assert all(not action.skipped for action in actions)

    mode_entity = config.inverter.custom_entities["work_mode"]
    if profile_name == "fronius":
        expected_work_mode = "Charge from Grid" if expected_mode == "charge" else "Auto"
        ha.set_select_option.assert_awaited_once_with(mode_entity, expected_work_mode)
        grid_power_entity = config.inverter.custom_entities["grid_charge_power"]
        if expected_mode == "self_consumption":
            ha.set_number.assert_not_awaited()
            assert grid_power_entity not in states
        else:
            assert any(call.args[0] == grid_power_entity for call in ha.set_number.await_args_list)
    else:
        ha.set_select_option.assert_awaited_once_with(mode_entity, "Zero Export To CT")
        grid_switch = config.inverter.custom_entities["grid_charging_enable"]
        ha.set_switch.assert_awaited_once_with(grid_switch, expected_mode == "charge")
