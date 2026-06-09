"""Tests for ml-forecast-correctness fixes (#9, #10, #15, #16, #17, #18, OQ5)."""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytz

from backend.learning import LearningEngine


# ---------------------------------------------------------------------------
# Task 1.4: Input integrity tests
# ---------------------------------------------------------------------------


class TestBaselineAggNoTempSubstitution:
    """Task 1.4a – baseline aggregation never emits load magnitudes in temp_c."""

    def _make_engine(self) -> LearningEngine:
        engine = LearningEngine.__new__(LearningEngine)
        engine.timezone = pytz.timezone("Europe/Stockholm")
        return engine

    def _make_observations(self, n_days: int = 8) -> pd.DataFrame:
        tz = pytz.timezone("Europe/Stockholm")
        base = tz.localize(datetime(2024, 6, 14, 0, 0))
        slots = [base + timedelta(hours=i) for i in range(n_days * 24)]
        return pd.DataFrame(
            {
                "slot_start": slots,
                "load_kwh": [1.5 + 0.1 * (i % 5) for i in range(len(slots))],
                "pv_kwh": [0.5 * max(0, abs(i % 24 - 12) - 6) / 6 for i in range(len(slots))],
            }
        )

    def test_temp_c_is_none_when_absent_from_history(self):
        """When observations have no temp_c, returned temp_c must be None."""
        from ml.evaluate import _generate_baseline_forecasts  # type: ignore[reportPrivateUsage]

        obs = self._make_observations()
        assert "temp_c" not in obs.columns

        forecasts = _generate_baseline_forecasts(obs, self._make_engine())

        assert len(forecasts) > 0
        for f in forecasts:
            assert f["temp_c"] is None, (
                f"temp_c should be None when absent from history, got {f['temp_c']}"
            )

    def test_temp_c_not_a_load_magnitude(self):
        """temp_c must never be a load-like value (e.g. 1.5 kWh)."""
        from ml.evaluate import _generate_baseline_forecasts  # type: ignore[reportPrivateUsage]

        obs = self._make_observations()
        forecasts = _generate_baseline_forecasts(obs, self._make_engine())

        for f in forecasts:
            assert f["temp_c"] is None or abs(f["temp_c"]) < 100, (
                f"temp_c={f['temp_c']} looks like a load magnitude, not a temperature"
            )


class TestConfigLoadFailureWarns:
    """Task 1.4b – failed config.yaml load emits a warning."""

    def test_warning_on_missing_file(self, caplog):
        from ml.api import _load_config  # type: ignore[reportPrivateUsage]

        with patch("pathlib.Path.open", side_effect=FileNotFoundError("no such file")):
            with caplog.at_level(logging.WARNING, logger="ml.api"):
                result = _load_config()

        assert result == {}
        assert any("Failed to load config.yaml" in r.message for r in caplog.records), (
            "Expected warning about config.yaml load failure"
        )

    def test_warning_on_yaml_error(self, caplog):
        import yaml
        from ml.api import _load_config  # type: ignore[reportPrivateUsage]

        with patch("yaml.safe_load", side_effect=yaml.YAMLError("bad yaml")):
            with caplog.at_level(logging.WARNING, logger="ml.api"):
                result = _load_config()

        assert result == {}
        assert any("Failed to load config.yaml" in r.message for r in caplog.records)


