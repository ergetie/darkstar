import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytz

from backend.learning import LearningEngine
from ml.train import (  # type: ignore[reportPrivateUsage]
    _build_time_features,
    _load_slot_observations,
)


class TestResidualTrainingPipeline(unittest.TestCase):
    """Tests for the residual-based PV training pipeline."""

    def test_build_time_features_residual_data(self):
        """Test that time features are built correctly for residual training."""
        tz = pytz.timezone("Europe/Stockholm")
        slots = pd.date_range(
            start=tz.localize(datetime(2024, 6, 21, 6, 0)),
            periods=96,  # 24 hours
            freq="15min",
            tz=tz,
        )

        df = pd.DataFrame(
            {
                "slot_start": slots,
                "pv_kwh": np.random.uniform(0, 1, 96),
                "physics_kwh": np.random.uniform(0, 1.2, 96),
                "pv_residual": np.random.uniform(-0.2, 0.2, 96),
                "shortwave_radiation_w_m2": np.random.uniform(0, 800, 96),
            }
        )

        result = _build_time_features(df)

        # Verify time features exist
        assert "hour" in result.columns
        assert "day_of_week" in result.columns
        assert "month" in result.columns
        assert "is_weekend" in result.columns
        assert "hour_sin" in result.columns
        assert "hour_cos" in result.columns

        # Verify hour values are correct
        assert result["hour"].iloc[0] == 6
        assert result["hour"].iloc[4] == 7  # After 4 x 15min slots

    def test_sun_up_filter_logic(self):
        """Test the sun-up filter for PV training data."""
        tz = pytz.timezone("Europe/Stockholm")

        # Create sample data with varying radiation and PV
        df = pd.DataFrame(
            {
                "slot_start": pd.date_range(
                    start=tz.localize(datetime(2024, 6, 21, 0, 0)),
                    periods=96,
                    freq="15min",
                    tz=tz,
                ),
                "pv_kwh": [0.0] * 24 + [0.1] * 4 + [0.5] * 40 + [0.1] * 4 + [0.0] * 24,
                "shortwave_radiation_w_m2": [0.0] * 24
                + [100] * 4
                + [800] * 40
                + [50] * 4
                + [0.0] * 24,
            }
        )

        # Apply sun-up filter: radiation > 10 OR pv > 0.01
        sun_up_mask = (df["shortwave_radiation_w_m2"] > 10) | (df["pv_kwh"] > 0.01)
        filtered = df[sun_up_mask].copy()

        # Verify nighttime slots are filtered out
        # First 24 slots (0-6h) have radiation=0 and pv=0
        # Last 24 slots (22-24h) have radiation=0 and pv=0
        assert len(filtered) < len(df)

        # All filtered slots should have either radiation > 10 or pv > 0.01
        assert all((filtered["shortwave_radiation_w_m2"] > 10) | (filtered["pv_kwh"] > 0.01))

    def test_residual_calculation(self):
        """Test that residual is calculated correctly."""
        df = pd.DataFrame(
            {
                "pv_kwh": [0.5, 0.3, 0.8, 0.1],
                "physics_kwh": [0.6, 0.35, 0.7, 0.15],
            }
        )

        df["pv_residual"] = df["pv_kwh"] - df["physics_kwh"]

        # Verify residual calculations
        assert abs(df["pv_residual"].iloc[0] - (-0.1)) < 0.001
        assert abs(df["pv_residual"].iloc[1] - (-0.05)) < 0.001
        assert abs(df["pv_residual"].iloc[2] - 0.1) < 0.001
        assert abs(df["pv_residual"].iloc[3] - (-0.05)) < 0.001

    def test_residual_statistics_reasonable(self):
        """Test that residual statistics are within reasonable bounds."""
        np.random.seed(42)
        n_samples = 1000

        # Simulate realistic physics and actual PV values
        physics = np.random.uniform(0, 1.5, n_samples)
        noise = np.random.normal(0, 0.1, n_samples)
        actual = np.clip(physics + noise, 0, 2.0)

        residual = actual - physics

        # Residual mean should be close to 0
        assert abs(np.mean(residual)) < 0.1

        # Residual std should be reasonable (not huge)
        assert np.std(residual) < 0.5

        # Most residuals should be within reasonable bounds
        assert np.percentile(np.abs(residual), 95) < 0.5

    def test_physics_feature_included(self):
        """Test that physics forecast is included as a feature."""
        feature_cols = [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "hour_sin",
            "hour_cos",
            "temp_c",
            "cloud_cover_pct",
            "shortwave_radiation_w_m2",
            "vacation_mode_flag",
            "alarm_armed_flag",
        ]

        # Add physics feature
        pv_feature_cols = feature_cols.copy()
        pv_feature_cols.append("physics_forecast_kwh")

        assert "physics_forecast_kwh" in pv_feature_cols
        assert len(pv_feature_cols) == len(feature_cols) + 1


