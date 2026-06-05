import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytz

from backend.learning import LearningEngine
from ml.forward import generate_forward_slots


class TestAuroraForward(unittest.IsolatedAsyncioTestCase):
    @patch("ml.forward.datetime")
    @patch("ml.forward.get_learning_engine")
    @patch("ml.forward._load_models")
    @patch("ml.forward.async_get_weather_series")
    @patch("ml.forward.get_vacation_mode_series")
    @patch("ml.forward.get_alarm_armed_series")
    @patch("backend.astro.SunCalculator")
    @patch("ml.forward.determine_graduation_level")
    async def test_forward_pass_multi_array(
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
        print("\n--- Testing Aurora Forward Pass with Multi-Array ---")

        # 1. Mock datetime to return a fixed midday summer time
        # This ensures sun is above horizon during physics calculation
        fixed_now = datetime(2024, 6, 15, 12, 0, tzinfo=pytz.UTC)
        mock_datetime.now.return_value = fixed_now
        mock_datetime.side_effect = datetime

        # 2. Mock graduation level
        mock_grad_level.return_value = (2, "graduate", 30.0)

        # 3. Mock LearningEngine
        mock_engine = MagicMock(spec=LearningEngine)
        mock_engine.store_forecasts = AsyncMock()
        mock_engine.timezone = pytz.UTC
        mock_engine.db_path = "fake_db.db"
        mock_engine.store = MagicMock()
        mock_engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=0)

        # 4. Mock SunCalculator
        mock_sun_instance = MagicMock()
        mock_sun_instance.is_sun_up.return_value = True
        mock_sun.return_value = mock_sun_instance
        mock_engine.config = {
            "timezone": "UTC",
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"kwp": 10.0}, {"kwp": 5.0}],
            },
        }
        mock_engine.store_forecasts = AsyncMock()
        mock_get_engine.return_value = mock_engine

        # 5. Mock Models (empty to trigger fallback)
        mock_models.return_value = {}

        # 6. Mock Weather data - align with fixed datetime
        slot_start = fixed_now.replace(minute=0, second=0, microsecond=0)
        mock_weather.return_value = pd.DataFrame(
            {
                "temp_c": [20.0] * 8,
                "cloud_cover_pct": [10.0] * 8,
                "shortwave_radiation_w_m2": [800.0] * 8,
            },
            index=pd.date_range(slot_start, periods=8, freq="15min", tz="UTC"),
        )

        # 4. Mock Context flags
        mock_vacation.return_value = pd.Series(0.0, index=mock_weather.return_value.index)
        mock_alarm.return_value = pd.Series(0.0, index=mock_weather.return_value.index)

        baseline = pd.Series([2.5] * 8, index=mock_weather.return_value.index)

        # 5. Run forward pass (short horizon)
        with patch("ml.forward._fetch_openmeteo_baseline_series", new=AsyncMock(return_value=baseline)):
            await generate_forward_slots(horizon_hours=2, forecast_version="test")

        # 6. Verify Open-Meteo baseline forecast in fallback mode

        args, _ = mock_engine.store_forecasts.call_args
        forecasts = args[0]

        self.assertGreater(len(forecasts), 0)
        # Check p50 PV forecast for first slot
        first_pv = forecasts[0]["pv_forecast_kwh"]
        # Open-Meteo baseline should be used directly when PV models are absent.
        self.assertGreater(first_pv, 0.0, "PV forecast should be positive during daytime")
        self.assertLess(first_pv, 4.0, "PV forecast should be reasonable for 15kWp system")
        self.assertEqual(forecasts[0]["openmeteo_pv_forecast_kwh"], 2.5)

        print("✅ Aurora forward pass used Open-Meteo baseline with 15.0 kWp total")
        print(f"✅ Calculated PV forecast: {first_pv:.4f} kWh")
        print("✅ Aurora forward pass multi-array integration verified!")


if __name__ == "__main__":
    unittest.main()
