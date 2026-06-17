"""Tests for price outlook functionality (Tasks 6.1-6.6)."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.core.price_outlook import (
    build_outlook_response,
    classify_confidence,
    classify_level,
    get_daily_outlook,
    get_trailing_avg,
)


class TestGetDailyOutlook(unittest.TestCase):
    """Test get_daily_outlook() aggregation (Task 6.1)."""

    def setUp(self):
        """Create a temporary database for testing."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.create_test_tables()

    def tearDown(self):
        """Clean up temporary database."""
        os.close(self.db_fd)
        Path(self.db_path).unlink()

    def create_test_tables(self):
        """Create test tables with sample data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create price_forecasts table
        cursor.execute("""
            CREATE TABLE price_forecasts (
                slot_start TEXT,
                issue_timestamp TEXT,
                days_ahead INTEGER,
                spot_p10 REAL,
                spot_p50 REAL,
                spot_p90 REAL
            )
        """)

        # Insert test data for D+1 through D+7 using future dates relative to today
        from datetime import datetime, timedelta

        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for day_offset in range(1, 8):
            current_date = base_date + timedelta(days=day_offset)
            date = current_date.strftime("%Y-%m-%d")
            for hour in range(24):
                slot_start = f"{date}T{hour:02d}:00:00"
                # Vary prices by day to test aggregation
                spot_p50 = 0.4 + (day_offset * 0.05)  # Increasing prices
                spot_p10 = spot_p50 * 0.8
                spot_p90 = spot_p50 * 1.2
                issue_timestamp = "2026-03-30T12:00:00Z"

                cursor.execute(
                    """
                    INSERT INTO price_forecasts (slot_start, issue_timestamp, days_ahead, spot_p10, spot_p50, spot_p90)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (slot_start, issue_timestamp, day_offset, spot_p10, spot_p50, spot_p90),
                )

        conn.commit()
        conn.close()

    def test_daily_aggregation(self):
        """Test that daily aggregation calculates correct averages."""
        print("\n--- Testing Daily Aggregation ---")

        from datetime import datetime, timedelta

        result = get_daily_outlook(self.db_path)

        self.assertEqual(len(result), 7)

        # Check D+1
        day1 = result[0]
        expected_date_1 = (
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        self.assertEqual(day1["date"], expected_date_1)
        self.assertEqual(day1["days_ahead"], 1)
        self.assertAlmostEqual(day1["avg_spot_p50"], 0.45, places=2)

        # Check D+7
        day7 = result[6]
        expected_date_7 = (
            datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
        ).strftime("%Y-%m-%d")
        self.assertEqual(day7["date"], expected_date_7)
        self.assertEqual(day7["days_ahead"], 7)
        self.assertAlmostEqual(day7["avg_spot_p50"], 0.75, places=2)

        print("✓ Daily aggregation calculates correct averages")

    def test_empty_result_when_no_data(self):
        """Test empty result when no forecast records exist."""
        print("\n--- Testing Empty Result ---")

        # Create empty database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM price_forecasts")
        conn.commit()
        conn.close()

        result = get_daily_outlook(self.db_path)

        self.assertEqual(len(result), 0)

        print("✓ Returns empty list when no forecast data exists")

    def test_d1_through_d7_range(self):
        """Test that results cover D+1 through D+7."""
        print("\n--- Testing D+1 through D+7 Range ---")

        result = get_daily_outlook(self.db_path)

        days_ahead_values = [d["days_ahead"] for d in result]
        self.assertEqual(sorted(days_ahead_values), [1, 2, 3, 4, 5, 6, 7])

        print("✓ Results cover D+1 through D+7")

    def test_only_latest_run_loaded(self):
        """Test that get_daily_outlook only reads from the latest forecast run."""
        print("\n--- Testing Only Latest Run Loaded ---")

        # Insert a older run with very high prices
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        from datetime import datetime, timedelta
        base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Older run (earlier issue_timestamp)
        for day_offset in range(1, 8):
            current_date = base_date + timedelta(days=day_offset)
            date = current_date.strftime("%Y-%m-%d")
            for hour in range(24):
                slot_start = f"{date}T{hour:02d}:00:00"
                cursor.execute(
                    """
                    INSERT INTO price_forecasts (slot_start, issue_timestamp, days_ahead, spot_p10, spot_p50, spot_p90)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (slot_start, "2026-03-30T11:00:00Z", day_offset, 10.0, 10.0, 10.0),
                )

        conn.commit()
        conn.close()

        # The output should be identical to the setUp latest run (prices around 0.45-0.75, NOT 10.0)
        result = get_daily_outlook(self.db_path)
        self.assertEqual(len(result), 7)
        self.assertLess(result[0]["avg_spot_p50"], 1.0)
        self.assertAlmostEqual(result[0]["avg_spot_p50"], 0.45, places=2)
        print("✓ Only latest run loaded successfully")



class TestGetTrailingAvg(unittest.TestCase):
    """Test get_trailing_avg() helper (Task 6.2)."""

    def setUp(self):
        """Create a temporary database for testing."""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.create_test_tables()

    def tearDown(self):
        """Clean up temporary database."""
        os.close(self.db_fd)
        Path(self.db_path).unlink()

    def create_test_tables(self):
        """Create test tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create slot_observations table
        cursor.execute("""
            CREATE TABLE slot_observations (
                slot_start TEXT,
                export_price_sek_kwh REAL
            )
        """)

        conn.commit()
        conn.close()

    def add_observations(self, num_days: int, price: float = 0.5):
        """Helper to add observations for N days."""
        from datetime import datetime, timedelta

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        base_date = datetime(2026, 3, 30)
        for day_offset in range(num_days):
            current_date = base_date - timedelta(days=day_offset)
            date = current_date.strftime("%Y-%m-%d")
            for hour in range(24):
                slot_start = f"{date}T{hour:02d}:00:00"
                cursor.execute(
                    """
                    INSERT INTO slot_observations (slot_start, export_price_sek_kwh)
                    VALUES (?, ?)
                """,
                    (slot_start, price),
                )

        conn.commit()
        conn.close()

    def test_14_day_mean(self):
        """Test calculation of 14-day mean."""
        print("\n--- Testing 14-Day Mean ---")

        self.add_observations(14, price=0.5)

        result = get_trailing_avg(self.db_path)

        self.assertAlmostEqual(result, 0.5, places=2)

        print("✓ 14-day mean calculated correctly")

    def test_partial_history_fallback(self):
        """Test fallback to partial history (3 days)."""
        print("\n--- Testing Partial History Fallback ---")

        self.add_observations(3, price=0.6)

        result = get_trailing_avg(self.db_path)

        self.assertAlmostEqual(result, 0.6, places=2)

        print("✓ Partial history (3 days) fallback works")

    def test_none_for_less_than_2_days(self):
        """Test None returned for fewer than 2 days."""
        print("\n--- Testing None for Less Than 2 Days ---")

        self.add_observations(1, price=0.5)

        result = get_trailing_avg(self.db_path)

        self.assertIsNone(result)

        print("✓ Returns None for less than 2 days of data")


class TestLevelClassification(unittest.TestCase):
    """Test level classification (Task 6.3)."""

    def test_cheap_below_85_percent(self):
        """Test level is 'cheap' when below 85% of reference."""
        print("\n--- Testing Cheap Level ---")

        result = classify_level(0.4, 0.5)  # 80% of reference

        self.assertEqual(result, "cheap")

        print("✓ Level 'cheap' when < 85%")

    def test_normal_between_85_and_115_percent(self):
        """Test level is 'normal' when between 85-115% of reference."""
        print("\n--- Testing Normal Level ---")

        result = classify_level(0.5, 0.5)  # 100% of reference

        self.assertEqual(result, "normal")

        result = classify_level(0.45, 0.5)  # 90% of reference
        self.assertEqual(result, "normal")

        print("✓ Level 'normal' when 85-115%")

    def test_expensive_above_115_percent(self):
        """Test level is 'expensive' when above 115% of reference."""
        print("\n--- Testing Expensive Level ---")

        result = classify_level(0.6, 0.5)  # 120% of reference

        self.assertEqual(result, "expensive")

        print("✓ Level 'expensive' when > 115%")

    def test_unknown_when_reference_is_none(self):
        """Test level is 'unknown' when reference is None."""
        print("\n--- Testing Unknown Level ---")

        result = classify_level(0.5, None)

        self.assertEqual(result, "unknown")

        print("✓ Level 'unknown' when reference is None")


class TestConfidenceClassification(unittest.TestCase):
    """Test confidence classification (Task 6.4 component)."""

    def test_high_confidence_d1_d2(self):
        """Test confidence is 'high' for D+1 and D+2."""
        print("\n--- Testing High Confidence ---")

        self.assertEqual(classify_confidence(1), "high")
        self.assertEqual(classify_confidence(2), "high")

        print("✓ Confidence 'high' for D+1/D+2")

    def test_medium_confidence_d3_d4(self):
        """Test confidence is 'medium' for D+3 and D+4."""
        print("\n--- Testing Medium Confidence ---")

        self.assertEqual(classify_confidence(3), "medium")
        self.assertEqual(classify_confidence(4), "medium")

        print("✓ Confidence 'medium' for D+3/D+4")

    def test_low_confidence_d5_d7(self):
        """Test confidence is 'low' for D+5 through D+7."""
        print("\n--- Testing Low Confidence ---")

        self.assertEqual(classify_confidence(5), "low")
        self.assertEqual(classify_confidence(6), "low")
        self.assertEqual(classify_confidence(7), "low")

        print("✓ Confidence 'low' for D+5-D+7")


class TestBuildOutlookResponse(unittest.TestCase):
    """Test build_outlook_response (Task 6.5 component)."""

    def test_response_when_enabled_with_data(self):
        """Test response shape when enabled with data."""
        print("\n--- Testing Enabled with Data Response ---")

        daily_outlook = [
            {
                "date": "2026-03-31",
                "day_label": "Mon",
                "days_ahead": 1,
                "avg_spot_p50": 0.45,
                "avg_spot_p10": 0.32,
                "avg_spot_p90": 0.58,
                "min_hour_p50": 0.22,
                "max_hour_p50": 0.78,
            }
        ]

        result = build_outlook_response(daily_outlook, 0.5, enabled=True)

        self.assertTrue(result["enabled"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["days"]), 1)
        self.assertEqual(result["reference_avg"], 0.5)

        # Check classification was applied
        day = result["days"][0]
        self.assertIn("level", day)
        self.assertIn("confidence", day)

        print("✓ Response shape correct when enabled with data")

    def test_response_when_disabled(self):
        """Test response when price forecast is disabled."""
        print("\n--- Testing Disabled Response ---")

        result = build_outlook_response([], None, enabled=False)

        self.assertFalse(result["enabled"])
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(len(result["days"]), 0)

        print("✓ Response correct when disabled")

    def test_response_when_no_data(self):
        """Test response when enabled but no data."""
        print("\n--- Testing No Data Response ---")

        result = build_outlook_response([], 0.5, enabled=True)

        self.assertTrue(result["enabled"])
        self.assertEqual(result["status"], "no_data")
        self.assertEqual(len(result["days"]), 0)

        print("✓ Response correct when no data")


if __name__ == "__main__":
    unittest.main()
