"""battery-plan-tracking: grid-charge stop at target, hold slots, tick reasons."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from executor.config import ControllerConfig, InverterConfig
from executor.controller import (
    CHARGE_TARGET_REASON,
    EV_ISOLATION_REASON,
    HOLD_REASON,
    MIN_SOC_GUARD_REASON,
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


class TestHoldBlocksDischarge:
    """fix-hold-slot-discharge-ratchet: a hold slot is idle at every SoC."""

    @pytest.mark.parametrize("soc", [60, 50, 49, 40])
    def test_idle_at_any_soc(self, controller, soc):
        decision = controller.decide(hold(50), _soc(soc))
        assert decision.mode_intent == "idle"
        assert HOLD_REASON in decision.reason

    def test_stable_across_alternating_soc(self, controller):
        modes = [controller.decide(hold(50), _soc(s)).mode_intent for s in (49, 50) * 4]
        assert modes == ["idle"] * 8

    def test_hold_leaves_no_plan_state(self, controller):
        controller.decide(grid_charge(50), _soc(50))
        assert controller.plan_state.latched is True
        controller.decide(hold(50), _soc(49))
        assert controller.plan_state.kind is None
        assert controller.plan_state.target is None
        assert controller.plan_state.latched is False

    def test_hold_does_not_cap_charge(self, controller):
        decision = controller.decide(hold(50), _soc(49))
        assert decision.mode_intent == "idle"
        assert decision.write_charge_current is False

    def test_ev_isolation_keeps_precedence(self, controller):
        for slot in (hold(50, ev_charging_kw=3.0), hold(50, ev_keep_on={"car": True})):
            for soc in (49, 50, 60):
                decision = controller.decide(slot, _soc(soc))
                assert decision.mode_intent == "idle"
                assert EV_ISOLATION_REASON in decision.reason
                assert HOLD_REASON not in decision.reason

    def test_discharge_slot_keeps_floor(self, controller):
        slot = SlotPlan(discharge_kw=2.0, soc_target=12)
        assert controller.decide(slot, _soc(12)).mode_intent == "idle"
        assert controller.decide(slot, _soc(13)).mode_intent == "self_consumption"

    def test_ev_isolated_slot_has_no_hold_reason(self, controller):
        slot = SlotPlan(discharge_kw=0.0, soc_target=12, discharge_blocked_by_ev=True)
        decision = controller.decide(slot, _soc(13))
        assert decision.mode_intent == "idle"
        assert HOLD_REASON not in decision.reason

    @pytest.mark.parametrize("offset", [0, 1, 2])
    def test_replan_ratchet_regression(self, controller, offset):
        # Each replan re-seeds the hold target from the live SoC (96, 94, 92, 90).
        for target in (96, 94, 92, 90):
            decision = controller.decide(hold(target), _soc(target + offset))
            assert decision.mode_intent == "idle"
            assert HOLD_REASON in decision.reason

    def test_replan_ratchet_mode_never_flips(self, controller):
        modes = []
        for target in (96, 94, 92, 90):
            for soc in (target + 2, target + 1, target):
                modes.append(controller.decide(hold(target), _soc(soc)).mode_intent)
        assert set(modes) == {"idle"}

    def test_hold_resets_charge_latch(self, controller):
        assert controller.decide(grid_charge(50), _soc(50)).mode_intent == "idle"
        assert controller.plan_state.latched is True
        controller.decide(hold(50), _soc(50))
        assert controller.decide(grid_charge(50), _soc(48)).mode_intent == "charge"


class TestHoldAtMinSoc:
    """A hold at or near battery.min_soc_percent idles and never grid charges."""

    @pytest.mark.parametrize(("target", "soc"), [(12, 11), (12, 12), (12, 13), (12, 14), (11, 11)])
    def test_idle_without_charge(self, target, soc):
        controller = _min_soc_controller(12)
        decision = controller.decide(hold(target), _soc(soc))
        assert decision.mode_intent == "idle"
        assert decision.write_charge_current is False

    def test_guard_persists_through_hold_and_releases_at_margin(self):
        controller = _min_soc_controller(12)
        controller.decide(hold(11), _soc(11))
        assert controller.plan_state.min_soc_guard is True
        for soc in (12, 13):
            controller.decide(hold(11), _soc(soc))
            assert controller.plan_state.min_soc_guard is True
        follow = SlotPlan(charge_kw=0.2, grid_charge_kw=0.0, soc_target=12)
        decision = controller.decide(follow, _soc(13))
        assert decision.mode_intent == "idle"
        assert MIN_SOC_GUARD_REASON in decision.reason
        assert controller.decide(follow, _soc(14)).mode_intent == "self_consumption"
        assert controller.plan_state.min_soc_guard is False


class TestFroniusHoldAtMinSoc:
    @pytest.fixture
    def fronius(self):
        profile = load_profile("fronius", PROFILES_DIR)
        assert profile.get_mode("idle").actions[0].value == "Block Discharging"
        return _min_soc_controller(12, profile)

    def test_hold_at_minimum_blocks_on_first_tick(self, fronius):
        assert fronius.decide(hold(12), _soc(12)).mode_intent == "idle"

    def test_reported_sequence_no_charge_auto_cycle(self, fronius):
        assert fronius.decide(grid_charge(12), _soc(12)).mode_intent == "idle"
        hold_modes = [fronius.decide(hold(12), _soc(12)).mode_intent for _ in range(3)]
        assert hold_modes == ["idle"] * 3
        assert fronius.decide(grid_charge(12), _soc(12)).mode_intent == "idle"


class TestDeyeHold:
    @pytest.fixture
    def deye(self):
        return _min_soc_controller(12, load_profile("deye", PROFILES_DIR))

    def test_hold_idles_and_keeps_soc_target(self, deye):
        for soc in (49, 48):
            decision = deye.decide(hold(50), _soc(soc))
            assert decision.mode_intent == "idle"
            assert decision.soc_target == 50
        assert deye.profile is not None
        soc_writes = [
            a.value for a in deye.profile.get_mode("idle").actions if a.entity == "soc_target"
        ]
        assert soc_writes == ["{{soc_target}}"]

    def test_grid_charge_latch_unchanged(self, deye):
        assert deye.decide(grid_charge(18), _soc(18)).mode_intent == "idle"
        assert deye.decide(grid_charge(18), _soc(17)).mode_intent == "idle"
        resumed = deye.decide(grid_charge(18), _soc(16))
        assert resumed.mode_intent == "charge"
        assert resumed.soc_target == 18


@pytest.mark.parametrize("name", ["fronius", "deye", "sungrow", "generic", "schema"])
def test_idle_writes_no_zero_charge_limit(name):
    """Idle in a hold slot must leave PV charging possible on every profile.

    Raw YAML is read because the schema template does not pass profile validation.
    """
    data = yaml.safe_load((PROFILES_DIR / f"{name}.yaml").read_text())
    for action in data["modes"]["idle"]["actions"]:
        if action["entity"] in ("max_charge_current", "max_charge_power"):
            assert str(action["value"]).strip().lower() not in {"0", "0.0", "false", "off"}


def pv_charge() -> SlotPlan:
    return SlotPlan(charge_kw=0.2, grid_charge_kw=0.0, soc_target=12)


def battery_export() -> SlotPlan:
    return SlotPlan(export_kw=2.0, discharge_kw=2.0, soc_target=12)


def _unavailable() -> SystemState:
    return SystemState(current_soc_percent=50.0, soc_available=False)


class TestMinSocDischargeGuard:
    """executor-min-soc-discharge-guard: block discharge at or below min_soc_percent."""

    def test_pv_charge_slot_at_minimum_is_idle(self):
        controller = _min_soc_controller(12)
        decision = controller.decide(pv_charge(), _soc(12))
        assert decision.mode_intent == "idle"
        assert MIN_SOC_GUARD_REASON in decision.reason

    def test_pv_charge_slot_above_minimum_unchanged(self):
        controller = _min_soc_controller(12)
        decision = controller.decide(pv_charge(), _soc(13))
        assert decision.mode_intent == "self_consumption"
        assert MIN_SOC_GUARD_REASON not in decision.reason

    def test_export_at_minimum_is_idle(self):
        controller = _min_soc_controller(12)
        decision = controller.decide(battery_export(), _soc(11))
        assert decision.mode_intent == "idle"
        assert MIN_SOC_GUARD_REASON in decision.reason

    def test_release_needs_margin(self):
        controller = _min_soc_controller(12)
        assert controller.decide(pv_charge(), _soc(12)).mode_intent == "idle"
        assert controller.decide(pv_charge(), _soc(13)).mode_intent == "idle"
        assert controller.plan_state.min_soc_guard is True
        assert controller.decide(pv_charge(), _soc(14)).mode_intent == "self_consumption"
        assert controller.plan_state.min_soc_guard is False

    def test_latch_survives_slot_change_and_replan(self):
        controller = _min_soc_controller(12)
        controller.decide(pv_charge(), _soc(12))
        # Different block kinds/targets (slot change, replan) do not reset it.
        controller.decide(grid_charge(30), _soc(13))
        controller.decide(hold(40), _soc(13))
        decision = controller.decide(SlotPlan(discharge_kw=2.0, soc_target=10), _soc(13))
        assert decision.mode_intent == "idle"
        assert MIN_SOC_GUARD_REASON in decision.reason

    def test_idle_slot_updates_latch(self):
        controller = _min_soc_controller(12)
        controller.decide(SlotPlan(discharge_kw=2.0, soc_target=12), _soc(12))
        assert controller.plan_state.min_soc_guard is True
        controller.decide(SlotPlan(discharge_kw=2.0, soc_target=12), _soc(14))
        assert controller.plan_state.min_soc_guard is False

    def test_unavailable_soc_keeps_engaged(self):
        controller = _min_soc_controller(12)
        controller.decide(pv_charge(), _soc(12))
        assert controller.decide(pv_charge(), _unavailable()).mode_intent == "idle"
        assert controller.plan_state.min_soc_guard is True

    def test_unavailable_soc_keeps_released(self):
        controller = _min_soc_controller(60)
        # Placeholder 50.0 is below min 60 but must not engage the latch.
        assert controller.decide(pv_charge(), _unavailable()).mode_intent == "self_consumption"
        assert controller.plan_state.min_soc_guard is False

    def test_charge_slot_untouched(self):
        controller = _min_soc_controller(12)
        controller.decide(pv_charge(), _soc(11))
        decision = controller.decide(grid_charge(18), _soc(11))
        assert decision.mode_intent == "charge"
        assert MIN_SOC_GUARD_REASON not in decision.reason

    def test_status_copy_does_not_mutate_engine_latch(self):
        engine_state = BatteryPlanState()
        controller = Controller(
            ControllerConfig(min_soc_percent=12.0),
            InverterConfig(),
            plan_state=replace(engine_state),
        )
        controller.decide(pv_charge(), _soc(12))
        assert controller.plan_state.min_soc_guard is True
        assert engine_state.min_soc_guard is False

    def test_deye_soc_target_unchanged(self):
        deye = _min_soc_controller(12, load_profile("deye", PROFILES_DIR))
        decision = deye.decide(pv_charge(), _soc(12))
        assert decision.mode_intent == "idle"
        assert decision.soc_target == 12
        assert deye.profile is not None
        soc_writes = [
            a.value for a in deye.profile.get_mode("idle").actions if a.entity == "soc_target"
        ]
        assert soc_writes == ["{{soc_target}}"]
