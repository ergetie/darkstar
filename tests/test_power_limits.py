import math

import pandas as pd
import pytest

from planner import HeliosPlanner


class TestPowerLimits:
    """Validate charge/discharge rate limiting and export behaviour."""

    def setup_method(self):
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.timezone = "Europe/Stockholm"
        self.planner.config = {
            "arbitrage": {
                "enable_export": True,
                "export_fees_sek_per_kwh": 0.0,
                "export_profit_margin_sek": 0.05,
                "protective_soc_strategy": "gap_based",
                "fixed_protective_soc_percent": 15.0,
            },
            "learning": {"enable": False},
        }
        self.planner.battery_config = {
            "capacity_kwh": 10.0,
            "min_soc_percent": 15,
            "max_soc_percent": 95,
            "max_charge_power_kw": 5.0,
            "max_discharge_power_kw": 5.0,
            "roundtrip_efficiency_percent": 95.0,
        }
        self.planner.thresholds = {
            "battery_use_margin_sek": 0.10,
            "battery_water_margin_sek": 0.20,
        }
        self.planner.charging_strategy = {
            "charge_threshold_percentile": 15,
            "cheap_price_tolerance_sek": 0.10,
        }
        self.planner.strategic_charging = {}
        self.planner.water_heating_config = {"power_kw": 3.0}
        self.planner.learning_config = self.planner.config.get("learning", {})
        self.planner._learning_schema_initialized = False
        self.planner.window_responsibilities = []
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}

        self.planner.roundtrip_efficiency = 0.95
        efficiency_component = math.sqrt(self.planner.roundtrip_efficiency)
        self.planner.charge_efficiency = efficiency_component
        self.planner.discharge_efficiency = efficiency_component
        self.planner.cycle_cost = 0.20

    def test_pass3_respects_discharge_power_limit(self):
        """_pass_3 should clamp discharge to max_discharge_power_kw."""
        self.planner.state = {
            "battery_kwh": 8.0,
            "battery_cost_sek_per_kwh": 0.20,
        }

        dates = pd.date_range("2025-01-01", periods=1, freq="15min", tz="Europe/Stockholm")
        df = pd.DataFrame(
            {
                "adjusted_pv_kwh": [0.0],
                "adjusted_load_kwh": [5.0],
                "water_heating_kw": [0.0],
                "import_price_sek_kwh": [1.20],
                "is_cheap": [False],
            },
            index=dates,
        )

        result_df = self.planner._pass_3_simulate_baseline_depletion(df.copy())
        rate_limited_output = self.planner.battery_config["max_discharge_power_kw"] * 0.25
        expected_output_kwh = rate_limited_output
        expected_battery_use = self.planner._battery_energy_for_output(expected_output_kwh)
        expected_soc = pytest.approx(
            self.planner.state["battery_kwh"] - expected_battery_use, rel=1e-5
        )

        assert result_df["simulated_soc_kwh"].iloc[0] == expected_soc

    def test_battery_export_without_pv_surplus(self):
        """_pass_6 should allow exporting from battery when profitable even with no PV surplus."""
        self.planner.state = {
            "battery_kwh": 8.0,
            "battery_cost_sek_per_kwh": 0.20,
        }
        self.planner.config["arbitrage"]["export_percentile_threshold"] = 100
        self.planner.config["arbitrage"]["enable_peak_only_export"] = False
        self.planner.strategic_charging = {"target_soc_percent": 70}
        self.planner.window_responsibilities = []

        dates = pd.date_range("2025-01-01", periods=1, freq="15min", tz="Europe/Stockholm")
        df = pd.DataFrame(
            {
                "adjusted_pv_kwh": [0.0],
                "adjusted_load_kwh": [0.0],
                "water_heating_kw": [0.0],
                "charge_kw": [0.0],
                "import_price_sek_kwh": [0.20],
                "export_price_sek_kwh": [0.55],
                "is_cheap": [False],
            },
            index=dates,
        )

        result_df = self.planner._pass_6_finalize_schedule(df.copy())
        exported_kwh = result_df["export_kwh"].iloc[0]

        assert exported_kwh == pytest.approx(1.0, rel=1e-5)
        assert result_df["action"].iloc[0] == "Export"

        battery_energy_used = self.planner._battery_energy_for_output(exported_kwh)
        expected_soc = pytest.approx(
            self.planner.state["battery_kwh"] - battery_energy_used, rel=1e-5
        )
        assert result_df["projected_soc_kwh"].iloc[0] == expected_soc
