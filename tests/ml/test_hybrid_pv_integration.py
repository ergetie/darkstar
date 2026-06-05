"""
Integration tests for physics + ML composition in hybrid PV forecasting.
"""

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytz

from backend.learning import LearningEngine


class TestHybridPVIntegration(unittest.IsolatedAsyncioTestCase):
    """Integration tests for physics + ML residual composition."""

    @patch("ml.forward.datetime")
    @patch("ml.forward.get_learning_engine")
    @patch("ml.forward._load_models")
    @patch("ml.forward.async_get_weather_series")
    @patch("ml.forward.get_vacation_mode_series")
    @patch("ml.forward.get_alarm_armed_series")
    @patch("backend.astro.SunCalculator")
    @patch("ml.forward.determine_graduation_level")
    async def test_hybrid_physics_plus_ml_residual(
        self,
        mock_grad_level,
        mock_sun,
        mock_alarm,
        mock_vacation,
        mock_weather,
        mock_models,
        mock_get_engine,
        mock_datetime,
    ):
        """Test that hybrid mode correctly composes physics + ML residual."""
        from ml.forward import generate_forward_slots

        # Mock datetime to return a fixed midday summer time
        # This ensures sun is above horizon during physics calculation
        fixed_now = datetime(2024, 6, 15, 12, 0, tzinfo=pytz.UTC)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = datetime

        # Mock graduation level
        mock_grad_level.return_value = (2, "graduate", 30.0)

        # Mock LearningEngine
        mock_engine = MagicMock(spec=LearningEngine)
        mock_engine.store_forecasts = AsyncMock()
        mock_engine.timezone = pytz.UTC
        mock_engine.db_path = "data/test.db"
        mock_engine.store = MagicMock()
        mock_engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=14)
        mock_engine.config = {
            "timezone": "UTC",
            "forecasting": {"pv_personalization_ramp_days": 14},
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}],
            },
        }
        mock_get_engine.return_value = mock_engine

        # Mock SunCalculator
        mock_sun_instance = MagicMock()
        mock_sun_instance.is_sun_up.return_value = True
        mock_sun.return_value = mock_sun_instance

        # Mock weather - align with fixed datetime
        slot_start = fixed_now.replace(minute=0, second=0, microsecond=0)
        mock_weather.return_value = pd.DataFrame(
            {
                "temp_c": [20.0] * 4,
                "cloud_cover_pct": [10.0] * 4,
                "shortwave_radiation_w_m2": [800.0] * 4,
            },
            index=pd.date_range(slot_start, periods=4, freq="15min", tz="UTC"),
        )

        mock_vacation.return_value = pd.Series(0.0, index=mock_weather.return_value.index)
        mock_alarm.return_value = pd.Series(0.0, index=mock_weather.return_value.index)

        # Mock ML models - predict small negative residual (shadows)
        import lightgbm as lgb

        mock_pv_model = MagicMock(spec=lgb.Booster)
        mock_pv_model.predict.return_value = np.array([-0.05, -0.08, -0.06, -0.04])

        mock_models.return_value = {
            "pv_p10": mock_pv_model,
            "pv_p50": mock_pv_model,
            "pv_p90": mock_pv_model,
        }

        baseline = pd.Series([1.0] * 4, index=mock_weather.return_value.index)

        # Run forward pass
        with patch("ml.forward._fetch_openmeteo_baseline_series", new=AsyncMock(return_value=baseline)):
            await generate_forward_slots(horizon_hours=1, forecast_version="test")

        # Verify forecasts were stored
        args, _ = mock_engine.store_forecasts.call_args
        forecasts = args[0]

        self.assertGreater(len(forecasts), 0)

        # Each forecast should have Open-Meteo baseline plus the bounded residual.
        for fc in forecasts:
            pv = fc["pv_forecast_kwh"]
            self.assertGreater(pv, 0, "PV forecast should be positive during daytime")
            self.assertLess(pv, fc["openmeteo_pv_forecast_kwh"])

    @patch("ml.forward.datetime")
    @patch("ml.forward.get_learning_engine")
    @patch("ml.forward._load_models")
    @patch("ml.forward.async_get_weather_series")
    @patch("ml.forward.get_vacation_mode_series")
    @patch("ml.forward.get_alarm_armed_series")
    @patch("backend.astro.SunCalculator")
    @patch("ml.forward.determine_graduation_level")
    async def test_physics_only_mode(
        self,
        mock_grad_level,
        mock_sun,
        mock_alarm,
        mock_vacation,
        mock_weather,
        mock_models,
        mock_get_engine,
        mock_datetime,
    ):
        """Test that physics-only mode works when no ML models available."""
        from ml.forward import generate_forward_slots

        # Mock datetime to return a fixed midday summer time
        # This ensures sun is above horizon during physics calculation
        fixed_now = datetime(2024, 6, 15, 12, 0, tzinfo=pytz.UTC)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = datetime

        mock_grad_level.return_value = (2, "graduate", 30.0)

        mock_engine = MagicMock(spec=LearningEngine)
        mock_engine.store_forecasts = AsyncMock()
        mock_engine.timezone = pytz.UTC
        mock_engine.db_path = "data/test.db"
        mock_engine.store = MagicMock()
        mock_engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=0)
        mock_engine.config = {
            "timezone": "UTC",
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}],
            },
        }
        mock_get_engine.return_value = mock_engine

        mock_sun_instance = MagicMock()
        mock_sun_instance.is_sun_up.return_value = True
        mock_sun.return_value = mock_sun_instance

        # Mock weather - align with fixed datetime
        slot_start = fixed_now.replace(minute=0, second=0, microsecond=0)

        mock_weather.return_value = pd.DataFrame(
            {
                "temp_c": [20.0] * 4,
                "cloud_cover_pct": [10.0] * 4,
                "shortwave_radiation_w_m2": [800.0] * 4,
            },
            index=pd.date_range(slot_start, periods=4, freq="15min", tz="UTC"),
        )

        mock_vacation.return_value = pd.Series(0.0, index=mock_weather.return_value.index)
        mock_alarm.return_value = pd.Series(0.0, index=mock_weather.return_value.index)

        # No ML models
        mock_models.return_value = {}

        baseline = pd.Series([1.0] * 4, index=mock_weather.return_value.index)

        with patch("ml.forward._fetch_openmeteo_baseline_series", new=AsyncMock(return_value=baseline)):
            await generate_forward_slots(horizon_hours=1, forecast_version="test")

        args, _ = mock_engine.store_forecasts.call_args
        forecasts = args[0]

        self.assertGreater(len(forecasts), 0)

        # Baseline-only should still give reasonable forecasts
        for fc in forecasts:
            pv = fc["pv_forecast_kwh"]
            self.assertGreater(pv, 0, "Baseline-only should produce positive PV during daytime")
            self.assertEqual(fc["openmeteo_pv_forecast_kwh"], 1.0)


