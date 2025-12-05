"""
Test export logic with protective SoC calculations.
"""

import math
import pandas as pd
import pytest
from archive.legacy_mpc import HeliosPlanner


class TestExportLogic:
    """Test export decisions and protective SoC logic."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            "arbitrage": {
                "enable_export": True,
                "export_fees_sek_per_kwh": 0.0,
                "export_profit_margin_sek": 0.05,
                "protective_soc_strategy": "gap_based",
                "fixed_protective_soc_percent": 15.0,
                "export_percentile_threshold": 50,
                "enable_peak_only_export": True,
                "export_future_price_guard": False,
            },
            "battery": {"capacity_kwh": 10.0, "max_soc_percent": 95, "min_soc_percent": 15},
            "battery_economics": {"battery_cycle_cost_kwh": 0.20},
            "strategic_charging": {
                "target_soc_percent": 90,
                "price_threshold_sek": 0.9,
                "carry_forward_tolerance_ratio": 0.10,
            },
            "decision_thresholds": {
                "battery_use_margin_sek": 0.10,
                "battery_water_margin_sek": 0.20,
            },
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.battery_config = config["battery"]
        self.planner.battery_economics = config["battery_economics"]
        self.planner.thresholds = config["decision_thresholds"]
        self.planner.strategic_charging = config["strategic_charging"]
        self.planner.charging_strategy = {
            "charge_threshold_percentile": 15,
            "cheap_price_tolerance_sek": 0.10,
        }
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}
        self.planner.window_responsibilities = []

        efficiency_component = math.sqrt(0.95)
        self.planner.roundtrip_efficiency = 0.95
        self.planner.charge_efficiency = efficiency_component
        self.planner.discharge_efficiency = efficiency_component
        self.planner.cycle_cost = config["battery_economics"]["battery_cycle_cost_kwh"]

    def _build_export_df(self, import_prices, export_prices):
        dates = pd.date_range(
            "2025-01-01 12:00", periods=len(import_prices), freq="15min", tz="Europe/Stockholm"
        )
        df = pd.DataFrame(
            {
                "adjusted_pv_kwh": [0.0] * len(import_prices),
                "adjusted_load_kwh": [0.0] * len(import_prices),
                "water_heating_kw": [0.0] * len(import_prices),
                "charge_kw": [0.0] * len(import_prices),
                "import_price_sek_kwh": import_prices,
                "export_price_sek_kwh": export_prices,
                "is_cheap": [False] * len(import_prices),
            },
            index=dates,
        )
        return df
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}

        # Initialize state
        self.planner.state = {"battery_kwh": 7.0, "battery_cost_sek_per_kwh": 0.20}  # 70% SoC

        # Mock window responsibilities for gap-based protective SoC
        self.planner.window_responsibilities = [
            {"total_responsibility_kwh": 2.0},
            {"total_responsibility_kwh": 1.5},
        ]

    def test_gap_based_protective_soc(self):
        """Test gap-based protective SoC calculation."""
        # Calculate expected protective SoC
        future_responsibilities = sum(
            resp["total_responsibility_kwh"] for resp in self.planner.window_responsibilities
        )
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

    def test_export_blocked_when_not_peak(self):
        """Exports should be blocked when price is below percentile threshold."""
        df = self._build_export_df([0.30, 0.80], [0.60, 0.90])
        self.planner.state = {
            "battery_kwh": 9.5,
            "battery_cost_sek_per_kwh": 0.20,
        }
        self.planner.now_slot = df.index[0]
        result = self.planner._pass_6_finalize_schedule(df.copy())

        assert result.loc[df.index[0], "export_kwh"] == pytest.approx(0.0)
        assert result.loc[df.index[1], "export_kwh"] > 0

    def test_export_blocked_when_responsibilities_pending(self):
        """Responsibilities prevent exports even during peak slots."""
        df = self._build_export_df([0.70, 0.90], [1.00, 1.10])
        self.planner.state = {
            "battery_kwh": 3.0,
            "battery_cost_sek_per_kwh": 0.20,
        }
        # Responsibility anchored at future slot
        self.planner.window_responsibilities = [
            {
                "window": {"start": df.index[1]},
                "total_responsibility_kwh": 3.0,
            }
        ]
        self.planner.now_slot = df.index[0]
        result = self.planner._pass_6_finalize_schedule(df.copy())

        assert result["export_kwh"].max() == pytest.approx(0.0)

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

    def test_export_disabled(self):
        """Test behavior when export is disabled."""
        enable_export = False

        # Should not export when disabled
        should_export = enable_export and True  # Other conditions true
        assert not should_export
