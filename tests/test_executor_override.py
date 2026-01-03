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


class TestOverrideEvaluatorEmergencyCharge:
    """Test Priority 9: Emergency charge when SoC at floor."""

    def test_soc_at_floor_triggers_emergency(self):
        """SoC at minimum floor should trigger emergency charge."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0)
        state = SystemState(current_soc_percent=10.0)

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.EMERGENCY_CHARGE
        assert result.priority == 9.0
        assert result.actions["grid_charging"] is True
        assert result.actions["work_mode"] == "Zero Export To CT"

    def test_soc_below_floor_triggers_emergency(self):
        """SoC below minimum floor should trigger emergency charge."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0)
        state = SystemState(current_soc_percent=5.0)

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.EMERGENCY_CHARGE

    def test_soc_above_floor_no_emergency(self):
        """SoC above minimum floor should not trigger emergency."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0)
        state = SystemState(current_soc_percent=15.0)

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.EMERGENCY_CHARGE


class TestOverrideEvaluatorLowSocExportPrevention:
    """Test Priority 8.5: Low SoC export prevention."""

    def test_export_planned_low_soc_triggers(self):
        """Plan wants to export but SoC is dangerously low - prevent."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0, low_soc_threshold=20.0)
        state = SystemState(current_soc_percent=15.0)  # Above floor, below threshold
        slot = SlotPlan(export_kw=5.0)  # Plan wants to export

        result = evaluator.evaluate(state, slot)

        assert result.override_needed is True
        assert result.override_type == OverrideType.LOW_SOC_EXPORT_PREVENTION
        assert result.priority == 8.5
        assert result.actions["work_mode"] == "Zero Export To CT"

    def test_export_planned_soc_ok_no_trigger(self):
        """Plan wants to export and SoC is healthy - allow."""
        evaluator = OverrideEvaluator(low_soc_threshold=20.0)
        state = SystemState(current_soc_percent=50.0)  # Healthy
        slot = SlotPlan(export_kw=5.0)

        result = evaluator.evaluate(state, slot)

        assert result.override_type != OverrideType.LOW_SOC_EXPORT_PREVENTION

    def test_no_export_planned_low_soc_no_trigger(self):
        """No export planned - no prevention needed even at low SoC."""
        evaluator = OverrideEvaluator(low_soc_threshold=20.0)
        state = SystemState(current_soc_percent=15.0)
        slot = SlotPlan(export_kw=0.0)  # No export

        result = evaluator.evaluate(state, slot)

        assert result.override_type != OverrideType.LOW_SOC_EXPORT_PREVENTION


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
        assert result.actions["work_mode"] == "Zero Export To CT"
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


class TestOverrideEvaluatorExcessPVHeating:
    """Test Priority 5: Excess PV heating."""

    def test_excess_pv_healthy_battery_triggers_heating(self):
        """Excess PV with healthy battery and cold water triggers heating."""
        evaluator = OverrideEvaluator(
            excess_pv_threshold_kw=2.0,
            water_temp_boost=70,  # Configured boost
            water_temp_max=85,    # Configured max
        )
        state = SystemState(
            current_pv_kw=5.0,
            current_load_kw=2.0,  # Excess = 3 kW
            current_soc_percent=60.0,  # Healthy
            current_water_temp=55.0,  # Below boost temp
        )

        result = evaluator.evaluate(state)

        assert result.override_needed is True
        assert result.override_type == OverrideType.EXCESS_PV_HEATING
        assert result.priority == 5.0
        # Should heat to MAX (dump load), not just boost
        assert result.actions["water_temp"] == 85

    def test_excess_pv_low_battery_no_heating(self):
        """Excess PV but low battery - preserve battery instead of heating."""
        evaluator = OverrideEvaluator(excess_pv_threshold_kw=2.0)
        state = SystemState(
            current_pv_kw=5.0,
            current_load_kw=2.0,  # Excess = 3 kW
            current_soc_percent=40.0,  # Below 50% threshold
            current_water_temp=55.0,
        )

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.EXCESS_PV_HEATING

    def test_no_excess_pv_no_heating(self):
        """Without excess PV, no heating override."""
        evaluator = OverrideEvaluator(excess_pv_threshold_kw=2.0)
        state = SystemState(
            current_pv_kw=3.0,
            current_load_kw=3.0,  # No excess
            current_soc_percent=60.0,
            current_water_temp=55.0,
        )

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.EXCESS_PV_HEATING

    def test_water_already_hot_no_heating(self):
        """Water already at MAX temp - no need to heat more."""
        evaluator = OverrideEvaluator(
            excess_pv_threshold_kw=2.0,
            water_temp_boost=70,
            water_temp_max=85,
        )
        state = SystemState(
            current_pv_kw=5.0,
            current_load_kw=2.0,
            current_soc_percent=60.0,
            current_water_temp=86.0,  # Already above MAX
        )

        result = evaluator.evaluate(state)

        assert result.override_type != OverrideType.EXCESS_PV_HEATING


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

    def test_manual_override_beats_emergency(self):
        """Manual override (10) should win over emergency charge (9)."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0)
        state = SystemState(
            current_soc_percent=5.0,  # Would trigger emergency
            manual_override_active=True,  # But manual is higher priority
        )

        result = evaluator.evaluate(state)

        assert result.override_type == OverrideType.MANUAL_OVERRIDE

    def test_emergency_beats_slot_failure(self):
        """Emergency charge (9) should win over slot failure (8)."""
        evaluator = OverrideEvaluator(min_soc_floor=10.0)
        state = SystemState(
            current_soc_percent=5.0,  # Would trigger emergency
            slot_exists=False,  # Also slot failure
        )

        result = evaluator.evaluate(state)

        assert result.override_type == OverrideType.EMERGENCY_CHARGE


class TestEvaluateOverridesConvenienceFunction:
    """Test the evaluate_overrides convenience function."""

    def test_with_default_config(self):
        """Works with default config."""
        state = SystemState(current_soc_percent=50.0)
        result = evaluate_overrides(state)

        assert isinstance(result, OverrideResult)
        assert result.override_needed is False

    def test_with_custom_config(self):
        """Works with custom config values."""
        state = SystemState(current_soc_percent=5.0)
        config = {"min_soc_floor": 10.0}

        result = evaluate_overrides(state, config=config)

        assert result.override_needed is True
        assert result.override_type == OverrideType.EMERGENCY_CHARGE

    def test_with_slot_plan(self):
        """Works with slot plan provided."""
        state = SystemState(current_soc_percent=15.0)
        slot = SlotPlan(export_kw=5.0)
        config = {"low_soc_threshold": 20.0}

        result = evaluate_overrides(state, slot, config)

        assert result.override_type == OverrideType.LOW_SOC_EXPORT_PREVENTION