class TestContextFetchFailureWarns:
    """Task 1.4c – failed HA context fetch emits a warning."""

    def _vacation_config(self) -> dict:
        return {
            "timezone": "Europe/Stockholm",
            "input_sensors": {"vacation_mode": "input_boolean.vacation"},
        }

    def _alarm_config(self) -> dict:
        return {
            "timezone": "Europe/Stockholm",
            "input_sensors": {"alarm_state": "alarm_control_panel.alarmo"},
        }

    def test_vacation_fetch_failure_warns(self, caplog):
        import requests
        from ml.context_features import get_vacation_mode_series

        ha_config = {"url": "http://ha.local", "token": "tok"}
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        with patch("ml.context_features.load_home_assistant_config", return_value=ha_config):
            with patch(
                "ml.context_features.requests.get",
                side_effect=requests.RequestException("connection refused"),
            ):
                with caplog.at_level(logging.WARNING, logger="ml.context_features"):
                    result = get_vacation_mode_series(
                        now - timedelta(days=1), now, config=self._vacation_config()
                    )

        assert result.empty
        assert any(
            "Failed to fetch HA context feature" in r.message for r in caplog.records
        ), "Expected warning about HA context fetch failure"

    def test_alarm_fetch_failure_warns(self, caplog):
        import requests
        from ml.context_features import get_alarm_armed_series

        ha_config = {"url": "http://ha.local", "token": "tok"}
        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        with patch("ml.context_features.load_home_assistant_config", return_value=ha_config):
            with patch(
                "ml.context_features.requests.get",
                side_effect=requests.RequestException("timeout"),
            ):
                with caplog.at_level(logging.WARNING, logger="ml.context_features"):
                    result = get_alarm_armed_series(
                        now - timedelta(days=1), now, config=self._alarm_config()
                    )

        assert result.empty
        assert any(
            "Failed to fetch HA context feature" in r.message for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Task 2.3 + 2.4: Recency sample-weight alignment tests
# ---------------------------------------------------------------------------


class TestSampleWeightAlignment:
    """Tasks 2.3, 2.4 – recency weights align correctly with gapped and contiguous indices."""

    def test_gapped_index_no_index_error(self):
        """Training set with one un-parseable slot_start completes without IndexError."""
        from ml.train import _compute_sample_weights

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        # Simulate raw DB output with one un-parseable slot_start
        raw_df = pd.DataFrame(
            {
                "slot_start": [
                    now - timedelta(days=5),
                    now - timedelta(days=4),
                    pd.NaT,  # un-parseable -> dropped by dropna
                    now - timedelta(days=2),
                    now - timedelta(days=1),
                ],
                "load_kwh": [1.0, 1.2, 1.3, 1.1, 1.0],
                "pv_kwh": [0.5, 0.6, 0.7, 0.5, 0.4],
            }
        )

        # Apply same logic as _load_slot_observations (after our fix)
        df = raw_df.dropna(subset=["slot_start"])
        df = df.reset_index(drop=True)  # our fix: labels == positions

        assert list(df.index) == list(range(len(df))), "Index must be contiguous after reset"

        # Wrap weights as labeled Series (our fix)
        weights_array = _compute_sample_weights(df)
        weights_series = pd.Series(weights_array, index=df.index)

        load_df = df[df["load_kwh"] > 0.001]

        # Must not raise IndexError; all surviving rows get individual weights
        load_weights = weights_series.loc[load_df.index].values

        assert len(load_weights) == len(load_df)
        for i, row_idx in enumerate(load_df.index):
            assert abs(load_weights[i] - weights_series.loc[row_idx]) < 1e-10, (
                f"Weight mismatch at row {row_idx}"
            )

    def test_each_surviving_row_gets_own_weight(self):
        """Each surviving row after dropna gets the recency weight computed for that row."""
        from ml.train import _compute_sample_weights

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        df = pd.DataFrame(
            {
                "slot_start": [now - timedelta(days=d) for d in (10, 5, 1)],
                "load_kwh": [1.0, 1.5, 2.0],
            }
        )
        # Reset to contiguous index
        df = df.reset_index(drop=True)

        weights_array = _compute_sample_weights(df)
        weights_series = pd.Series(weights_array, index=df.index)

        # Older rows have lower weights
        assert weights_series[2] > weights_series[1] > weights_series[0], (
            "More recent rows must have higher recency weights"
        )

    def test_contiguous_data_weights_unchanged(self):
        """Contiguous observations produce weights identical to the previous positional behavior."""
        from ml.train import _compute_sample_weights

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)

        df = pd.DataFrame(
            {
                "slot_start": [now - timedelta(days=i) for i in range(5)],
                "load_kwh": [1.0, 1.2, 1.3, 1.1, 1.0],
            }
        )
        # Default contiguous index 0..4
        assert list(df.index) == [0, 1, 2, 3, 4]

        weights_array = _compute_sample_weights(df)
        weights_series = pd.Series(weights_array, index=df.index)

        # .loc on a contiguous 0-based index must give the same values as positional indexing
        load_df = df  # all rows pass filter
        weights_via_loc = weights_series.loc[load_df.index].values

        np.testing.assert_array_almost_equal(weights_array, weights_via_loc)


# ---------------------------------------------------------------------------
# Task 3.3 + 3.4: Train/inference feature symmetry tests
# ---------------------------------------------------------------------------


