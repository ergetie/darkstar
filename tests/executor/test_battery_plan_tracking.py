"""battery-plan-tracking: grid-charge stop at target, hold margin, tick reasons."""

import pytest

from executor.config import ControllerConfig, InverterConfig
from executor.controller import (
    CHARGE_TARGET_REASON,
    HOLD_MARGIN_REASON,
    BatteryPlanState,
    Controller,
)
from executor.override import OverrideResult, OverrideType, SlotPlan, SystemState


@pytest.fixture
def controller():
    return Controller(ControllerConfig(), InverterConfig(), plan_state=BatteryPlanState())


def _soc(value: float) -> SystemState:
    return SystemState(current_soc_percent=value)


def grid_charge(target: int = 18) -> SlotPlan:
    return SlotPlan(charge_kw=3.0, grid_charge_kw=3.0, soc_target=target)


def hold(target: int = 50, **kw) -> SlotPlan:
    return SlotPlan(soc_target=target, **kw)


class TestStopGridChargeAtTarget:
    def test_below_target_charges(self, controller):
        assert controller.decide(grid_charge(), _soc(10)).mode_intent == "charge"

    def test_at_target_holds(self, controller):
        decision = controller.decide(grid_charge(), _soc(18))
        assert decision.mode_intent == "idle"
        assert decision.write_charge_current is False

    def test_above_target_at_block_start_holds(self, controller):
        assert controller.decide(grid_charge(), _soc(25)).mode_intent == "idle"

    def test_solar_only_unaffected(self, controller):
        slot = SlotPlan(charge_kw=3.0, grid_charge_kw=0.0, soc_target=18)
        assert controller.decide(slot, _soc(40)).mode_intent == "self_consumption"

    def test_override_unchanged(self, controller):
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.FORCE_CHARGE,
            reason="Top Up",
            actions={"soc_target": 90},
        )
        decision = controller.decide(grid_charge(18), _soc(40), override)
        assert decision.mode_intent == "charge"
        assert decision.source == "override"

    def test_small_dip_keeps_holding(self, controller):
        controller.decide(grid_charge(), _soc(18))
        assert controller.decide(grid_charge(), _soc(17)).mode_intent == "idle"

    def test_clear_drop_resumes(self, controller):
        controller.decide(grid_charge(), _soc(18))
        assert controller.decide(grid_charge(), _soc(15)).mode_intent == "charge"

    def test_latch_resets_at_block_change(self, controller):
        controller.decide(grid_charge(18), _soc(18))
        controller.decide(SlotPlan(soc_target=40), _soc(60))  # block ended
        assert controller.decide(grid_charge(18), _soc(17)).mode_intent == "charge"

    def test_latch_resets_on_new_target(self, controller):
        controller.decide(grid_charge(18), _soc(18))
        assert controller.decide(grid_charge(30), _soc(18)).mode_intent == "charge"

    def test_reason_recorded(self, controller):
        decision = controller.decide(grid_charge(), _soc(18))
        assert CHARGE_TARGET_REASON in decision.reason

    def test_reason_absent_while_charging(self, controller):
        assert CHARGE_TARGET_REASON not in controller.decide(grid_charge(), _soc(5)).reason

    def test_reported_scenario_stops_at_18(self, controller):
        modes = [
            controller.decide(grid_charge(18), _soc(s)).mode_intent for s in (3, 10, 17, 18, 19)
        ]
        assert modes == ["charge", "charge", "charge", "idle", "idle"]


class TestHoldMargin:
    def test_small_drop_stays_on_auto(self, controller):
        assert controller.decide(hold(), _soc(49)).mode_intent == "self_consumption"

    def test_margin_used_blocks(self, controller):
        decision = controller.decide(hold(), _soc(48))
        assert decision.mode_intent == "idle"
        assert HOLD_MARGIN_REASON in decision.reason

    def test_no_flip_on_one_point(self, controller):
        controller.decide(hold(), _soc(48))
        assert controller.decide(hold(), _soc(49)).mode_intent == "idle"

    def test_back_at_target_lifts(self, controller):
        controller.decide(hold(), _soc(48))
        assert controller.decide(hold(), _soc(50)).mode_intent == "self_consumption"

    def test_state_resets_at_block_change(self, controller):
        controller.decide(hold(50), _soc(48))
        controller.decide(SlotPlan(charge_kw=2.0, grid_charge_kw=0.0), _soc(49))
        assert controller.decide(hold(50), _soc(49)).mode_intent == "self_consumption"

    def test_reason_absent_on_auto(self, controller):
        assert HOLD_MARGIN_REASON not in controller.decide(hold(), _soc(49)).reason

    def test_ev_isolation_keeps_precedence(self, controller):
        slot = hold(50, ev_charging_kw=3.0)
        assert controller.decide(slot, _soc(50)).mode_intent == "idle"
        assert controller.decide(slot, _soc(60)).mode_intent == "idle"

    def test_ev_keep_on_keeps_precedence(self, controller):
        slot = hold(50, ev_keep_on={"car": True})
        assert controller.decide(slot, _soc(49)).mode_intent == "idle"

    def test_discharge_slot_keeps_floor_without_margin(self, controller):
        slot = SlotPlan(discharge_kw=2.0, soc_target=12)
        assert controller.decide(slot, _soc(12)).mode_intent == "idle"
        assert controller.decide(slot, _soc(13)).mode_intent == "self_consumption"

    def test_ev_isolated_slot_is_not_a_hold(self, controller):
        slot = SlotPlan(discharge_kw=0.0, soc_target=12, discharge_blocked_by_ev=True)
        assert controller.decide(slot, _soc(13)).mode_intent == "self_consumption"

    def test_pv_shortfall_at_most_one_block(self, controller):
        socs = [50, 49, 48, 49, 48, 49, 50, 49]
        modes = [controller.decide(hold(), _soc(s)).mode_intent for s in socs]
        assert modes == [
            "self_consumption",
            "self_consumption",
            "idle",
            "idle",
            "idle",
            "idle",
            "self_consumption",
            "self_consumption",
        ]