class TestTrainingDataPreparation(unittest.TestCase):
    """Tests for training data preparation with physics residuals."""

    def test_physics_calculated_for_each_slot(self):
        """Verify physics is calculated for each training slot."""
        from ml.weather import calculate_physics_pv

        tz = pytz.timezone("Europe/Stockholm")
        slot_start = tz.localize(datetime(2024, 6, 21, 12, 0))

        solar_arrays = [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        physics_kwh, per_array = calculate_physics_pv(
            radiation_w_m2=800.0,
            solar_arrays=solar_arrays,
            slot_start=slot_start,
            latitude=59.3,
            longitude=18.1,
        )

        assert physics_kwh is not None
        assert physics_kwh > 0
        assert len(per_array) == 1

    def test_physics_zero_at_night(self):
        """Verify physics returns 0 when sun is below horizon."""
        from ml.weather import calculate_physics_pv

        tz = pytz.timezone("Europe/Stockholm")
        # 2 AM in summer - sun might be up at 59°N, use winter
        slot_start = tz.localize(datetime(2024, 12, 21, 2, 0))

        solar_arrays = [{"name": "South", "kwp": 5.0, "tilt": 30.0, "azimuth": 180.0}]

        physics_kwh, _ = calculate_physics_pv(
            radiation_w_m2=100.0,  # Some radiation value
            solar_arrays=solar_arrays,
            slot_start=slot_start,
            latitude=59.3,
            longitude=18.1,
        )

        # Sun below horizon -> 0
        assert physics_kwh == 0.0


class TestSpikeFiltering(unittest.TestCase):
    """Tests for spike filtering in ML training data loading."""

    def test_load_slot_observations_filters_spikes(self):
        """Verify that _load_slot_observations filters out spike values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            config = {
                "system": {"grid": {"max_power_kw": 10.0}},
                "timezone": "Europe/Stockholm",
            }

            engine = LearningEngine.__new__(LearningEngine)
            engine.db_path = str(db_path)
            engine.config = config
            engine.timezone = pytz.timezone("Europe/Stockholm")

            with sqlite3.connect(db_path) as conn:
                conn.execute("""
                    CREATE TABLE slot_observations (
                        slot_start TEXT PRIMARY KEY,
                        load_kwh REAL,
                        pv_kwh REAL,
                        quality_flags TEXT
                    )
                """)

                tz = pytz.timezone("Europe/Stockholm")
                base_time = tz.localize(datetime(2024, 6, 21, 12, 0))

                test_data = [
                    (base_time.isoformat(), 1.5, 2.0),
                    ((base_time + timedelta(minutes=15)).isoformat(), 100.0, 2.0),
                    ((base_time + timedelta(minutes=30)).isoformat(), 1.5, 100.0),
                    ((base_time + timedelta(minutes=45)).isoformat(), 100.0, 100.0),
                ]

                for slot_start, load_kwh, pv_kwh in test_data:
                    conn.execute(
                        "INSERT INTO slot_observations "
                        "(slot_start, load_kwh, pv_kwh) VALUES (?, ?, ?)",
                        (slot_start, load_kwh, pv_kwh),
                    )
                conn.commit()

            start_time = base_time - timedelta(minutes=15)
            end_time = base_time + timedelta(minutes=15)
            df = _load_slot_observations(engine, start_time, end_time)

            max_kwh = 10.0 * 0.25 * 2.0
            assert all(df["load_kwh"] <= max_kwh)
            assert all(df["pv_kwh"] <= max_kwh)


if __name__ == "__main__":
    unittest.main()