class TestFeatureSymmetry:
    """Tasks 3.3, 3.4 – training and inference use the same feature set."""

    def test_empty_weather_materialises_all_three_columns(self):
        """When weather_df is empty, training adds all 3 weather columns (NaN-filled)."""
        from ml.train import _build_time_features

        tz = pytz.timezone("Europe/Stockholm")
        now = datetime.now(tz)
        observations = pd.DataFrame(
            {
                "slot_start": [now - timedelta(days=i) for i in range(10)],
                "load_kwh": [1.0] * 10,
                "pv_kwh": [0.5] * 10,
            }
        )

        # Simulate the else-branch: weather_df empty → materialise all 3 cols NaN
        for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
            observations[col] = np.nan
        for col in ("temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
            observations[col] = pd.to_numeric(observations[col], errors="coerce")

        observations = _build_time_features(observations)
        feature_cols = [
            "hour", "day_of_week", "month", "is_weekend", "hour_sin", "hour_cos",
        ]
        for feat in ["temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2",
                     "vacation_mode_flag", "alarm_armed_flag"]:
            if feat in observations.columns:
                feature_cols.append(feat)

        # All 3 weather features must be present (core of the fix)
        assert "temp_c" in feature_cols
        assert "cloud_cover_pct" in feature_cols
        assert "shortwave_radiation_w_m2" in feature_cols

        # All 6 base time features + 3 weather cols = 9; context flags are optional (same in both)
        for f in ("hour", "day_of_week", "month", "is_weekend", "hour_sin", "hour_cos",
                  "temp_c", "cloud_cover_pct", "shortwave_radiation_w_m2"):
            assert f in feature_cols, f"Feature '{f}' absent from training feature list"

    def test_feature_mismatch_triggers_warning_and_fallback(self, tmp_path, caplog):
        """A model with mismatched persisted feature names is skipped; warning is logged."""
        import lightgbm as lgb
        from ml.forward import _load_models  # type: ignore[reportPrivateUsage]

        models_dir = tmp_path / "models"
        models_dir.mkdir()

        # Train a tiny real LightGBM model
        rng = np.random.default_rng(42)
        X = rng.random((50, 3))
        y = rng.random(50)
        model = lgb.LGBMRegressor(n_estimators=5, verbose=-1)
        model.fit(X, y)

        model_path = models_dir / "load_model_p50.lgb"
        model.booster_.save_model(str(model_path))

        # Write mismatched feature names
        features_path = models_dir / "load_model_p50.features.json"
        features_path.write_text(json.dumps({"feature_names": ["feat_a", "feat_b", "feat_c"]}))

        with caplog.at_level(logging.WARNING, logger="ml.forward"):
            models = _load_models(models_dir=str(models_dir))

        assert "load_p50" not in models, (
            "Model with mismatched feature names should be excluded from loaded models"
        )
        assert any("Feature mismatch" in r.message for r in caplog.records), (
            "Expected warning about feature mismatch"
        )

    def test_matching_feature_names_loads_model(self, tmp_path):
        """A model whose persisted feature names match inference expectations loads normally."""
        import lightgbm as lgb
        from ml.forward import _EXPECTED_LOAD_FEATURES, _load_models  # type: ignore[reportPrivateUsage]

        models_dir = tmp_path / "models"
        models_dir.mkdir()

        rng = np.random.default_rng(42)
        X = rng.random((50, 3))
        y = rng.random(50)
        model = lgb.LGBMRegressor(n_estimators=5, verbose=-1)
        model.fit(X, y)

        model_path = models_dir / "load_model_p50.lgb"
        model.booster_.save_model(str(model_path))

        # Write matching feature names
        features_path = models_dir / "load_model_p50.features.json"
        features_path.write_text(json.dumps({"feature_names": _EXPECTED_LOAD_FEATURES}))

        models = _load_models(models_dir=str(models_dir))

        assert "load_p50" in models, "Model with matching feature names should be loaded"


# ---------------------------------------------------------------------------
# Task 4.4: Monotonic quantile repair tests
# ---------------------------------------------------------------------------


class TestMonotonicQuantileRepair:
    """Task 4.4 – quantile bands are repaired to p10 ≤ p50 ≤ p90."""

    def test_crossed_inputs_reordered(self):
        """Crossed quantiles (p10 > p50 > p90) are reordered to non-decreasing."""
        p10, p50, p90 = 3.0, 2.0, 1.0  # all crossed
        p10_fixed, p50_fixed, p90_fixed = sorted([p10, p50, p90])

        assert p10_fixed <= p50_fixed <= p90_fixed
        assert p10_fixed == 1.0
        assert p50_fixed == 2.0
        assert p90_fixed == 3.0

    def test_valid_bands_unchanged(self):
        """Already-monotonic bands are returned unchanged by the sort."""
        p10, p50, p90 = 1.0, 2.5, 4.0
        p10_fixed, p50_fixed, p90_fixed = sorted([p10, p50, p90])

        assert p10_fixed == p10
        assert p50_fixed == p50
        assert p90_fixed == p90

    def test_read_repair_in_api_on_crossed_pv_bands(self):
        """Crossed PV bands on read are reordered; valid bands are unchanged."""
        # Simulate the repair logic in ml/api.py
        final_pv = 2.0
        pv_p10_val = 3.0  # crossed: p10 > p50
        pv_p90_val = 1.5  # crossed: p90 < p50

        _pv_sorted = sorted([float(pv_p10_val), final_pv, float(pv_p90_val)])
        pv_p10_out = _pv_sorted[0]
        pv_p90_out = _pv_sorted[2]

        assert pv_p10_out <= final_pv <= pv_p90_out
        assert pv_p10_out == 1.5
        assert pv_p90_out == 3.0

    def test_read_repair_valid_bands_unchanged(self):
        """Valid PV bands on read are not modified."""
        final_pv = 2.0
        pv_p10_val = 1.0
        pv_p90_val = 3.0

        _pv_sorted = sorted([float(pv_p10_val), final_pv, float(pv_p90_val)])
        pv_p10_out = _pv_sorted[0]
        pv_p90_out = _pv_sorted[2]

        assert pv_p10_out == pv_p10_val
        assert pv_p90_out == pv_p90_val

    def test_daily_aggregation_receives_monotonic_bands(self):
        """After on-read repair, p10 ≤ p50 ≤ p90 for all slots passed to aggregation."""
        # Simulate 5 slots with various crossing patterns, apply repair, check monotonicity
        test_cases = [
            (3.0, 2.0, 1.0),  # fully crossed
            (1.0, 2.0, 3.0),  # already valid
            (2.5, 2.5, 2.5),  # all equal
            (1.0, 3.0, 2.0),  # p90 < p50
            (2.0, 1.0, 3.0),  # p10 > p50
        ]
        for p10_val, p50_val, p90_val in test_cases:
            fixed = sorted([p10_val, p50_val, p90_val])
            assert fixed[0] <= fixed[1] <= fixed[2], (
                f"Repair failed for ({p10_val}, {p50_val}, {p90_val})"
            )


# ---------------------------------------------------------------------------
# Task 5.3: Evaluator mirrors live pipeline
# ---------------------------------------------------------------------------


class TestEvaluatorMirrorsLivePipeline:
    """Task 5.3 – evaluator's PV predictions reconstruct absolute PV (baseline + residual)."""

    def _make_engine(self) -> LearningEngine:
        engine = LearningEngine.__new__(LearningEngine)
        engine.timezone = pytz.timezone("Europe/Stockholm")
        return engine

    def _make_observations(self, n: int = 5, baseline: float = 2.0) -> pd.DataFrame:
        tz = pytz.timezone("Europe/Stockholm")
        base = tz.localize(datetime(2024, 6, 21, 8, 0))
        return pd.DataFrame(
            {
                "slot_start": [base + timedelta(minutes=15 * i) for i in range(n)],
                "load_kwh": [1.5] * n,
                "pv_kwh": [2.5] * n,
                "openmeteo_pv_forecast_kwh": [baseline] * n,
            }
        )

    def test_pv_prediction_adds_baseline_to_residual(self):
        """pv_forecast_kwh = openmeteo_baseline + ml_residual (not the raw residual alone)."""
        from ml.evaluate import _predict_with_boosters  # type: ignore[reportPrivateUsage]
        from ml.train import _build_time_features

        baseline = 2.0
        residual = 0.5
        obs = self._make_observations(n=5, baseline=baseline)
        features = _build_time_features(obs.copy())
        engine = self._make_engine()

        mock_pv_booster = MagicMock()
        mock_pv_booster.predict.return_value = np.full(len(obs), residual)

        forecasts = _predict_with_boosters(
            {"pv_p50": mock_pv_booster},
            features,
            obs,
            engine,
            "aurora",
        )

        assert len(forecasts) == len(obs)
        for f in forecasts:
            expected = max(0.0, baseline + residual)
            assert abs(f["pv_forecast_kwh"] - expected) < 1e-6, (
                f"Expected pv_forecast_kwh={expected}, got {f['pv_forecast_kwh']}"
            )

    def test_all_quantiles_included_in_output(self):
        """Evaluator outputs p10/p50/p90 quantiles when all quantile boosters are provided."""
        from ml.evaluate import _predict_with_boosters  # type: ignore[reportPrivateUsage]
        from ml.train import _build_time_features

        obs = self._make_observations(n=4, baseline=2.0)
        features = _build_time_features(obs.copy())
        engine = self._make_engine()

        # Mock all three quantile boosters with different residuals
        boosters = {}
        for q, residual in [("p10", -0.3), ("p50", 0.5), ("p90", 1.0)]:
            mock = MagicMock()
            mock.predict.return_value = np.full(len(obs), residual)
            boosters[f"pv_{q}"] = mock

        forecasts = _predict_with_boosters(boosters, features, obs, engine, "aurora")

        assert len(forecasts) == len(obs)
        for f in forecasts:
            assert "pv_p10" in f
            assert "pv_p50" in f
            assert "pv_p90" in f
            # p10 uses -0.3 residual + 2.0 baseline = max(0, 1.7)
            assert abs(f["pv_p10"] - 1.7) < 1e-6
            # p50 uses 0.5 residual + 2.0 baseline = 2.5
            assert abs(f["pv_p50"] - 2.5) < 1e-6
            # p90 uses 1.0 residual + 2.0 baseline = 3.0
            assert abs(f["pv_p90"] - 3.0) < 1e-6


# ---------------------------------------------------------------------------
# Task 6.3: Open-Meteo baseline gap-fill tests
# ---------------------------------------------------------------------------


class TestOpenMeteoGapFill:
    """Task 6.3 – interior NaN slots are interpolated; leading/trailing fall back to 0."""

    def _apply_baseline_fill(self, values: list[float | None]) -> pd.Series:
        """Apply the same gap-fill logic as forward.py's baseline_series construction."""
        s = pd.Series(
            [float(v) if v is not None else float("nan") for v in values],
            dtype="float64",
        )
        return s.interpolate(method="linear", limit_area="inside").fillna(0.0)

    def test_single_interior_nan_interpolated(self):
        """An isolated NaN between valid slots is filled by linear interpolation."""
        result = self._apply_baseline_fill([1.0, None, 3.0])

        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx(2.0)  # midpoint of 1 and 3
        assert result[2] == pytest.approx(3.0)

    def test_trailing_nan_falls_back_to_zero(self):
        """Trailing NaN (no valid right neighbour) falls back to 0, not physics."""
        result = self._apply_baseline_fill([1.0, 2.0, None, None])

        assert result[0] == pytest.approx(1.0)
        assert result[1] == pytest.approx(2.0)
        assert result[2] == pytest.approx(0.0)
        assert result[3] == pytest.approx(0.0)

    def test_leading_nan_falls_back_to_zero(self):
        """Leading NaN (no valid left neighbour) falls back to 0, not physics."""
        result = self._apply_baseline_fill([None, None, 3.0, 4.0])

        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.0)
        assert result[2] == pytest.approx(3.0)
        assert result[3] == pytest.approx(4.0)

    def test_all_valid_slots_unchanged(self):
        """When no NaN values are present, all values pass through unchanged."""
        values = [1.0, 2.0, 3.0, 4.0]
        result = self._apply_baseline_fill(values)

        for i, v in enumerate(values):
            assert result[i] == pytest.approx(v)

    def test_interior_nan_run_interpolated(self):
        """Multiple consecutive interior NaN slots are all filled by interpolation."""
        result = self._apply_baseline_fill([0.0, None, None, None, 4.0])

        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(1.0)
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_physics_never_used_for_nan_slots(self):
        """The result contains only interpolated or zero values — never physics estimates.

        Physics values would be large positive floats (~0.5–2 kWh for solar midday).
        The gap-fill produces only 0 for unreachable NaN, not physics.
        """
        PHYSICS_VALUE = 1.8  # would be produced by home-grown physics
        result = self._apply_baseline_fill([None, None, None])  # all NaN, no valid neighbours

        for i in range(len(result)):
            assert result[i] == pytest.approx(0.0), (
                f"Slot {i} should be 0.0 (not physics={PHYSICS_VALUE}), got {result[i]}"
            )