class TestPhysicsCalculationIntegration(unittest.TestCase):
    """Tests for physics calculation integration."""

    def test_physics_matches_expected_range(self):
        """Test that physics calculation produces reasonable values."""
        from ml.weather import calculate_physics_pv

        tz = pytz.timezone("Europe/Stockholm")
        slot_start = tz.localize(datetime(2024, 6, 21, 12, 0))

        # Test with various radiation levels - physics should increase with radiation
        test_cases = [
            (200.0, 0.0, 1.0),  # Low radiation
            (500.0, 0.0, 2.0),  # Medium radiation
            (800.0, 0.0, 3.0),  # High radiation
            (1000.0, 0.0, 4.0),  # Very high radiation
        ]

        solar_arrays = [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        for radiation, min_expected, max_expected in test_cases:
            physics_kwh, _per_array = calculate_physics_pv(
                radiation_w_m2=radiation,
                solar_arrays=solar_arrays,
                slot_start=slot_start,
                latitude=59.3,
                longitude=18.1,
            )

            self.assertIsNotNone(
                physics_kwh, f"Physics should not be None for radiation={radiation}"
            )
            self.assertGreater(
                physics_kwh, min_expected, f"Physics too low for radiation={radiation}"
            )
            self.assertLess(
                physics_kwh, max_expected, f"Physics too high for radiation={radiation}"
            )

    def test_physics_different_array_orientations(self):
        """Test that different array orientations produce different results."""
        from ml.weather import calculate_physics_pv

        tz = pytz.timezone("Europe/Stockholm")
        slot_start = tz.localize(datetime(2024, 6, 21, 10, 0))  # Morning

        # East-facing vs West-facing should differ
        east_array = [{"name": "East", "kwp": 5.0, "tilt": 30.0, "azimuth": 90.0}]
        west_array = [{"name": "West", "kwp": 5.0, "tilt": 30.0, "azimuth": 270.0}]

        physics_east, _ = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=east_array,
            slot_start=slot_start,
            latitude=59.3,
            longitude=18.1,
        )

        physics_west, _ = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=west_array,
            slot_start=slot_start,
            latitude=59.3,
            longitude=18.1,
        )

        self.assertIsNotNone(physics_east)
        self.assertIsNotNone(physics_west)
        # Different orientations should produce different results
        self.assertNotEqual(
            round(physics_east, 3),
            round(physics_west, 3),
            "Different orientations should produce different results",
        )


if __name__ == "__main__":
    unittest.main()
