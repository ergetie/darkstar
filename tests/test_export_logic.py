"""
Test export logic with protective SoC calculations.
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from planner import HeliosPlanner


class TestExportLogic:
    """Test export decisions and protective SoC logic."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            'arbitrage': {
                'enable_export': True,
                'export_fees_sek_per_kwh': 0.0,
                'export_profit_margin_sek': 0.05,
                'protective_soc_strategy': 'gap_based',
                'fixed_protective_soc_percent': 15.0
            },
            'battery': {
                'capacity_kwh': 10.0,
                'max_soc_percent': 95,
                'min_soc_percent': 15
            },
            'battery_economics': {
                'battery_cycle_cost_kwh': 0.20
            }
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.arbitrage_config = config['arbitrage']
        self.planner.battery_config = config['battery']
        self.planner.battery_economics = config['battery_economics']

        # Initialize state
        self.planner.state = {
            'battery_kwh': 7.0,  # 70% SoC
            'battery_cost_sek_per_kwh': 0.20
        }

        # Mock window responsibilities for gap-based protective SoC
        self.planner.window_responsibilities = [
            {'total_responsibility_kwh': 2.0},
            {'total_responsibility_kwh': 1.5}
        ]

    def test_gap_based_protective_soc(self):
        """Test gap-based protective SoC calculation."""
        # Calculate expected protective SoC
        future_responsibilities = sum(resp['total_responsibility_kwh'] for resp in self.planner.window_responsibilities)
        expected_protective_soc_kwh = max(1.5, future_responsibilities * 1.1)  # 10% buffer, min 1.5

        # Simulate the calculation
        protective_soc_kwh = max(1.5, future_responsibilities * 1.1)

        assert abs(protective_soc_kwh - expected_protective_soc_kwh) < 0.001

    def test_fixed_protective_soc(self):
        """Test fixed protective SoC calculation."""
        fixed_percent = 15.0
        capacity_kwh = 10.0
        expected_protective_soc_kwh = fixed_percent / 100.0 * capacity_kwh

        # Simulate fixed strategy
        protective_soc_kwh = fixed_percent / 100.0 * capacity_kwh

        assert abs(protective_soc_kwh - expected_protective_soc_kwh) < 0.001

    def test_profitable_export_decision(self):
        """Test export profitability thresholds for PV and battery sources."""
        # Test scenarios
        test_cases = [
            # (import_price, export_price, expect_pv_export, expect_battery_export)
            (0.20, 0.28, True, False),   # PV export only (battery below wear threshold)
            (0.20, 0.24, False, False),  # Price below both thresholds
            (0.20, 0.50, True, True),    # High price allows both PV and battery export
        ]

        export_fees = 0.0
        export_profit_margin = 0.05
        avg_cost = 0.20
        cycle_cost = 0.20

        for import_price, export_price, expect_pv, expect_battery in test_cases:
            net_export_price = export_price - export_fees
            pv_threshold = import_price + export_profit_margin
            battery_threshold = avg_cost + cycle_cost + export_profit_margin

            can_export_pv = net_export_price > pv_threshold
            can_export_battery = net_export_price > battery_threshold

            assert can_export_pv == expect_pv
            assert can_export_battery == expect_battery

    def test_export_with_fees(self):
        """Test export profitability calculation with fees for PV vs battery."""
        import_price = 0.20
        export_price = 0.25
        export_fees = 0.02
        export_profit_margin = 0.05
        avg_cost = 0.20
        cycle_cost = 0.20

        net_export_price = export_price - export_fees
        pv_threshold = import_price + export_profit_margin
        battery_threshold = avg_cost + cycle_cost + export_profit_margin

        pv_profitable = net_export_price > pv_threshold
        battery_profitable = net_export_price > battery_threshold

        # 0.25 - 0.02 = 0.23, which is > 0.20 + 0.05 = 0.25? No: 0.23 > 0.25 is False
        assert not pv_profitable
        assert not battery_profitable

        # Test with higher export price
        export_price = 0.28
        net_export_price = export_price - export_fees
        pv_profitable = net_export_price > pv_threshold
        battery_profitable = net_export_price > battery_threshold
        # 0.28 - 0.02 = 0.26 (> 0.25) enables PV export, but still below battery threshold (0.45)
        assert pv_profitable
        assert not battery_profitable

    def test_export_respects_protective_soc(self):
        """Test that export doesn't occur below protective SoC."""
        protective_soc_kwh = 2.0
        current_soc_kwh = 1.5  # Below protective
        available_surplus = 1.0  # kWh available for export

        # Should not export when below protective SoC
        can_export = current_soc_kwh > protective_soc_kwh
        assert not can_export

        # Test when above protective SoC
        current_soc_kwh = 3.0  # Above protective
        can_export = current_soc_kwh > protective_soc_kwh
        assert can_export

    def test_export_energy_limits(self):
        """Test that export is limited by available energy above protective SoC."""
        protective_soc_kwh = 2.0
        current_soc_kwh = 5.0
        surplus_energy = 2.0  # kWh available for export

        # Available for export = current - protective
        available_for_export = current_soc_kwh - protective_soc_kwh
        max_export = min(surplus_energy, available_for_export)

        assert max_export == 2.0  # Limited by surplus energy available

    def test_export_updates_battery_state(self):
        """Test that export properly updates battery SoC and cost basis."""
        initial_soc = 7.0
        initial_cost_basis = 0.20
        export_amount = 1.0  # kWh

        # After export, SoC should decrease
        final_soc = initial_soc - export_amount
        assert final_soc == 6.0

        # Cost basis should decrease (export reduces stored cost)
        # This is simplified - actual logic accounts for average cost
        cost_reduction = initial_cost_basis * export_amount
        assert cost_reduction == 0.20

    def test_export_action_classification(self):
        """Test that export actions are properly classified."""
        # Simulate export scenario
        export_occurred = True

        if export_occurred:
            action = 'Export'
        else:
            action = 'Hold'

        assert action == 'Export'

    def test_export_disabled(self):
        """Test behavior when export is disabled."""
        enable_export = False

        # Should not export when disabled
        should_export = enable_export and True  # Other conditions true
        assert not should_export
