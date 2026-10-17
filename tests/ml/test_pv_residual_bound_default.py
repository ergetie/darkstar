"""PV residual bound default (1.0), zero handling and raw residual persistence."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
import pytz

from backend.learning import LearningEngine
from ml.forward import _hybrid_pv_values, _pv_tuning_config, generate_forward_slots


@pytest.mark.parametrize(
    ("forecasting", "expected"),
    [
        ({}, 1.0),
        ({"pv_residual_bound_fraction": None}, 1.0),
        ({"pv_residual_bound_fraction": 0}, 0.0),
        ({"pv_residual_bound_fraction": 0.5}, 0.5),
        ({"pv_residual_bound_fraction": 2.0}, 2.0),
        ({"pv_residual_bound_fraction": -0.1}, 1.0),
        ({"pv_residual_bound_fraction": float("nan")}, 1.0),
        ({"pv_residual_bound_fraction": float("inf")}, 1.0),
        ({"pv_residual_bound_fraction": "abc"}, 1.0),
        ({"pv_residual_bound_fraction": True}, 1.0),
    ],
)
def test_bound_fraction_parsing(forecasting: dict[str, Any], expected: float) -> None:
    assert _pv_tuning_config({"forecasting": forecasting})[0] == expected


def test_missing_forecasting_section_uses_default() -> None:
    assert _pv_tuning_config({})[0] == 1.0


def test_config_default_yaml_is_one() -> None:
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    cfg = yaml.safe_load((root / "config.default.yaml").read_text(encoding="utf-8"))
    assert cfg["forecasting"]["pv_residual_bound_fraction"] == 1.0


def _run_forward(
    bound: Any, raw: list[float], baseline: list[float], with_model: bool = True
) -> list[dict[str, Any]]:
    import asyncio

    tz = pytz.UTC
    fixed_now = tz.localize(datetime(2026, 6, 4, 12, 0))
    n = len(raw)
    weather = pd.DataFrame(
        {
            "temp_c": [20.0] * n,
            "cloud_cover_pct": [10.0] * n,
            "shortwave_radiation_w_m2": [800.0] * n,
        },
        index=pd.date_range(fixed_now, periods=n, freq="15min", tz="UTC"),
    )
    baseline_series = pd.Series(baseline, index=weather.index)
    model = MagicMock(spec=lgb.Booster)
    model.predict.return_value = np.array(raw)
    forecasting: dict[str, Any] = {
        "pv_personalization_ramp_days": 10,
        "pv_ceiling_efficiency": 0.95,
    }
    if bound != "missing":
        forecasting["pv_residual_bound_fraction"] = bound

    async def run() -> list[dict[str, Any]]:
        engine = MagicMock(spec=LearningEngine)
        engine.store = MagicMock()
        engine.store.count_paired_openmeteo_pv_days = AsyncMock(return_value=10)
        engine.store_forecasts = AsyncMock()
        engine.timezone = tz
        engine.db_path = "data/test.db"
        engine.config = {
            "timezone": "UTC",
            "forecasting": forecasting,
            "system": {
                "location": {"latitude": 59.3, "longitude": 18.1},
                "solar_arrays": [{"name": "S", "kwp": 10.0, "tilt": 30.0, "azimuth": 180.0}],
            },
        }
        with (
            patch("ml.forward.datetime") as mock_datetime,
            patch("ml.forward.get_learning_engine", return_value=engine),
            patch("ml.forward._load_models", return_value={"pv_p50": model} if with_model else {}),
            patch("ml.forward.async_get_weather_series", new=AsyncMock(return_value=weather)),
            patch(
                "ml.forward.get_vacation_mode_series",
                return_value=pd.Series(0.0, index=weather.index),
            ),
            patch(
                "ml.forward.get_alarm_armed_series",
                return_value=pd.Series(0.0, index=weather.index),
            ),
            patch("backend.astro.SunCalculator") as mock_sun,
            patch(
                "ml.forward._fetch_openmeteo_baseline_series",
                new=AsyncMock(return_value=baseline_series),
            ),
        ):
            mock_datetime.now.return_value = fixed_now
            mock_datetime.side_effect = datetime
            mock_sun.return_value.is_sun_up.return_value = True
            await generate_forward_slots(horizon_hours=n * 0.25, forecast_version="test")
        return engine.store_forecasts.call_args.args[0]

    return asyncio.run(run())


def test_forward_missing_key_uses_default_one_and_stores_raw() -> None:
    items = _run_forward("missing", [10.0], [1.0])
    assert items[0]["pv_forecast_kwh"] == pytest.approx(2.0)
    assert items[0]["pv_ml_residual_raw_kwh"] == pytest.approx(10.0)


def test_forward_zero_bound_equals_baseline() -> None:
    items = _run_forward(0, [10.0], [1.0])
    assert items[0]["pv_forecast_kwh"] == pytest.approx(1.0)
    assert items[0]["pv_ml_residual_raw_kwh"] == pytest.approx(10.0)


def test_forward_half_bound_kept() -> None:
    items = _run_forward(0.5, [10.0], [1.0])
    assert items[0]["pv_forecast_kwh"] == pytest.approx(1.5)


def test_forward_hybrid_stores_raw_while_forecast_uses_bounded() -> None:
    items = _run_forward(0.1, [0.4], [1.0])
    assert items[0]["pv_ml_residual_raw_kwh"] == pytest.approx(0.4)
    assert items[0]["pv_forecast_kwh"] == pytest.approx(1.1)


def test_forward_baseline_only_stores_none() -> None:
    items = _run_forward(1.0, [0.4], [1.0], with_model=False)
    assert items[0]["pv_ml_residual_raw_kwh"] is None
    assert items[0]["pv_forecast_kwh"] == pytest.approx(1.0)


def test_stored_raw_residual_reproduces_forecast() -> None:
    raw = [0.4, -2.0, 0.1, 3.0, 0.05, -0.2]
    baseline = [0.5, 1.0, 1.5, 1.0, 0.5, 0.8]
    bound = 0.5
    items = _run_forward(bound, raw, baseline)
    stored = np.array([i["pv_ml_residual_raw_kwh"] for i in items])
    ceiling = 10.0 * 0.95 * 0.25
    values = _hybrid_pv_values(
        stored,
        np.array(baseline),
        np.ones(len(raw), dtype=bool),
        np.full(len(raw), 800.0),
        bound,
        1.0,
        ceiling,
    )
    expected = pd.Series(values).rolling(window=3, center=True, min_periods=1).mean()
    actual = [i["pv_forecast_kwh"] for i in items]
    assert actual == pytest.approx(expected.tolist())
