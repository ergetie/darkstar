"""
Tests for Executor Override Logic

Tests the override evaluation logic that determines when real-time
conditions should override the scheduled plan.
"""

from executor.override import (
    OverrideEvaluator,
    OverrideResult,
    OverrideType,
    SlotPlan,
    SystemState,
    evaluate_overrides,
)


class TestSystemState:
    """Test the SystemState dataclass."""

    def test_default_values(self):
        """SystemState should have sensible defaults."""
        state = SystemState()
        assert state.current_soc_percent == 50.0
        assert state.min_soc_percent == 10.0
        assert state.slot_exists is True
        assert state.slot_valid is True

    def test_custom_values(self):
        """SystemState accepts custom values."""
        state = SystemState(
            current_soc_percent=25.0,
            current_pv_kw=5.0,
            current_load_kw=2.0,
        )
        assert state.current_soc_percent == 25.0
        assert state.current_pv_kw == 5.0
        assert state.current_load_kw == 2.0


class TestSlotPlan:
    """Test the SlotPlan dataclass."""

    def test_default_values(self):
        """SlotPlan should have sensible defaults."""
        slot = SlotPlan()
        assert slot.charge_kw == 0.0
        assert slot.export_kw == 0.0
        assert slot.soc_target == 50

    def test_custom_values(self):
        """SlotPlan accepts custom values."""
        slot = SlotPlan(charge_kw=5.0, export_kw=3.0, soc_target=80)
        assert slot.charge_kw == 5.0
        assert slot.export_kw == 3.0
        assert slot.soc_target == 80


class TestOverrideResult:
    """Test the OverrideResult dataclass."""

    def test_default_no_override(self):
        """Default OverrideResult means no override."""
        result = OverrideResult()
        assert result.override_needed is False
        assert result.override_type == OverrideType.NONE
        assert result.actions == {}

    def test_actions_default_to_empty_dict(self):
        """Actions should default to empty dict, not None."""
        result = OverrideResult(override_needed=True)
        assert result.actions == {}


class TestOverrideEvaluatorManualOverride:
    """Test Priority 10: Manual override detection."""

    def test_manual_override_active(self):
        """When manual_override_active=True, should return manual override."""
        evaluator = OverrideEvaluator()
        state = SystemState(manual_override_active=True)

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.MANUAL_OVERRIDE
        assert result.priority == 10.0
        assert "Manual override" in result.reason

    def test_manual_override_inactive(self):
        """When manual_override_active=False, should not trigger."""
        evaluator = OverrideEvaluator()
        state = SystemState(manual_override_active=False)

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.MANUAL_OVERRIDE


class TestOverrideEvaluatorSlotFailure:
    """Test Priority 8: Slot failure fallback."""

    def test_no_slot_exists_triggers_fallback(self):
        """When no slot exists, use safe fallback."""
        evaluator = OverrideEvaluator()
        state = SystemState(slot_exists=False)

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.SLOT_FAILURE_FALLBACK
        assert result.priority == 8.0
        assert result.actions["grid_charging"] is False
        assert result.actions["grid_charging"] is False

    def test_slot_invalid_triggers_fallback(self):
        """When slot is invalid, use safe fallback."""
        evaluator = OverrideEvaluator()
        state = SystemState(slot_exists=True, slot_valid=False)

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.SLOT_FAILURE_FALLBACK

    def test_valid_slot_no_fallback(self):
        """With valid slot, no fallback needed."""
        evaluator = OverrideEvaluator()
        state = SystemState(slot_exists=True, slot_valid=True)

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.SLOT_FAILURE_FALLBACK

    def test_slot_failure_without_water_heater_excludes_water_temp(self):
        """Slot failure without water heater - no water_temp in actions."""
        evaluator = OverrideEvaluator(water_temp_off=40)
        state = SystemState(
            has_water_heater=False,
            slot_exists=False,
            current_soc_percent=50.0,
        )

        result = evaluator.evaluate(state)

        assert result.override_type == OverrideType.SLOT_FAILURE_FALLBACK
        assert "water_temp" not in result.actions
        assert result.actions["grid_charging"] is False
        assert result.actions["soc_target"] == 50

    def test_slot_failure_with_water_heater_includes_water_temp(self):
        """Slot failure with water heater - water_temp included in actions."""
        evaluator = OverrideEvaluator(water_temp_off=40)
        state = SystemState(
            has_water_heater=True,
            slot_exists=False,
            current_soc_percent=50.0,
        )

        result = evaluator.evaluate(state)

        assert result.override_type == OverrideType.SLOT_FAILURE_FALLBACK
        assert result.actions["water_temp"] == 40
        assert result.actions["grid_charging"] is False
        assert result.actions["soc_target"] == 50


