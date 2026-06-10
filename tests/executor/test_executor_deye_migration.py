"""
Integration tests for Deye Profile Migration.

Verifies that the new profile-based logic produces correct results using
v2 ControllerDecision fields (mode_intent) instead of legacy v1 fields
(work_mode, grid_charging).
"""

import pytest

from executor.config import ControllerConfig, InverterConfig, WaterHeaterConfig
from executor.controller import make_decision
from executor.override import SlotPlan, SystemState
from executor.profiles import load_profile


class TestDeyeMigration:
    """Test suite for Deye profile migration to v2 mode_intent system."""

    @pytest.fixture
    def deye_profile(self):
        """Load the real Deye profile."""
        return load_profile("deye", profiles_dir="profiles")

    @pytest.fixture
    def configs(self):
        """Standard Deye-like configurations."""
        ctrl_cfg = ControllerConfig(
            min_charge_a=10.0,
            max_charge_a=185.0,
            round_step_a=5.0,
        )
        inv_cfg = InverterConfig(
            control_unit="A",
        )
        wh_cfg = WaterHeaterConfig()
        return ctrl_cfg, inv_cfg, wh_cfg

    def test_mode_translation_equivalence(self, deye_profile, configs):
        """Verify that mode translation matches expected v2 behavior."""
        ctrl_cfg, inv_cfg, _wh_cfg = configs

        # Test 1: Export case (battery discharge to grid)
        # Requires both export_kw > 0 AND discharge_kw > 0
        slot_export = SlotPlan(export_kw=5.0, discharge_kw=5.0, charge_kw=0)
        state = SystemState(current_soc_percent=50.0)

        decision = make_decision(
            slot_export, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=deye_profile
        )

        # v2: Check mode_intent instead of work_mode
        assert decision.mode_intent == "export"

        # Test 2: Idle case (no export, no charge, at SoC target)
        # v2: When there's no planned activity and SoC is at/above target, return idle
        slot_zero = SlotPlan(export_kw=0, charge_kw=0, soc_target=50)
        decision = make_decision(
            slot_zero, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=deye_profile
        )

        assert decision.mode_intent == "idle"

    def test_grid_charging_equivalence(self, deye_profile, configs):
        """Verify that grid charging logic uses mode_intent='charge'."""
        ctrl_cfg, inv_cfg, _wh_cfg = configs
        state = SystemState(current_soc_percent=20.0)

        # Grid charge case
        slot_charge = SlotPlan(export_kw=0, charge_kw=3.0)

        decision = make_decision(
            slot_charge, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=deye_profile
        )

        # v2: Grid charging is indicated by mode_intent='charge'
        assert decision.mode_intent == "charge"

    def test_behavioral_limits_equivalence(self, deye_profile, configs):
        """Verify that charge/discharge limit calculations match."""
        ctrl_cfg, inv_cfg, _wh_cfg = configs
        state = SystemState(current_soc_percent=20.0)
        slot_charge = SlotPlan(export_kw=0, charge_kw=1.0)  # ~20.8A at 48V

        # Profile decision
        decision = make_decision(
            slot_charge, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=deye_profile
        )

        # Expected: 1000W / 48V (nominal) = 20.83A -> rounded to 20A (step 5)
        assert decision.charge_value == 20.0
        assert decision.write_charge_current is True

    def test_fallback_behavior(self, configs):
        """Verify that system falls back to generic profile if profile is None."""
        ctrl_cfg, inv_cfg, _wh_cfg = configs
        state = SystemState(current_soc_percent=50.0)
        # Battery export requires both export_kw > 0 AND discharge_kw > 0
        slot = SlotPlan(export_kw=5.0, discharge_kw=5.0)

        # No profile provided
        decision = make_decision(
            slot, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=None
        )

        # v2: Check mode_intent
        assert decision.mode_intent == "export"
        assert decision.control_unit == "A"

    def test_idle_mode_at_target(self, deye_profile, configs):
        """Verify idle mode is selected when at SoC target with no activity."""
        ctrl_cfg, inv_cfg, _wh_cfg = configs
        state = SystemState(current_soc_percent=95.0)

        # Slot at target with no charge/export
        slot = SlotPlan(export_kw=0, charge_kw=0, soc_target=95)

        decision = make_decision(
            slot, state, config=ctrl_cfg, inverter_config=inv_cfg, profile=deye_profile
        )

        # At target with no export/charge should be idle to preserve battery
        assert decision.mode_intent == "idle"
