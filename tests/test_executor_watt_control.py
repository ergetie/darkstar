"""
Tests for Executor Watt-based Control
"""
import pytest

from executor.config import ControllerConfig, InverterConfig
from executor.controller import Controller
from executor.override import SlotPlan, SystemState


class TestWattControl:
    """Test Watt-based control logic in Controller."""

    @pytest.fixture
    def controller_w(self):
        """Create a controller configured for Watts."""
        inverter_cfg = InverterConfig(control_unit="W")
        controller_cfg = ControllerConfig(
            max_charge_w=5000.0,
            max_discharge_w=6000.0,
            min_charge_w=500.0,
            round_step_w=100.0,
        )
        return Controller(controller_cfg, inverter_cfg)

    @pytest.fixture
    def controller_a(self):
        """Create a controller configured for Amps."""
        inverter_cfg = InverterConfig(control_unit="A")
        controller_cfg = ControllerConfig(
            max_charge_a=100.0,
            max_discharge_a=100.0,
            min_charge_a=10.0,
            round_step_a=5.0,
            worst_case_voltage_v=50.0 # Simple math: 100A * 50V = 5000W
        )
        return Controller(controller_cfg, inverter_cfg)

    def test_charge_calculation_watts(self, controller_w):
        """Verify charge calculation in Watts."""
        # Plan: 2.5 kW charge
        slot = SlotPlan(charge_kw=2.5)
        state = SystemState()

        val, write = controller_w._calculate_charge_limit(slot, state)

        # Should be 2500 Watts
        assert val == 2500.0
        assert write is True

    def test_charge_calculation_rounding_watts(self, controller_w):
        """Verify rounding in Watts."""
        # Plan: 2.55 kW -> 2550 W
        # Round step is 100 W
        slot = SlotPlan(charge_kw=2.55)
        state = SystemState()

        val, _ = controller_w._calculate_charge_limit(slot, state)

        # Should round to nearest 100W -> 2600W
        assert val == 2600.0

    def test_charge_clamping_watts(self, controller_w):
        """Verify max/min clamping in Watts."""
        # Plan: 10 kW -> 10000 W (Max is 5000)
        slot_max = SlotPlan(charge_kw=10.0)
        state = SystemState()
        val_max, _ = controller_w._calculate_charge_limit(slot_max, state)
        assert val_max == 5000.0

        # Plan: 0.2 kW -> 200 W (Min is 500)
        slot_min = SlotPlan(charge_kw=0.2)
        val_min, _ = controller_w._calculate_charge_limit(slot_min, state)
        assert val_min == 500.0

    def test_discharge_limit_watts(self, controller_w):
        """Verify discharge limit in Watts."""
        slot = SlotPlan()
        state = SystemState()

        val, _ = controller_w._calculate_discharge_limit(slot, state)

        # Should return max discharge W
        assert val == 6000.0

    def test_decision_includes_unit(self, controller_w):
        """Verify decision includes correct control unit."""
        slot = SlotPlan(charge_kw=2.0)
        state = SystemState()
        decision = controller_w.decide(slot, state)

        assert decision.control_unit == "W"
        assert decision.charge_value == 2000.0