class TestOverrideEvaluatorExcessPVHeatingRemoved:
    """Verify EXCESS_PV_HEATING override was removed (now handled by planner)."""

    def test_override_type_removed(self):
        """EXCESS_PV_HEATING should no longer exist in OverrideType enum."""
        assert not hasattr(OverrideType, "EXCESS_PV_HEATING")

    def test_excess_pv_params_removed(self):
        """OverrideEvaluator should not accept excess_pv_threshold_kw."""
        evaluator = OverrideEvaluator()
        assert not hasattr(evaluator, "excess_pv_threshold_kw")

    def test_excess_pv_no_longer_triggers(self):
        """Excess PV conditions should not trigger any override (handled by planner)."""
        evaluator = OverrideEvaluator()
        state = SystemState(
            current_pv_kw=5.0,
            current_load_kw=2.0,
            current_soc_percent=95.0,
            current_water_temp=55.0,
        )

        result = evaluator.evaluate(state)

        assert result.override_needed is False
        assert result.override_type == OverrideType.NONE

    def test_evaluate_overrides_no_excess_pv_param(self):
        """evaluate_overrides should not require excess_pv_threshold_kw."""
        state = SystemState(
            current_pv_kw=5.0,
            current_load_kw=2.0,
        )

        result = evaluate_overrides(state)

        assert result.override_needed is False


class TestOverrideEvaluatorNoOverride:
    """Test case when no override is needed."""

    def test_normal_operation_no_override(self):
        """Normal operation with valid slot and healthy state - no override."""
        evaluator = OverrideEvaluator()
        state = SystemState(
            current_soc_percent=50.0,
            slot_exists=True,
            slot_valid=True,
            manual_override_active=False,
        )
        slot = SlotPlan()

        result = evaluator.evaluate(state, slot)

        assert result.override_needed is False
        assert result.override_type == OverrideType.NONE
        assert result.priority == 0.0


class TestOverridePriority:
    """Test that higher priority overrides take precedence."""

    def test_manual_override_beats_slot_failure(self):
        """Manual override (10) should win over slot failure (8)."""
        evaluator = OverrideEvaluator()
        state = SystemState(
            slot_exists=False,  # Would trigger slot failure
            manual_override_active=True,  # But manual is higher priority
        )

        result = evaluator.evaluate(state)

        assert result.override_type == OverrideType.MANUAL_OVERRIDE


class TestEvaluateOverridesConvenienceFunction:
    """Test the evaluate_overrides convenience function."""

    def test_with_default_config(self):
        """Works with default config."""
        state = SystemState(current_soc_percent=50.0)
        result = evaluate_overrides(state)

        assert isinstance(result, OverrideResult)
        assert result.override_needed is False

    def test_with_custom_config(self):
        """Works with custom water-heater config values."""
        state = SystemState(current_soc_percent=5.0)
        config = {"water_temp_off": 40}

        result = evaluate_overrides(state, config=config)

        assert isinstance(result, OverrideResult)
        assert result.override_needed is False

    def test_with_slot_plan(self):
        """Works with slot plan provided."""
        state = SystemState(current_soc_percent=50.0)
        slot = SlotPlan(export_kw=5.0)

        result = evaluate_overrides(state, slot)

        assert isinstance(result, OverrideResult)
        assert result.override_needed is False
