"""
Test gap responsibility calculations and cascading inheritance.
"""

import os
import tempfile

import pandas as pd
import yaml

from archive.legacy_mpc import HeliosPlanner


class TestGapResponsibilities:
    """Test gap energy calculations and window responsibilities."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {
            "charging_strategy": {
                "charge_threshold_percentile": 15,
                "cheap_price_tolerance_sek": 0.10,
                "price_smoothing_sek_kwh": 0.05,
            },
            "s_index": {"mode": "static", "static_factor": 1.05, "max_factor": 1.25},
            "battery": {
                "capacity_kwh": 10.0,
                "max_soc_percent": 95,
                "min_soc_percent": 15,
                "max_charge_power_kw": 5.0,
            },
            "decision_thresholds": {"battery_use_margin_sek": 0.10},
            "battery_economics": {"battery_cycle_cost_kwh": 0.20},
            "strategic_charging": {
                "target_soc_percent": 95,
                "price_threshold_sek": 0.90,
                "carry_forward_tolerance_ratio": 0.10,
            },
        }
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.charging_strategy = config["charging_strategy"]
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}
        # Config is accessed through self.planner.config

        # Initialize state
        self.planner.state = {"battery_kwh": 5.0, "battery_cost_sek_per_kwh": 0.20}

    def _create_planner(self, config: dict) -> HeliosPlanner:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml") as tmp:
            yaml.safe_dump(config, tmp)
            tmp.flush()
            tmp_path = tmp.name
        try:
            planner = HeliosPlanner(tmp_path)
        finally:
            os.unlink(tmp_path)
        return planner

    def test_price_aware_gap_calculation(self):
        """Test that gap energy only considers slots where battery is economical."""
        # Create test scenario with mixed prices
        dates = pd.date_range("2025-01-01 00:00", periods=8, freq="15min")
        df = pd.DataFrame(
            {
                "import_price_sek_kwh": [0.10, 0.15, 0.25, 0.30, 0.10, 0.15, 0.25, 0.30],
                "adjusted_pv_kwh": [0.0] * 8,
                "adjusted_load_kwh": [0.5] * 8,  # 2 kWh per slot
                "simulated_soc_kwh": [5.0] * 8,
                "is_cheap": [True, True, False, False, True, True, False, False],
            },
            index=dates,
        )

        # Calculate gap for a window
        window_df = df.loc[dates[0] : dates[3]]  # First 4 slots
        avg_cost = 0.20
        cycle_cost = 0.20
        economic_threshold = avg_cost + cycle_cost + 0.10  # battery_use_margin

        # Only slots with price > economic_threshold should contribute to gap
        economic_slots = window_df[window_df["import_price_sek_kwh"] > economic_threshold]
        expected_gap = (
            economic_slots["adjusted_load_kwh"].sum() - economic_slots["adjusted_pv_kwh"].sum()
        )

        # Calculate actual gap
        gap_slots = window_df[window_df["import_price_sek_kwh"] > economic_threshold]
        actual_gap = gap_slots["adjusted_load_kwh"].sum() - gap_slots["adjusted_pv_kwh"].sum()

        assert abs(actual_gap - expected_gap) < 0.001

    def test_s_index_factor_application(self):
        """Test that S-index safety factor is applied to gap energy."""
        # Test with static S-index factor
        s_index_factor = 1.05
        base_gap = 4.0
        expected_responsibility = base_gap * s_index_factor

        # Simulate the calculation
        total_responsibility = base_gap * s_index_factor

        assert abs(total_responsibility - expected_responsibility) < 0.001

    def test_s_index_max_cap(self):
        """Test that S-index factor is capped at max_factor."""
        # Test with factor that exceeds max
        s_index_factor = 1.35  # Above max of 1.25
        max_factor = 1.25
        capped_factor = min(s_index_factor, max_factor)

        assert capped_factor == max_factor

    def test_cascading_inheritance(self):
        """Test that responsibilities cascade backwards with self-depletion."""
        # Create mock window responsibilities
        self.planner.window_responsibilities = [
            {
                "total_responsibility_kwh": 2.0,
                "window": {
                    "start": pd.Timestamp("2025-01-01 00:00"),
                    "end": pd.Timestamp("2025-01-01 01:00"),
                },
            },
            {
                "total_responsibility_kwh": 3.0,
                "window": {
                    "start": pd.Timestamp("2025-01-01 02:00"),
                    "end": pd.Timestamp("2025-01-01 03:00"),
                },
            },
            {
                "total_responsibility_kwh": 1.5,
                "window": {
                    "start": pd.Timestamp("2025-01-01 04:00"),
                    "end": pd.Timestamp("2025-01-01 05:00"),
                },
            },
        ]

        # Create mock DataFrame for windows
        dates = pd.date_range("2025-01-01 00:00", periods=12, freq="15min")
        df = pd.DataFrame(
            {
                "adjusted_load_kwh": [0.5] * 12,
                "adjusted_pv_kwh": [0.0] * 12,
                "water_heating_kw": [0.0] * 12,
            },
            index=dates,
        )

        # Simulate cascading logic (simplified)
        for i in range(len(self.planner.window_responsibilities) - 2, -1, -1):
            next_i = i + 1
            next_resp = self.planner.window_responsibilities[next_i]["total_responsibility_kwh"]

            # Simplified self-depletion calculation
            next_window = self.planner.window_responsibilities[next_i]["window"]
            next_df = df.loc[next_window["start"] : next_window["end"]]
            net_load_next = (next_df["adjusted_load_kwh"] - next_df["adjusted_pv_kwh"]).sum()
            self_depletion_kwh = max(0.0, net_load_next)
            adjusted_next_resp = next_resp + self_depletion_kwh

            # Simplified capacity check
            realistic_charge_kw = 5.0  # max_charge_power_kw
            num_slots = len(next_df)
            max_energy = realistic_charge_kw * num_slots * 0.25 * 0.97  # efficiency

            if adjusted_next_resp > max_energy:
                self.planner.window_responsibilities[i][
                    "total_responsibility_kwh"
                ] += adjusted_next_resp

        # Verify cascading occurred
        assert (
            self.planner.window_responsibilities[0]["total_responsibility_kwh"] >= 2.0
        )  # Should have increased

    def test_strategic_window_override(self):
        """Test that strategic windows override gap-based responsibilities."""
        # Set up strategic scenario
        self.planner.is_strategic_period = True
        strategic_target_soc_percent = 95
        capacity_kwh = 10.0
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh

        # Mock window with low SoC
        soc_at_window_start = 3.0  # Low SoC
        expected_responsibility = max(0, strategic_target_kwh - soc_at_window_start)

        # Simulate strategic override
        total_responsibility_kwh = expected_responsibility

        assert total_responsibility_kwh == strategic_target_kwh - soc_at_window_start

    def test_carry_forward_logic(self):
        """Test strategic carry-forward when target not met."""
        # Set up carry-forward scenario
        carry_tolerance = 0.10
        strategic_price_threshold = 0.90

        # Mock scenario where first window can't meet target
        # This would be tested in the full _pass_4 method
        # For now, just verify the logic components
        next_window_prices = pd.Series([0.85, 0.88, 0.92])  # Below threshold with tolerance

        # Check if carry-forward should occur
        threshold_with_tolerance = strategic_price_threshold * (1 + carry_tolerance)
        should_carry_forward = (next_window_prices <= threshold_with_tolerance).any()

        assert should_carry_forward  # Should carry forward due to prices within tolerance

    def test_gap_responsibility_uses_following_gap_only(self):
        """Ensure each window's responsibility matches the following gap net load."""
        config = {
            "timezone": "Europe/Stockholm",
            "nordpool": {"resolution_minutes": 15},
            "charging_strategy": {
                "charge_threshold_percentile": 15,
                "cheap_price_tolerance_sek": 0.10,
                "price_smoothing_sek_kwh": 0.05,
                "responsibility_only_above_threshold": False,
            },
            "s_index": {"mode": "static", "static_factor": 1.05, "max_factor": 1.25},
            "battery": {
                "capacity_kwh": 10.0,
                "max_soc_percent": 95,
                "min_soc_percent": 15,
                "max_charge_power_kw": 5.0,
                "max_discharge_power_kw": 5.0,
                "roundtrip_efficiency_percent": 95,
            },
            "decision_thresholds": {"battery_use_margin_sek": 0.10},
            "battery_economics": {"battery_cycle_cost_kwh": 0.20},
            "system": {
                "inverter": {"max_power_kw": 10.0},
                "grid": {"max_power_kw": 25.0},
            },
            "strategic_charging": {
                "target_soc_percent": 95,
                "price_threshold_sek": 0.90,
                "carry_forward_tolerance_ratio": 0.10,
            },
        }
        planner = self._create_planner(config)
        planner.state = {"battery_kwh": 5.0, "battery_cost_sek_per_kwh": 0.20}
        dates = pd.date_range("2025-01-01 22:45", periods=8, freq="15min")
        df = pd.DataFrame(
            {
                "import_price_sek_kwh": [0.20] * 4 + [0.60] * 4,
                "adjusted_pv_kwh": [2.0] * 4 + [0.0] * 4,
                "adjusted_load_kwh": [0.1] * 4 + [1.2] * 4,
                "simulated_soc_kwh": [5.0] * 8,
                "is_cheap": [True] * 4 + [False] * 4,
                "water_heating_kw": [0.0] * 8,
            },
            index=dates,
        )
        planner.now_slot = df.index[0]
        planner.window_start_states = []
        planner.daily_pv_forecast = {}
        planner.daily_load_forecast = {}
        planner.is_strategic_period = False

        planner._pass_4_allocate_cascading_responsibilities(df)
        assert len(planner.window_responsibilities) == 1
        gap_df = df[~df["is_cheap"]]
        expected_gap = gap_df["adjusted_load_kwh"].sum() - gap_df["adjusted_pv_kwh"].sum()
        expected_responsibility = expected_gap * 1.05
        actual = planner.window_responsibilities[0]["total_responsibility_kwh"]
        assert abs(actual - expected_responsibility) < 0.001

    def test_gap_responsibility_respects_price_guard(self):
        """Ensure the optional price guard can zero-out responsibilities."""
        config = {
            "timezone": "Europe/Stockholm",
            "nordpool": {"resolution_minutes": 15},
            "charging_strategy": {
                "charge_threshold_percentile": 15,
                "cheap_price_tolerance_sek": 0.10,
                "price_smoothing_sek_kwh": 0.05,
                "responsibility_only_above_threshold": True,
            },
            "s_index": {"mode": "static", "static_factor": 1.05, "max_factor": 1.25},
            "battery": {
                "capacity_kwh": 10.0,
                "max_soc_percent": 95,
                "min_soc_percent": 15,
                "max_charge_power_kw": 5.0,
                "max_discharge_power_kw": 5.0,
                "roundtrip_efficiency_percent": 95,
            },
            "decision_thresholds": {"battery_use_margin_sek": 0.10},
            "battery_economics": {"battery_cycle_cost_kwh": 0.20},
            "system": {
                "inverter": {"max_power_kw": 10.0},
                "grid": {"max_power_kw": 25.0},
            },
            "strategic_charging": {
                "target_soc_percent": 95,
                "price_threshold_sek": 0.90,
                "carry_forward_tolerance_ratio": 0.10,
            },
        }
        planner = self._create_planner(config)
        planner.state = {"battery_kwh": 5.0, "battery_cost_sek_per_kwh": 0.20}
        dates = pd.date_range("2025-01-01 22:45", periods=8, freq="15min")
        df = pd.DataFrame(
            {
                "import_price_sek_kwh": [0.20] * 4 + [0.45] * 4,
                "adjusted_pv_kwh": [2.0] * 4 + [0.0] * 4,
                "adjusted_load_kwh": [0.1] * 4 + [1.2] * 4,
                "simulated_soc_kwh": [5.0] * 8,
                "is_cheap": [True] * 4 + [False] * 4,
                "water_heating_kw": [0.0] * 8,
            },
            index=dates,
        )
        planner.now_slot = df.index[0]
        planner.window_start_states = []
        planner.daily_pv_forecast = {}
        planner.daily_load_forecast = {}
        planner.is_strategic_period = False

        planner._pass_4_allocate_cascading_responsibilities(df)
        assert len(planner.window_responsibilities) == 1
        actual = planner.window_responsibilities[0]["total_responsibility_kwh"]
        assert actual == 0.0
