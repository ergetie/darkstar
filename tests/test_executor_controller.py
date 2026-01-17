"""
Tests for Executor Controller Logic

Tests the controller decision-making that determines what actions to take
based on slot plan and override state.
"""

import pytest

from executor.config import ControllerConfig, InverterConfig
from executor.controller import Controller, ControllerDecision, make_decision
from executor.override import OverrideResult, OverrideType, SlotPlan, SystemState


class TestControllerDecision:
    """Test the ControllerDecision dataclass."""

    def test_required_fields(self):
        """ControllerDecision requires core action fields."""
        decision = ControllerDecision(
            work_mode="Export First",
            grid_charging=True,
            charge_value=100.0,
            discharge_value=50.0,
            soc_target=80,
            water_temp=60,
        )
        assert decision.work_mode == "Export First"
        assert decision.grid_charging is True
        assert decision.charge_value == 100.0
        assert decision.soc_target == 80

    def test_default_flags(self):
        """ControllerDecision has sensible default flags."""
        decision = ControllerDecision(
            work_mode="Zero Export To CT",
            grid_charging=False,
            charge_value=0.0,
            discharge_value=0.0,
            soc_target=50,
            water_temp=40,
        )
        assert decision.write_charge_current is False
        assert decision.write_discharge_current is False
        assert decision.source == "plan"
        assert decision.reason == ""


class TestControllerConfig:
    """Test the ControllerConfig dataclass."""

    def test_default_values(self):
        """ControllerConfig has sensible defaults."""
        config = ControllerConfig()
        assert config.battery_capacity_kwh == 27.0
        assert config.nominal_voltage_v == 48.0
        assert config.min_charge_a == 10.0
        assert config.max_charge_a == 185.0
        assert config.max_discharge_a == 185.0
        assert config.round_step_a == 5.0

    def test_custom_values(self):
        """ControllerConfig can be initialized with custom values."""
        config = ControllerConfig(
            battery_capacity_kwh=30.0,
            nominal_voltage_v=50.0,
            min_charge_a=5.0,
            max_charge_a=200.0,
            max_discharge_a=200.0,
            round_step_a=10.0,
        )
        assert config.battery_capacity_kwh == 30.0
        assert config.nominal_voltage_v == 50.0
        assert config.min_charge_a == 5.0
        assert config.max_charge_a == 200.0
        assert config.max_discharge_a == 200.0
        assert config.round_step_a == 10.0


