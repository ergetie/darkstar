import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.exceptions import PVForecastError
# We import from forecasts module. We will patch OpenMeteoSolarForecast where it is USED.
from backend.core.forecasts import (
    _get_forecast_data_async,
    _get_stored_openmeteo_pv_for_slots,
    get_forecast_data,
)


def _outage_config():
    return {
        "timezone": "UTC",
        "system": {
            "location": {"latitude": 59.3, "longitude": 18.1},
            "solar_arrays": [{"name": "Array 1", "azimuth": 180, "tilt": 35, "kwp": 10.0}],
        },
    }


def _slots(count: int, start: datetime | None = None):
    start = start or datetime(2024, 6, 21, 12, 0, tzinfo=UTC)
    return [{"start_time": start + timedelta(minutes=15 * i)} for i in range(count)]


class _FakeStore:
    def __init__(self, rows):
        self._rows = rows

    async def get_openmeteo_pv_baselines_range(self, start, end, forecast_version):
        return self._rows

    async def close(self):
        return None


def _stored_rows(entries):
    return [
        {"slot_start": ts.isoformat(), "openmeteo_pv_forecast_kwh": value} for ts, value in entries
    ]


class TestStoredFallbackHelper(unittest.IsolatedAsyncioTestCase):
    async def _run(self, rows, price_slots, known=None):
        with patch("backend.learning.store.LearningStore", return_value=_FakeStore(rows)):
            return await _get_stored_openmeteo_pv_for_slots(
                price_slots, {"timezone": "UTC"}, known
            )

    async def test_full_coverage_has_no_estimated_slots(self):
        slots = _slots(2)
        rows = _stored_rows([(slots[0]["start_time"], 0.5), (slots[1]["start_time"], 0.6)])
        values, daily, estimated = await self._run(rows, slots)
        assert values == [0.5, 0.6]
        assert estimated == []
        assert daily["2024-06-21"] == pytest.approx(1.1)

    async def test_partial_coverage_uses_same_time_of_day(self):
        slots = _slots(3)
        yesterday = datetime(2024, 6, 20, 12, 0, tzinfo=UTC)
        rows = _stored_rows(
            [
                (slots[0]["start_time"], 0.5),
                (slots[1]["start_time"], 0.6),
                (yesterday + timedelta(minutes=30), 0.9),
                (yesterday - timedelta(days=1) + timedelta(minutes=30), 0.1),
            ]
        )
        values, daily, estimated = await self._run(rows, slots)
        assert values == [0.5, 0.6, 0.9]
        assert estimated == [2]
        assert daily["2024-06-21"] == pytest.approx(2.0)

    async def test_gap_prefers_earlier_day_over_later_day(self):
        slots = _slots(1)
        rows = _stored_rows(
            [
                (datetime(2024, 6, 19, 12, 0, tzinfo=UTC), 0.3),
                (datetime(2024, 6, 22, 12, 0, tzinfo=UTC), 0.8),
            ]
        )
        values, _, estimated = await self._run(rows, slots)
        assert values == [0.3]
        assert estimated == [0]

    async def test_later_day_used_when_no_earlier_day(self):
        slots = _slots(1)
        rows = _stored_rows([(datetime(2024, 6, 22, 12, 0, tzinfo=UTC), 0.8)])
        values, _, estimated = await self._run(rows, slots)
        assert values == [0.8]
        assert estimated == [0]

    async def test_unfillable_slot_is_never_zero(self):
        slots = _slots(2)
        rows = _stored_rows([(slots[0]["start_time"], 0.5)])
        assert await self._run(rows, slots) is None

    async def test_no_stored_data_returns_none(self):
        assert await self._run([], _slots(2)) is None

    async def test_known_values_keep_value_and_missing_are_estimated(self):
        slots = _slots(2)
        rows = _stored_rows(
            [
                (slots[1]["start_time"], 0.7),  # exact stored value, still estimated
            ]
        )
        values, _, estimated = await self._run(rows, slots, known={0: 0.25})
        assert values == [0.25, 0.7]
        assert estimated == [1]


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
                past_days=1,
            )
            MockForecastClass.assert_any_call(
                latitude=59.3,
                longitude=18.1,
                declination=35.0,
                azimuth=-90.0,
                dc_kwp=5.0,
                past_days=1,
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
                new=AsyncMock(return_value=([0.5, 0.6], {"2024-06-21": 1.1}, [])),
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
        assert mock_record_error.call_args.kwargs["context"]["estimated_slots"] == 0
        assert [slot["openmeteo_pv_forecast_kwh"] for slot in result["slots"]] == [0.5, 0.6]

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

    async def test_outage_partial_coverage_marks_estimated_slots(self):
        config = _outage_config()
        price_slots = _slots(3)

        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass,
            patch(
                "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
                new=AsyncMock(return_value=([0.5, 0.6, 0.6], {"2024-06-21": 1.7}, [2])),
            ),
            patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
            patch("backend.health.record_forecast_error") as mock_record_error,
        ):
            MockForecastClass.side_effect = RuntimeError("api down")
            result = await _get_forecast_data_async(price_slots, config)

        slots = result["slots"]
        assert [s["pv_forecast_kwh"] for s in slots] == [0.5, 0.6, 0.6]
        # Estimated slot keeps its value for planning but is never a stored baseline.
        assert slots[2]["openmeteo_pv_forecast_kwh"] is None
        assert slots[2]["pv_estimated"] is True
        assert slots[0]["pv_estimated"] is False
        context = mock_record_error.call_args.kwargs["context"]
        assert context["estimated_slots"] == 1
        assert context["total_slots"] == 3

    async def test_empty_estimate_uses_stored_fallback(self):
        config = _outage_config()
        price_slots = _slots(2)
        empty_estimate = MagicMock()
        empty_estimate.watts = {}

        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass,
            patch(
                "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
                new=AsyncMock(return_value=([0.5, 0.6], {"2024-06-21": 1.1}, [])),
            ) as mock_stored,
            patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
            patch("backend.health.record_forecast_error"),
        ):
            instance = AsyncMock()
            instance.estimate.return_value = empty_estimate
            instance.__aenter__.return_value = instance
            instance.__aexit__.return_value = None
            MockForecastClass.return_value = instance
            result = await _get_forecast_data_async(price_slots, config)

        mock_stored.assert_awaited_once()
        assert [s["pv_forecast_kwh"] for s in result["slots"]] == [0.5, 0.6]

    async def test_missing_slot_in_successful_response_is_not_zero(self):
        config = _outage_config()
        price_slots = _slots(2)
        estimate = MagicMock()
        estimate.watts = {datetime(2024, 6, 21, 12, 0, tzinfo=UTC): 1000.0}

        with (
            patch("backend.core.forecasts.OpenMeteoSolarForecast") as MockForecastClass,
            patch(
                "backend.core.forecasts._get_stored_openmeteo_pv_for_slots",
                new=AsyncMock(return_value=([0.25, 0.4], {"2024-06-21": 0.65}, [1])),
            ) as mock_stored,
            patch("backend.core.ha_client.get_load_profile_from_ha", return_value=[0.5] * 96),
            patch("backend.health.record_forecast_error") as mock_record_error,
        ):
            instance = AsyncMock()
            instance.estimate.return_value = estimate
            instance.__aenter__.return_value = instance
            instance.__aexit__.return_value = None
            MockForecastClass.return_value = instance
            result = await _get_forecast_data_async(price_slots, config)

        assert mock_stored.call_args.args[2] == {0: 0.25}
        assert result["slots"][1]["pv_forecast_kwh"] == 0.4
        assert result["slots"][1]["openmeteo_pv_forecast_kwh"] is None
        assert result["slots"][0]["openmeteo_pv_forecast_kwh"] == 0.25
        assert mock_record_error.call_args.kwargs["context"]["estimated_slots"] == 1

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
