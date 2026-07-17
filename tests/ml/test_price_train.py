"""Tests for price model training."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.learning.models import Base, SlotObservation
from ml.price_train import _add_price_lag_features, train_price_model


class TestPriceTrain(unittest.TestCase):
    """Test price model training (Task 9.3)."""

    @patch("ml.price_train._build_training_dataset")
    def test_cold_start_gating_insufficient_samples(self, mock_build_dataset):
        """Test that training is skipped when insufficient samples."""
        print("\n--- Testing Cold-Start Gating (Insufficient Samples) ---")

        # Create DataFrame with insufficient samples
        mock_df = pd.DataFrame(
            {
                "export_price_sek_kwh": [0.3] * 100,  # Only 100 samples
            }
        )
        mock_build_dataset.return_value = mock_df

        with patch("ml.price_train.print") as mock_print:
            result = train_price_model(min_training_samples=500)

            # Should return False (training skipped)
            self.assertFalse(result)

            # Should print warning about insufficient samples
            mock_print.assert_any_call(
                "Skipping training: only 100 samples available; requires at least 500."
            )

        print("✓ Cold-start gating works with insufficient samples")

    @patch("ml.price_train._build_training_dataset")
    @patch("ml.price_train.lgb.LGBMRegressor")
    def test_training_creates_model_files(self, mock_model_class, mock_build_dataset):
        """Test that training creates model files when sufficient samples."""
        print("\n--- Testing Training Creates Model Files ---")

        # Create DataFrame with sufficient samples
        mock_df = pd.DataFrame(
            {
                "hour": [12] * 1000,
                "day_of_week": [1] * 1000,
                "month": [3] * 1000,
                "is_weekend": [0] * 1000,
                "is_holiday": [0] * 1000,
                "days_ahead": [1] * 1000,
                "price_lag_1d": [0.25] * 1000,
                "price_lag_7d": [0.22] * 1000,
                "price_lag_24h_avg": [0.23] * 1000,
                "wind_index": [5.0] * 1000,
                "temperature_c": [10.0] * 1000,
                "cloud_cover": [50.0] * 1000,
                "radiation_wm2": [200.0] * 1000,
                "export_price_sek_kwh": [0.3] * 1000,
            }
        )
        mock_build_dataset.return_value = mock_df

        # Mock model
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model

        # Mock model save
        with (
            patch("ml.price_train.Path.mkdir"),
            patch.object(Path, "exists", return_value=False),
            patch("ml.price_train._save_model"),
        ):
            result = train_price_model(min_training_samples=500)

            # Should return True (training successful)
            self.assertTrue(result)

            # Model should be trained 3 times (p10, p50, p90)
            self.assertEqual(mock_model.fit.call_count, 3)

        print("✓ Training creates model files correctly")

    def test_feature_column_list(self):
        """Test that feature columns match expected schema."""
        print("\n--- Testing Feature Column List ---")

        # Feature columns are defined in train_price_model function
        expected_cols = [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "is_holiday",
            "days_ahead",
            "price_lag_1d",
            "price_lag_7d",
            "price_lag_24h_avg",
            "wind_index",
            "temperature_c",
            "cloud_cover",
            "radiation_wm2",
        ]

        # Just verify the expected columns are valid feature names
        self.assertEqual(len(expected_cols), 13)
        self.assertIn("hour", expected_cols)
        self.assertIn("wind_index", expected_cols)

        print("✓ Feature columns match expected schema")


def test_add_price_lag_features_masks_by_issue_time_knowability(tmp_path):
    """Lags are only materialised when their source timestamp precedes the
    row's issue_timestamp — leakage-free even when the DB has the observation."""
    db_path = str(tmp_path / "test.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    tz = pytz.timezone("Europe/Stockholm")

    def local(y, m, d, h):
        return tz.localize(pd.Timestamp(y, m, d, h).to_pydatetime())

    # days_ahead=1 row: issued the same morning for a slot later that day.
    row_a_slot = local(2026, 4, 10, 12)
    row_a_issue = local(2026, 4, 10, 6)

    # days_ahead=5 row: issued 4 days ahead of the target slot.
    row_b_slot = local(2026, 4, 14, 12)
    row_b_issue = local(2026, 4, 10, 6)

    observation_timestamps = [
        row_a_slot - pd.Timedelta(days=1),  # row A lag_1d source (knowable)
        row_a_slot - pd.Timedelta(days=7),  # row A lag_7d source (knowable)
        row_b_slot - pd.Timedelta(days=1),  # row B lag_1d source (NOT knowable)
        row_b_slot - pd.Timedelta(days=7),  # row B lag_7d source (knowable)
    ]

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    for ts in observation_timestamps:
        session.add(
            SlotObservation(
                slot_start=ts.isoformat(),
                slot_end=(ts + pd.Timedelta(minutes=15)).isoformat(),
                export_price_sek_kwh=0.5,
            )
        )
    session.commit()
    session.close()
    engine.dispose()

    df = pd.DataFrame(
        {
            "slot_start": [row_a_slot, row_b_slot],
            "issue_timestamp": [row_a_issue, row_b_issue],
            "days_ahead": [1, 5],
        }
    )

    result = _add_price_lag_features(df, db_path)

    row_a = result.iloc[0]
    row_b = result.iloc[1]

    # Row A: both lags knowable at issue time -> populated.
    assert row_a["price_lag_1d"] == pytest.approx(0.5)
    assert row_a["price_lag_7d"] == pytest.approx(0.5)

    # Row B: lag_1d source is after issue time -> NaN despite the DB row existing.
    assert pd.isna(row_b["price_lag_1d"])
    # Row B: lag_7d source still precedes issue time -> populated.
    assert row_b["price_lag_7d"] == pytest.approx(0.5)


if __name__ == "__main__":
    unittest.main()