class TestControllerFollowPlan:
    """Test Controller._follow_plan behavior."""

    @pytest.fixture
    def controller(self):
        """Create a controller with default config."""
        return Controller(ControllerConfig(), InverterConfig())

    def test_export_mode_when_export_planned(self, controller):
        """When export is planned, use Export First mode."""
        slot = SlotPlan(export_kw=5.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.work_mode == "Export First"
        assert decision.source == "plan"

    def test_zero_export_mode_when_no_export(self, controller):
        """When no export planned, use Zero Export mode."""
        slot = SlotPlan(export_kw=0.0, charge_kw=3.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.work_mode == "Zero Export To CT"

    def test_grid_charging_when_charging_only(self, controller):
        """Grid charging enabled when charging and not exporting."""
        slot = SlotPlan(charge_kw=5.0, export_kw=0.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.grid_charging is True

    def test_no_grid_charging_when_exporting(self, controller):
        """Grid charging disabled when exporting."""
        slot = SlotPlan(charge_kw=0.0, export_kw=5.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.grid_charging is False

    def test_soc_target_from_plan(self, controller):
        """SoC target comes from slot plan."""
        slot = SlotPlan(soc_target=85)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.soc_target == 85

    def test_water_temp_active_when_water_planned(self, controller):
        """Water temp set to 60 when water heating planned."""
        slot = SlotPlan(water_kw=3.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.water_temp == 60  # Normal heating temp

    def test_water_temp_off_when_no_water(self, controller):
        """Water temp set to 40 (off) when no water heating."""
        slot = SlotPlan(water_kw=0.0)
        state = SystemState()

        decision = controller.decide(slot, state)

        assert decision.water_temp == 40  # Off/minimum


class TestControllerApplyOverride:
    """Test Controller._apply_override behavior."""

    @pytest.fixture
    def controller(self):
        """Create a controller with default config."""
        return Controller(ControllerConfig(), InverterConfig())

    def test_override_uses_override_values(self, controller):
        """When override is active, use override values."""
        slot = SlotPlan(export_kw=5.0)  # Plan says export
        state = SystemState()
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.EMERGENCY_CHARGE,
            actions={
                "work_mode": "Zero Export To CT",
                "grid_charging": True,
                "soc_target": 30,
            },
        )

        decision = controller.decide(slot, state, override)

        assert decision.work_mode == "Zero Export To CT"  # Override wins
        assert decision.grid_charging is True
        assert decision.soc_target == 30
        assert decision.source == "override"

    def test_override_source_is_override(self, controller):
        """Decision source is 'override' when override is active."""
        slot = SlotPlan()
        state = SystemState()
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.MANUAL_OVERRIDE,
            reason="User override",
        )

        decision = controller.decide(slot, state, override)

        assert decision.source == "override"
        assert decision.reason == "User override"

    def test_force_charge_sets_max_current(self, controller):
        """Force charge override sets max charging current."""
        slot = SlotPlan()
        state = SystemState()
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.FORCE_CHARGE,
            actions={"grid_charging": True},
        )

        decision = controller.decide(slot, state, override)

        # Default is Amps
        assert decision.charge_value == controller.config.max_charge_a
        assert decision.write_charge_current is True

    def test_force_export_sets_max_discharge(self, controller):
        """Force export override sets max discharge current."""
        slot = SlotPlan()
        state = SystemState()
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.FORCE_EXPORT,
            actions={},
        )

        decision = controller.decide(slot, state, override)

        assert decision.discharge_value == controller.config.max_discharge_a
        assert decision.write_discharge_current is True

    def test_no_override_follows_plan(self, controller):
        """When no override, decision follows plan."""
        slot = SlotPlan(export_kw=5.0)
        state = SystemState()
        override = None

        decision = controller.decide(slot, state, override)

        assert decision.source == "plan"
        assert decision.work_mode == "Export First"


class TestCalculateChargeCurrent:
    """Test Controller._calculate_charge_current."""

    def test_no_charge_planned_returns_zero(self):
        """When no charge planned, return 0."""
        config = ControllerConfig(min_voltage_v=46.0)
        controller = Controller(config, InverterConfig())
        slot = SlotPlan(charge_kw=0.0)
        state = SystemState()

        current, should_write = controller._calculate_charge_limit(slot, state)

        assert current == 0.0
        assert should_write is False

    def test_kw_to_amps_conversion(self):
        """Correctly converts kW to Amps."""
        config = ControllerConfig(
            min_voltage_v=46.0,
            round_step_a=5.0,
            min_charge_a=10.0,
            max_charge_a=185.0,
        )
        controller = Controller(config, InverterConfig())
        # 5 kW at 46V = 5000/46 ≈ 108.7A → rounds to 110A
        slot = SlotPlan(charge_kw=5.0)
        state = SystemState()

        current, _ = controller._calculate_charge_limit(slot, state)

        assert current == 110.0  # Rounded to step

    def test_respects_min_limit(self):
        """Current is clamped to minimum."""
        config = ControllerConfig(
            min_voltage_v=46.0,
            round_step_a=5.0,
            min_charge_a=10.0,
            max_charge_a=185.0,
        )
        controller = Controller(config, InverterConfig())
        # Very small charge → would be below min
        slot = SlotPlan(charge_kw=0.1)  # 0.1kW at 46V ≈ 2.2A
        state = SystemState()

        current, _ = controller._calculate_charge_limit(slot, state)

        assert current >= config.min_charge_a

    def test_respects_max_limit(self):
        """Current is clamped to maximum."""
        config = ControllerConfig(
            min_voltage_v=46.0,
            round_step_a=5.0,
            min_charge_a=10.0,
            max_charge_a=185.0,
        )
        controller = Controller(config, InverterConfig())
        # Very high charge → would exceed max
        slot = SlotPlan(charge_kw=20.0)  # 20kW at 46V ≈ 435A
        state = SystemState()

        current, _ = controller._calculate_charge_limit(slot, state)

        assert current <= config.max_charge_a


class TestCalculateDischargeCurrent:
    """Test Controller._calculate_discharge_current."""

    def test_export_mode_limits_discharge(self):
        """When exporting, discharge is limited to export rate."""
        config = ControllerConfig(
            min_voltage_v=46.0,
            round_step_a=5.0,
            min_charge_a=10.0,
            max_charge_a=185.0,
            max_discharge_a=185.0,
        )
        controller = Controller(config, InverterConfig())
        # 3 kW export at 46V ≈ 65A → rounds to 65A
        slot = SlotPlan(export_kw=3.0)
        state = SystemState()

        current, should_write = controller._calculate_discharge_limit(slot, state)

        # Bug fix #1: Even when exporting, we set discharge to MAX
        # so local load spikes are handled by battery.
        assert current == 185.0
        assert should_write is True

    def test_no_export_sets_max_discharge(self):
        """When not exporting, discharge is set to max for load handling."""
        config = ControllerConfig(max_discharge_a=185.0)
        controller = Controller(config, InverterConfig())
        slot = SlotPlan(export_kw=0.0)
        state = SystemState()

        current, should_write = controller._calculate_discharge_limit(slot, state)

        assert current == 185.0  # Max for load spikes
        assert should_write is True


class TestGenerateReason:
    """Test Controller._generate_reason."""

    def test_charge_reason(self):
        """Reason includes charge info."""
        controller = Controller(ControllerConfig(), InverterConfig())
        slot = SlotPlan(charge_kw=5.0)

        reason = controller._generate_reason(slot, "Zero Export To CT", True)

        assert "Charge 5.0kW" in reason
        assert "Grid+" in reason

    def test_export_reason(self):
        """Reason includes export info."""
        controller = Controller(ControllerConfig(), InverterConfig())
        slot = SlotPlan(export_kw=3.0)

        reason = controller._generate_reason(slot, "Export First", False)

        assert "Export 3.0kW" in reason
        assert "Export" in reason

    def test_idle_reason(self):
        """Reason shows idle when nothing planned."""
        controller = Controller(ControllerConfig(), InverterConfig())
        slot = SlotPlan()

        reason = controller._generate_reason(slot, "Zero Export To CT", False)

        assert "Hold/Idle" in reason


class TestMakeDecisionConvenience:
    """Test the make_decision convenience function."""

    def test_with_defaults(self):
        """Works with default config."""
        slot = SlotPlan(export_kw=5.0)
        state = SystemState()

        decision = make_decision(slot, state)

        assert isinstance(decision, ControllerDecision)
        assert decision.work_mode == "Export First"

    def test_with_custom_config(self):
        """Works with custom config."""
        slot = SlotPlan(charge_kw=5.0)
        state = SystemState()
        config = ControllerConfig(max_charge_a=100.0)

        decision = make_decision(slot, state, config=config)

        # Charge current should respect custom max
        assert decision.charge_value <= 100.0

    def test_with_override(self):
        """Works with override."""
        slot = SlotPlan(export_kw=5.0)
        state = SystemState()
        override = OverrideResult(
            override_needed=True,
            override_type=OverrideType.EMERGENCY_CHARGE,
            actions={"work_mode": "Zero Export To CT"},
        )

        decision = make_decision(slot, state, override)

        assert decision.source == "override"
        assert decision.work_mode == "Zero Export To CT"
