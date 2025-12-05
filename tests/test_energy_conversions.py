"""
Test energy and cost conversion helpers in the planner.
"""

import math
from archive.legacy_mpc import HeliosPlanner


class TestEnergyConversions:
    """Test energy conversion helper methods."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            "battery": {
                "roundtrip_efficiency_percent": 95.0,
                "capacity_kwh": 10.0,
                "max_soc_percent": 95,
                "min_soc_percent": 15,
            },
            "battery_economics": {"battery_cycle_cost_kwh": 0.20},
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.battery_config = config["battery"]
        self.planner.battery_economics = config["battery_economics"]
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}

        # Initialize efficiency values
        roundtrip_percent = self.planner.battery_config.get("roundtrip_efficiency_percent", 95.0)
        self.planner.roundtrip_efficiency = roundtrip_percent / 100.0
        efficiency_component = math.sqrt(self.planner.roundtrip_efficiency)
        self.planner.charge_efficiency = efficiency_component
        self.planner.discharge_efficiency = efficiency_component
        self.planner.cycle_cost = self.planner.battery_economics.get("battery_cycle_cost_kwh", 0.0)

    def test_energy_into_battery(self):
        """Test energy stored in battery after charging losses."""
        # With 95% roundtrip efficiency, charge efficiency should be sqrt(0.95) ≈ 0.9747
        source_energy = 5.0  # kWh
        expected_stored = source_energy * self.planner.charge_efficiency
        actual_stored = self.planner._energy_into_battery(source_energy)

        assert abs(actual_stored - expected_stored) < 0.001

    def test_battery_energy_for_output(self):
        """Test energy needed from battery to deliver required output."""
        required_output = 4.0  # kWh
        expected_battery_energy = required_output / self.planner.discharge_efficiency
        actual_battery_energy = self.planner._battery_energy_for_output(required_output)

        assert abs(actual_battery_energy - expected_battery_energy) < 0.001

    def test_battery_output_from_energy(self):
        """Test energy delivered from battery after discharge losses."""
        battery_energy = 4.5  # kWh
        expected_output = battery_energy * self.planner.discharge_efficiency
        actual_output = self.planner._battery_output_from_energy(battery_energy)

        assert abs(actual_output - expected_output) < 0.001

    def test_zero_efficiency_handling(self):
        """Test behavior with zero efficiency."""
        # Temporarily set zero efficiency
        original_charge_eff = self.planner.charge_efficiency
        original_discharge_eff = self.planner.discharge_efficiency

        self.planner.charge_efficiency = 0.0
        self.planner.discharge_efficiency = 0.0

        # Test that _energy_into_battery returns 0
        assert self.planner._energy_into_battery(5.0) == 0.0

        # Test that _battery_energy_for_output returns infinity
        assert self.planner._battery_energy_for_output(4.0) == float("inf")

        # Test that _battery_output_from_energy returns 0
        assert self.planner._battery_output_from_energy(4.5) == 0.0

        # Restore original values
        self.planner.charge_efficiency = original_charge_eff
        self.planner.discharge_efficiency = original_discharge_eff

    def test_roundtrip_efficiency_calculation(self):
        """Test that roundtrip efficiency is correctly split into charge/discharge."""
        # 95% roundtrip should give ~97.47% charge/discharge efficiency
        expected_efficiency = math.sqrt(0.95)
        assert abs(self.planner.charge_efficiency - expected_efficiency) < 0.001
        assert abs(self.planner.discharge_efficiency - expected_efficiency) < 0.001

    def test_cycle_cost_integration(self):
        """Test that cycle cost is properly initialized."""
        assert self.planner.cycle_cost == 0.20
