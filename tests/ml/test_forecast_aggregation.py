import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.exceptions import PVForecastError
# We import from forecasts module. We will patch OpenMeteoSolarForecast where it is USED.
from backend.core.forecasts import _get_forecast_data_async, get_forecast_data


class TestForecastAggregation(unittest.IsolatedAsyncioTestCase):
    async def test_multi_array_aggregation(self):
        print("\n--- Testing Multi-Array Forecast Aggregation ---")

        # 1. Setup mock config with 2 arrays
        config = {
            "timezone": "UTC",
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [
                    {"name": "Array 1", "azimuth": 180, "tilt": 35, "kwp": 10.0},
                    {"name": "Array 2", "azimuth": 90, "tilt": 35, "kwp": 5.0},
                ],
            },
        }

        # 2. Setup mock price slots (4 slots = 1 hour)
        price_slots = [
            {"start_time": datetime(2024, 6, 21, 12, 0, tzinfo=UTC)},
            {"start_time": datetime(2024, 6, 21, 12, 15, tzinfo=UTC)},
            {"start_time": datetime(2024, 6, 21, 12, 30, tzinfo=UTC)},
            {"start_time": datetime(2024, 6, 21, 12, 45, tzinfo=UTC)},
        ]

        # 3. Setup mock OpenMeteoSolarForecast estimate response
        mock_estimate_1 = MagicMock()
        mock_estimate_1.watts = {
            datetime(2024, 6, 21, 12, 0, tzinfo=UTC): 1000.0,
            datetime(2024, 6, 21, 12, 15, tzinfo=UTC): 1000.0,
            datetime(2024, 6, 21, 12, 30, tzinfo=UTC): 1000.0,
            datetime(2024, 6, 21, 12, 45, tzinfo=UTC): 1000.0,
        }
        mock_estimate_2 = MagicMock()
        mock_estimate_2.watts = {
            datetime(2024, 6, 21, 12, 0, tzinfo=UTC): 500.0,
            datetime(2024, 6, 21, 12, 15, tzinfo=UTC): 500.0,
            datetime(2024, 6, 21, 12, 30, tzinfo=UTC): 500.0,
            datetime(2024, 6, 21, 12, 45, tzinfo=UTC): 500.0,
        }

        # 4. Patch OpenMeteoSolarForecast inside inputs
        with patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass:
            # Configure one mock instance per array.
            mock_instance_1 = AsyncMock()
            mock_instance_1.estimate.return_value = mock_estimate_1
            mock_instance_1.__aenter__.return_value = mock_instance_1
            mock_instance_1.__aexit__.return_value = None
            mock_instance_2 = AsyncMock()
            mock_instance_2.estimate.return_value = mock_estimate_2
            mock_instance_2.__aenter__.return_value = mock_instance_2
            mock_instance_2.__aexit__.return_value = None
            MockForecastClass.side_effect = [mock_instance_1, mock_instance_2]

            # Mock get_load_profile_from_ha to avoid HA calls
            with patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96):
                # 5. Call the function
                result = await _get_forecast_data_async(price_slots, config)

            # 6. Verify constructor calls
            self.assertEqual(MockForecastClass.call_count, 2)
            MockForecastClass.assert_any_call(
                latitude=59.3,
                longitude=18.1,
                declination=35.0,
                azimuth=0.0,  # South = 0 for Open-Meteo
                dc_kwp=10.0,
            )
            MockForecastClass.assert_any_call(
                latitude=59.3,
                longitude=18.1,
                declination=35.0,
                azimuth=-90.0,
                dc_kwp=5.0,
            )
            print("✅ Correct per-array calls passed to OpenMeteoSolarForecast")

            # 7. Verify result aggregation
            # (1000 + 500) Watts * 0.25 hours = 375 Wh = 0.375 kWh per slot
            for slot in result["slots"]:
                self.assertEqual(slot["pv_forecast_kwh"], 0.375)
                self.assertEqual(slot["openmeteo_pv_forecast_kwh"], 0.375)

            print("✅ Forecast aggregation result correct (0.375 kWh per slot)")
            print("✅ Multi-array forecast integration verified!")

    async def test_outage_uses_stored_openmeteo_forecast(self):
        config = {
            "timezone": "UTC",
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "Array 1", "azimuth": 180, "tilt": 35, "kwp": 10.0}],
            },
        }
        price_slots = [
            {"start_time": datetime(2024, 6, 21, 12, 0, tzinfo=UTC)},
            {"start_time": datetime(2024, 6, 21, 12, 15, tzinfo=UTC)},
        ]

        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass,
            patch(
                "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
                new=AsyncMock(return_value=([0.5, 0.6], {"2024-06-21": 1.1})),
            ),
            patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
            patch("backend.health.record_forecast_error") as mock_record_error,
        ):
            MockForecastClass.side_effect = RuntimeError("api down")

            result = await _get_forecast_data_async(price_slots, config)

        assert [slot["pv_forecast_kwh"] for slot in result["slots"]] == [0.5, 0.6]
        assert result["daily_pv_forecast"]["2024-06-21"] == 1.1
        mock_record_error.assert_called_once()
        assert "using last known forecast" in str(mock_record_error.call_args.args[0])

    async def test_outage_without_stored_coverage_is_critical(self):
        config = {
            "timezone": "UTC",
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "Array 1", "azimuth": 180, "tilt": 35, "kwp": 10.0}],
            },
        }
        price_slots = [{"start_time": datetime(2024, 6, 21, 12, 0, tzinfo=UTC)}]

        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass,
            patch(
                "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
                new=AsyncMock(return_value=None),
            ),
            patch("backend.health.record_forecast_error") as mock_record_error,
        ):
            MockForecastClass.side_effect = RuntimeError("api down")

            with pytest.raises(PVForecastError):
                await _get_forecast_data_async(price_slots, config)

        mock_record_error.assert_called_once()
        assert isinstance(mock_record_error.call_args.args[0], PVForecastError)

    async def test_independent_aurora_load_pv_toggle_combinations(self):
        price_slots = [
            {"start_time": datetime(2024, 6, 21, 12, 0, tzinfo=UTC)},
            {"start_time": datetime(2024, 6, 21, 12, 15, tzinfo=UTC)},
        ]
        db_slots = [
            {"pv_forecast_kwh": 1.0, "openmeteo_pv_forecast_kwh": 0.6, "base_load_forecast_kwh": 2.0},
            {"pv_forecast_kwh": 1.1, "openmeteo_pv_forecast_kwh": 0.7, "base_load_forecast_kwh": 2.1},
        ]
        openmeteo_result = {
            "slots": [
                {"pv_forecast_kwh": 0.6, "openmeteo_pv_forecast_kwh": 0.6, "load_forecast_kwh": 0.4},
                {"pv_forecast_kwh": 0.7, "openmeteo_pv_forecast_kwh": 0.7, "load_forecast_kwh": 0.4},
            ],
            "daily_pv_forecast": {"2024-06-21": 1.3},
            "daily_load_forecast": {"2024-06-21": 0.8},
        }

        async def run_case(load_enabled: bool, pv_enabled: bool):
            config = {
                "timezone": "UTC",
                "forecasting": {
                    "active_forecast_version": "aurora",
                    "aurora_load_enabled": load_enabled,
                    "aurora_pv_enabled": pv_enabled,
                },
            }
            with (
                patch("backend.core.forecasts.build_db_forecast_for_slots", new=AsyncMock(return_value=db_slots)),
                patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=[])),
                patch("backend.core.forecasts._get_forecast_data_async", new=AsyncMock(return_value=openmeteo_result)),
                patch("backend.core.ha_client.get_load_profile_from_ha", new=AsyncMock(return_value=[0.4] * 96)),
            ):
                return await get_forecast_data(price_slots, config)

        both_on = await run_case(load_enabled=True, pv_enabled=True)
        assert both_on["slots"][0]["load_forecast_kwh"] == 2.0
        assert both_on["slots"][0]["pv_forecast_kwh"] == 1.0

        load_off = await run_case(load_enabled=False, pv_enabled=True)
        assert load_off["slots"][0]["load_forecast_kwh"] == 0.4
        assert load_off["slots"][0]["pv_forecast_kwh"] == 1.0

        pv_off = await run_case(load_enabled=True, pv_enabled=False)
        assert pv_off["slots"][0]["load_forecast_kwh"] == 2.0
        assert pv_off["slots"][0]["pv_forecast_kwh"] == 0.6
        assert pv_off["slots"][0]["openmeteo_pv_forecast_kwh"] == 0.6

        both_off = await run_case(load_enabled=False, pv_enabled=False)
        assert both_off["slots"][0]["load_forecast_kwh"] == 0.4
        assert both_off["slots"][0]["pv_forecast_kwh"] == 0.6

    async def test_aurora_returns_extended_slots_from_existing_records(self):
        price_slots = [
            {"start_time": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)},
            {"start_time": datetime(2024, 1, 1, 0, 15, tzinfo=UTC)},
        ]
        db_slots = [
            {"pv_forecast_kwh": 0.1, "base_load_forecast_kwh": 0.2},
            {"pv_forecast_kwh": 0.2, "base_load_forecast_kwh": 0.3},
        ]
        extended_records = []
        for idx in range(100):
            slot_start = datetime(2024, 1, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=15 * idx)
            extended_records.append(
                {
                    "slot_start": slot_start,
                    "final": {"pv_kwh": 0.05 + idx, "load_kwh": 0.1 + idx},
                    "base": {"pv_kwh": 0.04 + idx},
                    "probabilistic": {
                        "pv_p10": 0.01 + idx,
                        "pv_p90": 0.09 + idx,
                        "load_p10": 0.02 + idx,
                        "load_p90": 0.12 + idx,
                    },
                }
            )

        config = {
            "timezone": "UTC",
            "forecasting": {
                "active_forecast_version": "aurora",
                "aurora_load_enabled": True,
                "aurora_pv_enabled": True,
            },
        }

        with (
            patch("backend.core.forecasts.build_db_forecast_for_slots", new=AsyncMock(return_value=db_slots)),
            patch(
                "backend.core.forecasts.get_forecast_slots",
                new=AsyncMock(return_value=extended_records),
            ) as mock_extended_fetch,
            patch("backend.core.ha_client.get_load_profile_from_ha", new=AsyncMock(return_value=[0.4] * 96)),
        ):
            result = await get_forecast_data(price_slots, config)

        assert mock_extended_fetch.await_count == 1
        assert len(result["slots"]) == len(price_slots)
        assert len(result["extended_slots"]) == len(extended_records)
        assert result["extended_slots"][-1]["start_time"] >= price_slots[-1]["start_time"] + timedelta(
            hours=24
        )
        assert result["extended_slots"][0]["pv_forecast_kwh"] == 0.05
        assert result["extended_slots"][0]["load_forecast_kwh"] == 0.1
        assert result["extended_slots"][0]["pv_p10"] == 0.01
        assert result["extended_slots"][0]["pv_p90"] == 0.09
        assert result["extended_slots"][0]["load_p10"] == 0.02
        assert result["extended_slots"][0]["load_p90"] == 0.12

    async def test_aurora_extended_slots_use_load_fallback(self):
        price_slots = [{"start_time": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)}]
        extended_records = [
            {
                "slot_start": datetime(2024, 1, 1, 1, 0, tzinfo=UTC),
                "final": {"pv_kwh": 0.0, "load_kwh": 0.0},
                "base": {"pv_kwh": 0.0},
                "probabilistic": {},
            }
        ]
        config = {
            "timezone": "UTC",
            "forecasting": {
                "active_forecast_version": "aurora",
                "aurora_load_enabled": True,
                "aurora_pv_enabled": True,
            },
        }
        ha_profile = [float(idx) for idx in range(96)]

        with (
            patch("backend.core.forecasts.build_db_forecast_for_slots", new=AsyncMock(return_value=[])),
            patch("backend.core.forecasts.get_forecast_slots", new=AsyncMock(return_value=extended_records)),
            patch("backend.core.ha_client.get_load_profile_from_ha", new=AsyncMock(return_value=ha_profile)),
        ):
            result = await get_forecast_data(price_slots, config)

        assert result["extended_slots"][0]["load_forecast_kwh"] == ha_profile[4]
        assert result["daily_load_forecast"]["2024-01-01"] == ha_profile[4]


if __name__ == "__main__":
    unittest.main()
