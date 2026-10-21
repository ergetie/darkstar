"""battery-plan-tracking: grid-charge stop at target, hold margin, tick reasons."""

from pathlib import Path

import pytest

from executor.config import ControllerConfig, InverterConfig
from executor.controller import (
    CHARGE_TARGET_REASON,
    HOLD_MARGIN_REASON,
    BatteryPlanState,
    Controller,
)
from executor.override import OverrideResult, OverrideType, SlotPlan, SystemState
from executor.profiles import InverterProfile, load_profile

PROFILES_DIR = Path(__file__).resolve().parents[2] / "profiles"


@pytest.fixture
def controller():
    return Controller(ControllerConfig(), InverterConfig(), plan_state=BatteryPlanState())


def _min_soc_controller(
    min_soc: float = 12.0, profile: InverterProfile | None = None
) -> Controller:
    return Controller(
        ControllerConfig(min_soc_percent=min_soc),
        InverterConfig(),
        profile=profile,
        plan_state=BatteryPlanState(),
    )


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


class TestHoldFloorAtMinSoc:
    """min-soc-floor-tracking D1: the hold margin never crosses min_soc_percent."""

    def test_margin_never_crosses_minimum(self):
        controller = _min_soc_controller(12)
        decision = controller.decide(hold(13), _soc(12))
        assert decision.mode_intent == "idle"
        assert HOLD_MARGIN_REASON in decision.reason

    def test_target_above_minimum_still_auto(self):
        controller = _min_soc_controller(12)
        assert controller.decide(hold(13), _soc(13)).mode_intent == "self_consumption"

    def test_hold_at_minimum_blocks_immediately_and_stays(self):
        controller = _min_soc_controller(12)
        modes = [controller.decide(hold(12), _soc(12)).mode_intent for _ in range(5)]
        assert modes == ["idle"] * 5

    def test_hold_at_minimum_lifts_on_real_gain(self):
        controller = _min_soc_controller(12)
        controller.decide(hold(12), _soc(12))
        assert controller.decide(hold(12), _soc(13)).mode_intent == "self_consumption"

    def test_hold_below_minimum_is_idle_without_charge(self):
        controller = _min_soc_controller(12)
        decision = controller.decide(hold(11), _soc(11))
        assert decision.mode_intent == "idle"
        assert decision.write_charge_current is False
        assert controller.decide(hold(11), _soc(11)).mode_intent == "idle"

    def test_hold_below_minimum_lifts_only_at_minimum(self):
        controller = _min_soc_controller(12)
        controller.decide(hold(11), _soc(11))
        assert controller.decide(hold(11), _soc(12)).mode_intent == "self_consumption"


class TestFroniusHoldAtMinSoc:
    """Fronius writes no SoC target, so the hold floor alone stops self-consumption."""

    @pytest.fixture
    def fronius(self):
        profile = load_profile("fronius", PROFILES_DIR)
        assert profile.get_mode("idle").actions[0].value == "Block Discharging"
        return _min_soc_controller(12, profile)

    def test_hold_at_minimum_blocks_on_first_tick(self, fronius):
        decision = fronius.decide(hold(12), _soc(12))
        assert decision.mode_intent == "idle"

    def test_reported_sequence_no_charge_auto_cycle(self, fronius):
        # Charge block with target 12 reaches target and latches idle.
        assert fronius.decide(grid_charge(12), _soc(12)).mode_intent == "idle"
        # The following hold slot at the minimum stays idle (no self-consumption).
        hold_modes = [fronius.decide(hold(12), _soc(12)).mode_intent for _ in range(3)]
        assert hold_modes == ["idle"] * 3
        # The following charge slot at live 12 stays idle (no new top-up).
        assert fronius.decide(grid_charge(12), _soc(12)).mode_intent == "idle"


class TestDeyeAboveMinSocUnchanged:
    """Profiles that write a SoC target keep today's behaviour above the minimum."""

    @pytest.fixture
    def deye(self):
        return _min_soc_controller(12, load_profile("deye", PROFILES_DIR))

    def test_hold_margin_and_soc_target_unchanged(self, deye):
        first = deye.decide(hold(50), _soc(49))
        second = deye.decide(hold(50), _soc(48))
        assert first.mode_intent == "self_consumption"
        assert second.mode_intent == "idle"
        assert first.soc_target == 50
        assert second.soc_target == 50
        assert deye.profile is not None
        for mode in ("self_consumption", "idle"):
            soc_writes = [
                a.value for a in deye.profile.get_mode(mode).actions if a.entity == "soc_target"
            ]
            assert soc_writes == ["{{soc_target}}"]

    def test_grid_charge_latch_unchanged(self, deye):
        assert deye.decide(grid_charge(18), _soc(18)).mode_intent == "idle"
        assert deye.decide(grid_charge(18), _soc(17)).mode_intent == "idle"
        resumed = deye.decide(grid_charge(18), _soc(16))
        assert resumed.mode_intent == "charge"
        assert resumed.soc_target == 18
