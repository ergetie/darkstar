#!/usr/bin/env python3
"""
Insert mock price forecast data for testing the Weekly Outlook widget.
Run this after enabling price forecasting in config.yaml to see the UI with data.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytz

LOCAL_TZ = pytz.timezone("Europe/Stockholm")


def insert_mock_forecasts(db_path: str = "data/planner_learning.db"):
    """Insert 7 days of mock price forecast data."""

    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_forecasts'")
    if not cursor.fetchone():
        print("price_forecasts table doesn't exist. Run: uv run alembic upgrade 5a8b9c2d1e3f")
        return

    # Generate 7 days of hourly forecasts (24 slots per day)
    base_date = datetime(2026, 3, 30, 0, 0, 0)
    issue_time = LOCAL_TZ.localize(datetime(2026, 3, 30, 8, 0, 0)).isoformat()

    # Clear existing mock data
    cursor.execute("DELETE FROM price_forecasts WHERE issue_timestamp = ?", (issue_time,))

    # Realistic consumer price patterns (import prices with taxes/fees)
    # Range: ~0.50 kr/kWh (cheap nights) to ~2.50 kr/kWh (expensive peaks)
    daily_patterns = [
        {"base": 1.20, "var": 0.40, "label": "Today"},  # D+1 - Normal (~1.20 avg)
        {"base": 0.65, "var": 0.25, "label": "Tomorrow"},  # D+2 - CHEAP (~0.65, 45% drop!)
        {"base": 2.10, "var": 0.60, "label": "Wed"},  # D+3 - EXPENSIVE (~2.10)
        {"base": 0.85, "var": 0.30, "label": "Thu"},  # D+4 - Cheap (~0.85)
        {"base": 1.35, "var": 0.45, "label": "Fri"},  # D+5 - Normal (~1.35)
        {"base": 0.55, "var": 0.20, "label": "Sat"},  # D+6 - CHEAP (~0.55, 54% drop!)
        {"base": 1.45, "var": 0.50, "label": "Sun"},  # D+7 - Normal (~1.45)
    ]

    records = []
    for day_offset, pattern in enumerate(daily_patterns):
        for hour in range(24):
            slot_time = base_date + timedelta(days=day_offset, hours=hour)
            slot_start = LOCAL_TZ.localize(slot_time).isoformat()

            # Realistic hourly patterns for consumer prices
            hour_factor = 1.0
            if 6 <= hour <= 9:  # Morning peak
                hour_factor = 1.25
            elif 17 <= hour <= 20:  # Evening peak
                hour_factor = 1.40
            elif hour >= 23 or hour <= 5:  # Night low
                hour_factor = 0.70

            spot_p50 = pattern["base"] * hour_factor
            spot_p10 = max(0.25, spot_p50 * 0.65)  # Min price floor
            spot_p90 = spot_p50 * 1.50  # High uncertainty

            records.append(
                {
                    "slot_start": slot_start,
                    "issue_timestamp": issue_time,
                    "days_ahead": day_offset + 1,
                    "spot_p10": round(spot_p10, 4),
                    "spot_p50": round(spot_p50, 4),
                    "spot_p90": round(spot_p90, 4),
                    "wind_index": 0.5 + (day_offset * 0.1),  # Mock wind
                    "temperature_c": 8.0 - (day_offset * 0.5),  # Getting colder
                    "cloud_cover": 0.3 + (day_offset * 0.1),
                    "radiation_wm2": 200.0 if 6 <= hour <= 18 else 0.0,
                }
            )

    # Insert records
    cursor.executemany(
        """
        INSERT INTO price_forecasts
        (slot_start, issue_timestamp, days_ahead, spot_p10, spot_p50, spot_p90,
         wind_index, temperature_c, cloud_cover, radiation_wm2)
        VALUES
        (:slot_start, :issue_timestamp, :days_ahead, :spot_p10, :spot_p50, :spot_p90,
         :wind_index, :temperature_c, :cloud_cover, :radiation_wm2)
        """,
        records,
    )

    conn.commit()
    conn.close()

    print(f"✓ Inserted {len(records)} mock forecast records")
    print("  - 7 days of hourly forecasts (24h x 7d = 168 slots)")
    print(
        f"  - Price range: {min(r['spot_p50'] for r in records):.2f} - {max(r['spot_p50'] for r in records):.2f} kr/kWh"
    )
    print("\nRefresh your browser to see the Weekly Outlook widget with data!")


if __name__ == "__main__":
    insert_mock_forecasts()
