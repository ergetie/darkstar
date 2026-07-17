"""Tests for price forecasting feature engineering."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.learning.models import Base, SlotObservation
from ml.price_features import build_price_features, build_price_features_batch


class TestPriceFeatures(unittest.TestCase):
    """Test price feature engineering."""

    def test_calendar_features(self):
        """Test calendar feature generation (Task 9.1)."""
        print("\n--- Testing Calendar Features ---")

        slot = datetime(2026, 3, 15, 14, 0, tzinfo=pytz.UTC)

        features = build_price_features(
            slot_start=slot,
            days_ahead=2,
            wind_index=5.0,
            temperature_c=10.0,
        )

        # Verify calendar features
        self.assertEqual(features["hour"], 14)
        self.assertEqual(features["day_of_week"], 6)  # Sunday
        self.assertEqual(features["month"], 3)
        self.assertTrue(features["is_weekend"])  # Sunday is a weekend

        # Test weekday detection
        monday = datetime(2026, 3, 16, 14, 0, tzinfo=pytz.UTC)
        mon_features = build_price_features(
            slot_start=monday,
            days_ahead=1,
        )
        self.assertFalse(mon_features["is_weekend"])

        print("✓ Calendar features generated correctly")

    def test_holiday_detection(self):
        """Test Swedish holiday detection (Task 9.1)."""
        print("\n--- Testing Holiday Detection ---")

        # New Year's Day
        new_year = datetime(2026, 1, 1, 12, 0, tzinfo=pytz.UTC)
        features = build_price_features(slot_start=new_year, days_ahead=1)
        self.assertTrue(features["is_holiday"])

        # Labour Day
        may_day = datetime(2026, 5, 1, 12, 0, tzinfo=pytz.UTC)
        features = build_price_features(slot_start=may_day, days_ahead=1)
        self.assertTrue(features["is_holiday"])

        # National Day
        national_day = datetime(2026, 6, 6, 12, 0, tzinfo=pytz.UTC)
        features = build_price_features(slot_start=national_day, days_ahead=1)
        self.assertTrue(features["is_holiday"])

        # Regular day
        regular_day = datetime(2026, 3, 15, 12, 0, tzinfo=pytz.UTC)
        features = build_price_features(slot_start=regular_day, days_ahead=1)
        self.assertFalse(features["is_holiday"])

        print("✓ Holiday detection working correctly")

    def test_weather_passthrough(self):
        """Test weather features are passed through correctly."""
        print("\n--- Testing Weather Passthrough ---")

        slot = datetime(2026, 3, 15, 14, 0, tzinfo=pytz.UTC)

        features = build_price_features(
            slot_start=slot,
            days_ahead=2,
            wind_index=8.5,
            temperature_c=12.3,
            cloud_cover=45.0,
            radiation_wm2=350.0,
        )

        self.assertEqual(features["wind_index"], 8.5)
        self.assertEqual(features["temperature_c"], 12.3)
        self.assertEqual(features["cloud_cover"], 45.0)
        self.assertEqual(features["radiation_wm2"], 350.0)
        self.assertEqual(features["days_ahead"], 2)

        print("✓ Weather features passed through correctly")

    @patch("ml.price_features._get_price_lags")
    def test_price_lag_features(self, mock_get_lags):
        """Test price lag feature retrieval."""
        print("\n--- Testing Price Lag Features ---")

        # Mock the lag retrieval function
        mock_get_lags.return_value = {
            "price_lag_1d": 0.25,
            "price_lag_7d": 0.22,
            "price_lag_24h_avg": 0.23,
        }

        mock_session = MagicMock()
        slot = datetime(2026, 3, 15, 14, 0, tzinfo=pytz.UTC)

        features = build_price_features(
            slot_start=slot,
            days_ahead=1,
            db_session=mock_session,
        )

        # Verify lag features are present (values from mock)
        self.assertEqual(features["price_lag_1d"], 0.25)
        self.assertEqual(features["price_lag_7d"], 0.22)
        self.assertEqual(features["price_lag_24h_avg"], 0.23)

        # Verify the function was called
        mock_get_lags.assert_called_once()

        print("✓ Price lag features retrieved correctly")

    @patch("ml.price_features._get_price_lags")
    def test_build_price_features_batch(self, mock_get_lags):
        """Test batch feature generation."""
        print("\n--- Testing Batch Feature Generation ---")

        # Mock lag retrieval
        mock_get_lags.return_value = {
            "price_lag_1d": float("nan"),
            "price_lag_7d": float("nan"),
            "price_lag_24h_avg": float("nan"),
        }

        start = datetime(2026, 3, 15, 0, 0, tzinfo=pytz.UTC)
        end = datetime(2026, 3, 15, 1, 0, tzinfo=pytz.UTC)

        # Create sample weather DataFrame
        weather_df = pd.DataFrame(
            {
                "wind_index": [5.0, 6.0, 7.0, 8.0, 9.0],
                "temperature_c": [10.0, 11.0, 12.0, 13.0, 14.0],
            },
            index=pd.date_range(start, periods=5, freq="15min"),
        )

        mock_session = MagicMock()
        df = build_price_features_batch(
            start_time=start,
            end_time=end,
            days_ahead=1,
            weather_df=weather_df,
            db_session=mock_session,
        )

        # Should have 4-5 slots (0:00, 0:15, 0:30, 0:45, possibly 1:00)
        self.assertGreaterEqual(len(df), 4)

        # Check feature columns exist
        expected_cols = [
            "hour",
            "day_of_week",
            "month",
            "is_weekend",
            "is_holiday",
            "days_ahead",
            "wind_index",
            "temperature_c",
        ]
        for col in expected_cols:
            self.assertIn(col, df.columns)

        print(f"✓ Generated {len(df)} feature rows correctly")


@pytest.fixture
def db_session(tmp_path):
    """Real SQLite session with the slot_observations schema, no seeded rows."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def test_inference_wiring_populates_lag_from_observation(db_session):
    """build_price_features_batch, called the way generate_price_forecasts now
    calls it (with a db_session), populates price_lag_1d for a slot whose
    same-hour-yesterday observation exists, and leaves it NaN when absent."""
    tz = pytz.timezone("Europe/Stockholm")
    slot_with_lag = tz.localize(datetime(2026, 4, 10, 12, 0))
    lag_source = slot_with_lag - timedelta(days=1)

    db_session.add(
        SlotObservation(
            slot_start=lag_source.isoformat(),
            slot_end=(lag_source + timedelta(minutes=15)).isoformat(),
            export_price_sek_kwh=0.42,
        )
    )
    db_session.commit()

    start_time = slot_with_lag
    end_time = start_time + timedelta(minutes=15)
    df = build_price_features_batch(
        start_time=start_time,
        end_time=end_time,
        days_ahead=1,
        db_session=db_session,
    )

    row = df.loc[start_time.isoformat()]
    assert row["price_lag_1d"] == pytest.approx(0.42)

    # A slot whose same-hour-yesterday has no observation row stays NaN
    slot_without_lag = tz.localize(datetime(2026, 4, 20, 12, 0))
    df_missing = build_price_features_batch(
        start_time=slot_without_lag,
        end_time=slot_without_lag + timedelta(minutes=15),
        days_ahead=1,
        db_session=db_session,
    )
    row_missing = df_missing.loc[slot_without_lag.isoformat()]
    assert pd.isna(row_missing["price_lag_1d"])


if __name__ == "__main__":
    unittest.main()
