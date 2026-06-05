from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytz

from backend.learning import LearningEngine
from backend.learning.pv_openmeteo_backfill import backfill_openmeteo_pv_baselines
from ml.forward import _pv_personalization_weight, generate_forward_slots


@pytest.mark.asyncio
async def test_pv_personalization_weight_scales_with_paired_days():
    engine = MagicMock()
    engine.config = {"forecasting": {"pv_personalization_ramp_days": 10}}
    engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=4)

    weight, days, ramp_days = await _pv_personalization_weight(engine)

    assert weight == 0.4
    assert days == 4
    assert ramp_days == 10


@pytest.mark.asyncio
async def test_pv_personalization_weight_caps_at_full():
    engine = MagicMock()
    engine.config = {"forecasting": {"pv_personalization_ramp_days": 10}}
    engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=20)

    weight, days, ramp_days = await _pv_personalization_weight(engine)

    assert weight == 1.0
    assert days == 20
    assert ramp_days == 10


@pytest.mark.asyncio
async def test_backfill_skips_new_install_without_production_history():
    engine = MagicMock()
    engine.store.get_pv_slots_missing_openmeteo_baseline = AsyncMock(return_value=set())
    engine.store_openmeteo_pv_baselines = AsyncMock()

    count = await backfill_openmeteo_pv_baselines(engine, days=28)

    assert count == 0
    engine.store_openmeteo_pv_baselines.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_skips_fetch_when_no_missing_baseline_slots():
    engine = MagicMock()
    engine.store.get_pv_slots_missing_openmeteo_baseline = AsyncMock(return_value=set())
    engine.store_openmeteo_pv_baselines = AsyncMock()

    with patch(
        "backend.learning.pv_openmeteo_backfill.fetch_historical_openmeteo_pv_baselines",
        new=AsyncMock(),
    ) as fetch:
        count = await backfill_openmeteo_pv_baselines(engine, days=28)

    assert count == 0
    fetch.assert_not_called()
    engine.store_openmeteo_pv_baselines.assert_not_called()


@pytest.mark.asyncio
async def test_backfill_filters_to_missing_actual_production_slots():
    tz = pytz.timezone("UTC")
    engine = MagicMock()
    engine.timezone = tz
    engine.config = {"timezone": "UTC"}
    engine.store.get_pv_slots_missing_openmeteo_baseline = AsyncMock(
        return_value={tz.localize(datetime(2026, 6, 1, 12, 0)).isoformat()}
    )
    engine.store_openmeteo_pv_baselines = AsyncMock()
    rows = [
        {"slot_start": tz.localize(datetime(2026, 6, 1, 12, 0)), "openmeteo_pv_forecast_kwh": 1.0},
        {"slot_start": tz.localize(datetime(2026, 6, 1, 12, 15)), "openmeteo_pv_forecast_kwh": 2.0},
    ]

    with patch(
        "backend.learning.pv_openmeteo_backfill.fetch_historical_openmeteo_pv_baselines",
        new=AsyncMock(return_value=rows),
    ):
        count = await backfill_openmeteo_pv_baselines(engine, days=28)

    assert count == 1
    stored_rows = engine.store_openmeteo_pv_baselines.call_args.args[0]
    assert stored_rows == [rows[0]]


@pytest.mark.asyncio
async def test_forward_ramp_cold_partial_full_respects_bound():
    tz = pytz.UTC
    fixed_now = tz.localize(datetime(2026, 6, 4, 12, 0))
    weather = pd.DataFrame(
        {
            "temp_c": [20.0],
            "cloud_cover_pct": [10.0],
            "shortwave_radiation_w_m2": [800.0],
        },
        index=pd.date_range(fixed_now, periods=1, freq="15min", tz="UTC"),
    )
    baseline = pd.Series([1.0], index=weather.index)

    import lightgbm as lgb

    model = MagicMock(spec=lgb.Booster)
    model.predict.return_value = np.array([10.0])

    async def run_with_days(days: int) -> float:
        engine = MagicMock(spec=LearningEngine)
        engine.store = MagicMock()
        engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=days)
        engine.store_forecasts = AsyncMock()
        engine.timezone = tz
        engine.db_path = "data/test.db"
        engine.config = {
            "timezone": "UTC",
            "forecasting": {
                "pv_personalization_ramp_days": 10,
                "pv_residual_bound_fraction": 0.25,
                "pv_ceiling_efficiency": 0.95,
            },
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "South", "kwp": 10.0, "tilt": 30.0, "azimuth": 180.0}],
            },
        }

        with (
            patch("ml.forward.datetime") as mock_datetime,
            patch("ml.forward.get_learning_engine", return_value=engine),
            patch("ml.forward._load_models", return_value={"pv_p50": model}),
            patch("ml.forward.async_get_weather_series", new=AsyncMock(return_value=weather)),
            patch("ml.forward.get_vacation_mode_series", return_value=pd.Series(0.0, index=weather.index)),
            patch("ml.forward.get_alarm_armed_series", return_value=pd.Series(0.0, index=weather.index)),
            patch("backend.astro.SunCalculator") as mock_sun,
            patch("ml.forward._fetch_openmeteo_baseline_series", new=AsyncMock(return_value=baseline)),
        ):
            mock_datetime.now.return_value = fixed_now
            mock_datetime.side_effect = datetime
            mock_sun.return_value.is_sun_up.return_value = True
            await generate_forward_slots(horizon_hours=0.25, forecast_version="test")

        forecasts = engine.store_forecasts.call_args.args[0]
        return forecasts[0]["pv_forecast_kwh"]

    assert await run_with_days(0) == pytest.approx(1.0)
    assert await run_with_days(5) == pytest.approx(1.125)
    assert await run_with_days(10) == pytest.approx(1.25)
