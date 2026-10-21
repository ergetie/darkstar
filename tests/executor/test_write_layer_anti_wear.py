"""load-balancer-coordinated-ramping D10: write-layer deadband, urgent bypass
and last-write tracking (anti-wear)."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from executor.actions import ActionDispatcher, HAClient
from executor.config import ExecutorConfig, LoadBalancingConfig
from executor.controller import ControllerDecision
from executor.profiles import load_profile


def make_dispatcher(*, enabled: bool = True, previous: str = "100") -> ActionDispatcher:
    ha = MagicMock(spec=HAClient)
    ha.get_state_value = AsyncMock(return_value=previous)
    ha.set_number = AsyncMock(return_value=True)
    ha.set_select_option = AsyncMock(return_value=True)
    ha.set_switch = AsyncMock(return_value=True)
    config = ExecutorConfig(
        load_balancing=LoadBalancingConfig(
            enabled=enabled, main_fuse_a=20, write_deadband_percent=2.0
        )
    )
    return ActionDispatcher(ha, config, shadow_mode=False, profile=load_profile("deye"))


def charge_action(dispatcher: ActionDispatcher):
    return next(
        a for a in dispatcher.profile.modes["charge"].actions if a.entity == "max_charge_current"
    )


class TestDeadband:
    def test_change_below_percent_is_not_written(self):
        d = make_dispatcher()
        # 2 % of 6000 W = 120 W, larger than the 100 W step.
        assert d._below_write_deadband("6000", 6100.0, 100.0, urgent=False)
        assert not d._below_write_deadband("6000", 6130.0, 100.0, urgent=False)

    def test_never_smaller_than_one_profile_step(self):
        d = make_dispatcher()
        # 2 % of 100 A = 2 A, but one step is 5 A.
        assert d._below_write_deadband("100", 103.0, 5.0, urgent=False)
        assert not d._below_write_deadband("100", 105.0, 5.0, urgent=False)

    def test_urgent_reduction_bypasses_deadband(self):
        d = make_dispatcher()
        assert not d._below_write_deadband("6000", 5950.0, 100.0, urgent=True)

    def test_start_and_stop_are_always_written(self):
        d = make_dispatcher()
        assert not d._below_write_deadband("0", 1.0, 5.0, urgent=False)
        assert not d._below_write_deadband("5", 0.0, 5.0, urgent=False)

    def test_disabled_balancer_means_no_deadband(self):
        d = make_dispatcher(enabled=False)
        assert not d._below_write_deadband("6000", 6001.0, 100.0, urgent=False)


class TestChargeValueWrite:
    @pytest.mark.asyncio
    async def test_small_plan_fluctuation_is_not_written(self):
        d = make_dispatcher(previous="100")
        decision = ControllerDecision(mode_intent="charge", charge_value=103.0)
        result = await d._execute_action(charge_action(d), decision, "charge")
        assert result.skipped
        assert "deadband" in result.message
        d.ha.set_number.assert_not_called()

    @pytest.mark.asyncio
    async def test_step_sized_change_is_written_and_tracked(self):
        d = make_dispatcher(previous="100")
        decision = ControllerDecision(mode_intent="charge", charge_value=105.0)
        before = time.monotonic()
        result = await d._execute_action(charge_action(d), decision, "charge")
        assert result.success and not result.skipped
        d.ha.set_number.assert_called_once()
        last = d.last_write_at(result.entity_id)
        assert last is not None and last >= before

    @pytest.mark.asyncio
    async def test_overload_cut_is_written_immediately(self):
        d = make_dispatcher(previous="100")
        decision = ControllerDecision(
            mode_intent="charge", charge_value=98.0, urgent_reduction=True
        )
        result = await d._execute_action(charge_action(d), decision, "charge")
        assert not result.skipped
        d.ha.set_number.assert_called_once()


class TestEvCurrentWrite:
    @pytest.mark.asyncio
    async def test_current_change_is_written_and_tracked(self):
        d = make_dispatcher(previous="10")
        result = await d.set_ev_charger_current("number.goe_current", 11)
        assert result.success and not result.skipped
        assert d.last_write_at("number.goe_current") is not None

    @pytest.mark.asyncio
    async def test_urgent_reduction_is_written(self):
        d = make_dispatcher(previous="10")
        result = await d.set_ev_charger_current("number.goe_current", 7, urgent=True)
        assert not result.skipped
        d.ha.set_number.assert_called_once_with("number.goe_current", 7.0)
