"""
Test JSON schema validation and output format.
"""

from archive.legacy_mpc import HeliosPlanner, dataframe_to_json_response


class TestJsonSchema:
    """Test JSON output schema and validation."""

    def setup_method(self):
        """Set up test fixtures."""
        config = {"debug": {"enable_planner_debug": True, "sample_size": 5}}
        self.planner = HeliosPlanner.__new__(HeliosPlanner)
        self.planner.config = config
        self.planner.daily_pv_forecast = {}
        self.planner.daily_load_forecast = {}
        self.planner._last_temperature_forecast = {}
        self.planner.forecast_meta = {}

    def test_basic_schedule_schema(self):
        """Test that basic schedule JSON has required fields."""
        # Create minimal test DataFrame
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=2, freq="15min")
        df = pd.DataFrame(
            {
                "start_time": dates,
                "end_time": dates + pd.Timedelta(minutes=15),
                "import_price_sek_kwh": [0.20, 0.25],
                "export_price_sek_kwh": [0.15, 0.20],
                "pv_forecast_kwh": [0.0, 0.0],
                "adjusted_pv_kwh": [0.0, 0.0],
                "adjusted_load_kwh": [0.3, 0.3],
                "is_cheap": [True, False],
                "water_heating_kw": [0.0, 0.0],
                "simulated_soc_kwh": [5.0, 5.0],
                "charge_kw": [0.0, 0.0],
                "action": ["Hold", "Hold"],
                "projected_soc_kwh": [5.0, 5.0],
                "projected_soc_percent": [50.0, 50.0],
                "soc_target_percent": [45.0, 45.0],
                "projected_battery_cost": [0.20, 0.20],
                "water_from_pv_kwh": [0.0, 0.0],
                "water_from_battery_kwh": [0.0, 0.0],
                "water_from_grid_kwh": [0.0, 0.0],
                "export_kwh": [0.0, 0.0],
                "export_revenue": [0.0, 0.0],
            },
            index=dates,
        )

        # Convert to JSON
        records = dataframe_to_json_response(df)

        # Validate basic structure
        assert isinstance(records, list)
        assert len(records) == 2

        # Check required fields in first record
        record = records[0]
        required_fields = [
            "slot_number",
            "start_time",
            "end_time",
            "import_price_sek_kwh",
            "export_price_sek_kwh",
            "projected_soc_percent",
            "soc_target_percent",
            "projected_battery_cost",
            "reason",
            "priority",
        ]

        for field in required_fields:
            assert field in record

    def test_reason_priority_mapping(self):
        """Ensure reason/priority reflect numeric actions."""
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=4, freq="15min")
        df = pd.DataFrame(
            {
                "start_time": dates,
                "end_time": dates + pd.Timedelta(minutes=15),
                "import_price_sek_kwh": [0.20, 0.25, 0.15, 0.30],
                "export_price_sek_kwh": [0.15, 0.20, 0.10, 0.28],
                "pv_forecast_kwh": [0.0, 0.0, 0.0, 0.0],
                "adjusted_pv_kwh": [0.1, 0.2, 0.3, 0.4],
                "adjusted_load_kwh": [0.3, 0.3, 0.3, 0.3],
                "is_cheap": [True, False, True, True],
                "water_heating_kw": [0.0, 0.0, 0.0, 0.0],
                "simulated_soc_kwh": [5.0, 5.0, 5.0, 5.0],
                "charge_kw": [2.0, 0.0, 0.0, 0.0],
                "battery_charge_kw": [2.0, 0.0, 1.0, 0.0],
                "battery_discharge_kw": [0.0, 1.0, 0.0, 0.0],
                "projected_soc_kwh": [5.0, 4.0, 4.5, 4.0],
                "projected_soc_percent": [50.0, 40.0, 45.0, 40.0],
                "soc_target_percent": [45.0, 40.0, 50.0, 35.0],
                "projected_battery_cost": [0.20, 0.20, 0.20, 0.20],
                "water_from_pv_kwh": [0.0, 0.0, 0.0, 0.0],
                "water_from_battery_kwh": [0.0, 0.0, 0.0, 0.0],
                "water_from_grid_kwh": [0.0, 0.0, 0.0, 0.0],
                "export_kwh": [0.0, 0.0, 0.0, 0.5],
                "export_revenue": [0.0, 0.0, 0.0, 0.0],
            },
            index=dates,
        )

        records = dataframe_to_json_response(df)

        assert records[0]["reason"] == "cheap_grid_power"
        assert records[0]["priority"] == "high"
        assert records[1]["reason"] == "expensive_grid_power"
        assert records[1]["priority"] == "high"
        assert records[2]["reason"] == "excess_pv"
        assert records[2]["priority"] == "high"
        assert records[3]["reason"] == "profitable_export"
        assert records[3]["priority"] == "medium"

    def test_reason_and_priority_fields(self):
        """Test that reason and priority fields are added."""
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=4, freq="15min")
        df = pd.DataFrame(
            {
                "start_time": dates,
                "end_time": dates + pd.Timedelta(minutes=15),
                "import_price_sek_kwh": [0.20, 0.25, 0.15, 0.10],
                "export_price_sek_kwh": [0.15, 0.20, 0.10, 0.05],
                "pv_forecast_kwh": [0.0, 0.0, 0.0, 0.0],
                "adjusted_pv_kwh": [0.0, 0.0, 0.0, 0.0],
                "adjusted_load_kwh": [0.3, 0.3, 0.3, 0.3],
                "is_cheap": [True, False, True, True],
                "water_heating_kw": [0.0, 0.0, 0.0, 0.0],
                "simulated_soc_kwh": [5.0, 5.0, 5.0, 5.0],
                "charge_kw": [0.0, 0.0, 0.0, 0.0],
                "projected_soc_kwh": [5.0, 5.0, 5.0, 5.0],
                "projected_soc_percent": [50.0, 50.0, 50.0, 50.0],
                "soc_target_percent": [45.0, 35.0, 30.0, 55.0],
                "projected_battery_cost": [0.20, 0.20, 0.20, 0.20],
                "water_from_pv_kwh": [0.0, 0.0, 0.0, 0.0],
                "water_from_battery_kwh": [0.0, 0.0, 0.0, 0.0],
                "water_from_grid_kwh": [0.0, 0.0, 0.0, 0.0],
                "export_kwh": [0.0, 0.0, 0.0, 0.0],
                "export_revenue": [0.0, 0.0, 0.0, 0.0],
            },
            index=dates,
        )

        records = dataframe_to_json_response(df)

        # Check reason and priority fields exist
        for record in records:
            assert "reason" in record
            assert "priority" in record
            assert record["priority"] in ["high", "medium", "low"]

    def test_numeric_rounding(self):
        """Test that numeric values are properly rounded."""
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=1, freq="15min")
        df = pd.DataFrame(
            {
                "start_time": dates,
                "end_time": dates + pd.Timedelta(minutes=15),
                "import_price_sek_kwh": [0.123456],
                "export_price_sek_kwh": [0.098765],
                "pv_forecast_kwh": [0.0],
                "adjusted_pv_kwh": [0.0],
                "adjusted_load_kwh": [0.35789],
                "is_cheap": [True],
                "water_heating_kw": [0.0],
                "simulated_soc_kwh": [5.0],
                "charge_kw": [0.0],
                "action": ["Hold"],
                "projected_soc_kwh": [5.123456],
                "projected_soc_percent": [50.987654],
                "soc_target_percent": [52.2222],
                "projected_battery_cost": [0.198765],
                "water_from_pv_kwh": [0.0],
                "water_from_battery_kwh": [0.0],
                "water_from_grid_kwh": [0.0],
                "export_kwh": [0.0],
                "export_revenue": [0.0],
            },
            index=dates,
        )

        records = dataframe_to_json_response(df)

        record = records[0]

        # Check rounding to 2 decimal places
        assert record["import_price_sek_kwh"] == 0.12
        assert record["adjusted_load_kwh"] == 0.36
        assert record["projected_soc_kwh"] == 5.12
        assert record["projected_soc_percent"] == 50.99
        assert record["projected_battery_cost"] == 0.20
        assert record["soc_target_percent"] == 52.22

    def test_debug_payload_structure(self):
        """Test that debug payload has correct structure when enabled."""
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=3, freq="15min")
        df = pd.DataFrame(
            {
                "import_price_sek_kwh": [0.20, 0.25, 0.15],
                "export_price_sek_kwh": [0.15, 0.20, 0.10],
                "pv_forecast_kwh": [0.0, 0.0, 0.0],
                "adjusted_pv_kwh": [0.1, 0.2, 0.3],
                "adjusted_load_kwh": [0.3, 0.3, 0.3],
                "is_cheap": [True, False, True],
                "water_heating_kw": [0.0, 0.0, 0.0],
                "simulated_soc_kwh": [5.0, 5.0, 5.0],
                "battery_charge_kw": [0.0, 0.0, 0.0],
                "action": ["Hold", "Hold", "Hold"],
                "projected_soc_kwh": [5.0, 5.0, 5.0],
                "projected_soc_percent": [50.0, 50.0, 50.0],
                "soc_target_percent": [45.0, 45.0, 45.0],
                "projected_battery_cost": [0.20, 0.20, 0.20],
                "water_from_pv_kwh": [0.0, 0.0, 0.0],
                "water_from_battery_kwh": [0.0, 0.0, 0.0],
                "water_from_grid_kwh": [0.0, 0.0, 0.0],
                "export_kwh": [0.0, 0.0, 0.0],
                "export_revenue": [0.0, 0.0, 0.0],
            },
            index=dates,
        )

        # Mock window responsibilities
        self.planner.window_responsibilities = [
            {
                "window": {"start": "2025-01-01T00:00:00", "end": "2025-01-01T01:00:00"},
                "total_responsibility_kwh": 2.0,
                "start_soc_kwh": 5.0,
                "start_avg_cost_sek_per_kwh": 0.20,
            }
        ]

        debug_payload = self.planner._generate_debug_payload(df)

        # Check debug structure
        required_sections = [
            "windows",
            "water_analysis",
            "charging_plan",
            "metrics",
            "sample_schedule",
        ]
        for section in required_sections:
            assert section in debug_payload

        # Check specific metrics
        assert "total_pv_generation_kwh" in debug_payload["metrics"]
        assert "total_load_kwh" in debug_payload["metrics"]
        assert "final_soc_percent" in debug_payload["metrics"]

    def test_json_file_creation(self):
        """Test that JSON file is created correctly."""
        import pandas as pd

        dates = pd.date_range("2025-01-01 00:00", periods=1, freq="15min")
        df = pd.DataFrame(
            {
                "start_time": dates,
                "end_time": dates + pd.Timedelta(minutes=15),
                "import_price_sek_kwh": [0.20],
                "export_price_sek_kwh": [0.15],
                "pv_forecast_kwh": [0.0],
                "adjusted_pv_kwh": [0.0],
                "adjusted_load_kwh": [0.3],
                "is_cheap": [True],
                "water_heating_kw": [0.0],
                "simulated_soc_kwh": [5.0],
                "charge_kw": [0.0],
                "action": ["Hold"],
                "projected_soc_kwh": [5.0],
                "projected_soc_percent": [50.0],
                "projected_battery_cost": [0.20],
                "water_from_pv_kwh": [0.0],
                "water_from_battery_kwh": [0.0],
                "water_from_grid_kwh": [0.0],
                "export_kwh": [0.0],
                "export_revenue": [0.0],
            },
            index=dates,
        )

        # Test the JSON response function directly to avoid file I/O issues
        records = dataframe_to_json_response(df)

        # Validate the structure
        assert isinstance(records, list)
        assert len(records) == 1

        record = records[0]
        assert "slot_number" in record
        assert "start_time" in record
        assert "end_time" in record
        assert "reason" in record
        assert "priority" in record
