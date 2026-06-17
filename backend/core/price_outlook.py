"""
Price outlook helpers for daily price forecasts.

Provides aggregation functions to convert per-slot forecasts into daily summaries
suitable for the Weekly Outlook UI widget.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

import pytz

from backend.core.forecasts import get_forecast_db_path

logger = logging.getLogger("darkstar.price_outlook")


def get_daily_outlook(db_path: str | None = None) -> list[dict[str, Any]]:
    """
    Query price_forecasts DB table and aggregate per-slot p10/p50/p90 into daily summaries.

    Returns daily summaries for D+1 through D+7 with:
    - date: ISO date string
    - day_label: short weekday name (Mon, Tue, etc.)
    - days_ahead: integer 1-7
    - avg_spot_p50: daily mean of p50 forecasts
    - avg_spot_p10: daily mean of p10 forecasts
    - avg_spot_p90: daily mean of p90 forecasts
    - min_hour_p50: minimum p50 value for the day
    - max_hour_p50: maximum p50 value for the day

    Args:
        db_path: Path to the SQLite database. If None, uses default learning DB.

    Returns:
        List of daily summary dicts, sorted by date (D+1 to D+7).
        Returns empty list if no forecast data exists.
    """
    import sqlite3

    if db_path is None:
        db_path = get_forecast_db_path()

    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Query price forecasts from the latest forecast run
        cursor.execute("""
            SELECT slot_start, days_ahead, spot_p10, spot_p50, spot_p90
            FROM price_forecasts
            WHERE days_ahead BETWEEN 1 AND 7
              AND issue_timestamp = (SELECT MAX(issue_timestamp) FROM price_forecasts)
            ORDER BY slot_start
        """)

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        # Group by date and aggregate
        daily_data: dict[str, dict[str, Any]] = {}

        for row in rows:
            slot_start = row["slot_start"]
            days_ahead = row["days_ahead"]
            spot_p10 = row["spot_p10"]
            spot_p50 = row["spot_p50"]
            spot_p90 = row["spot_p90"]

            # Parse date from slot_start (ISO format)
            try:
                slot_dt = datetime.fromisoformat(slot_start.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                # Fallback for non-ISO formats
                try:
                    slot_dt = datetime.strptime(slot_start[:10], "%Y-%m-%d")
                except (ValueError, AttributeError):
                    continue

            date_str = slot_dt.strftime("%Y-%m-%d")
            day_label = slot_dt.strftime("%a")

            if date_str not in daily_data:
                daily_data[date_str] = {
                    "date": date_str,
                    "day_label": day_label,
                    "days_ahead": days_ahead,
                    "p50_values": [],
                    "p10_values": [],
                    "p90_values": [],
                }

            # Collect values for aggregation
            if spot_p50 is not None:
                daily_data[date_str]["p50_values"].append(spot_p50)
            if spot_p10 is not None:
                daily_data[date_str]["p10_values"].append(spot_p10)
            if spot_p90 is not None:
                daily_data[date_str]["p90_values"].append(spot_p90)

        # Calculate today's date in configured timezone
        tz_name = "Europe/Stockholm"
        try:
            from backend.core.secrets import load_yaml

            config = load_yaml("config.yaml")
            tz_name = config.get("timezone", "Europe/Stockholm")
        except Exception:
            pass
        tz = pytz.timezone(tz_name)
        today_str = datetime.now(tz).strftime("%Y-%m-%d")

        # Calculate aggregates for each day
        result: list[dict[str, Any]] = []
        for date_str in sorted(daily_data.keys()):
            day_data = daily_data[date_str]

            # Filter out stale dates (before today)
            if date_str < today_str:
                continue

            # Recalculate days_ahead from actual date difference
            days_ahead = (
                datetime.strptime(date_str, "%Y-%m-%d").date() - datetime.now(tz).date()
            ).days

            p50_values = day_data["p50_values"]
            p10_values = day_data["p10_values"]
            p90_values = day_data["p90_values"]

            if not p50_values:
                continue

            result.append(
                {
                    "date": day_data["date"],
                    "day_label": day_data["day_label"],
                    "days_ahead": days_ahead,
                    "avg_spot_p50": sum(p50_values) / len(p50_values),
                    "avg_spot_p10": sum(p10_values) / len(p10_values) if p10_values else None,
                    "avg_spot_p90": sum(p90_values) / len(p90_values) if p90_values else None,
                    "min_hour_p50": min(p50_values),
                    "max_hour_p50": max(p50_values),
                }
            )

        # Deduplicate by date, keep first occurrence (SQL ordered by slot_start DESC,
        # so the last aggregate wins for duplicate dates from multiple forecast runs)
        seen_dates: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for entry in reversed(result):
            if entry["date"] not in seen_dates:
                seen_dates.add(entry["date"])
                deduped.append(entry)
        deduped.reverse()

        # Sort by date and limit to 7 days
        deduped.sort(key=lambda x: x["date"])
        result = deduped[:7]

        return result

    except sqlite3.Error as e:
        logger.warning(f"Database error in get_daily_outlook: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error in get_daily_outlook: {e}")
        return []


def get_trailing_avg(db_path: str | None = None) -> float | None:
    """
    Query slot_observations.export_price_sek_kwh for the most recent 14 days and return the mean.

    Returns None if fewer than 2 days of data exist.
    Uses whatever history is available if between 2 and 13 days.

    Args:
        db_path: Path to the SQLite database. If None, uses default learning DB.

    Returns:
        Mean export price over trailing period, or None if insufficient data.
    """
    import sqlite3

    if db_path is None:
        db_path = get_forecast_db_path()

    try:
        conn = sqlite3.connect(db_path, timeout=30)
        cursor = conn.cursor()

        # Get the most recent 14 days of daily average prices
        # We need to aggregate by day first, then take the mean of daily averages
        cursor.execute("""
            SELECT
                DATE(slot_start) as day,
                AVG(export_price_sek_kwh) as avg_price
            FROM slot_observations
            WHERE export_price_sek_kwh IS NOT NULL
            GROUP BY DATE(slot_start)
            ORDER BY day DESC
            LIMIT 14
        """)

        rows = cursor.fetchall()
        conn.close()

        if len(rows) < 2:
            return None

        # Calculate mean of daily averages
        daily_avgs = [row[1] for row in rows if row[1] is not None]

        if not daily_avgs:
            return None

        return sum(daily_avgs) / len(daily_avgs)

    except sqlite3.Error as e:
        logger.warning(f"Database error in get_trailing_avg: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error in get_trailing_avg: {e}")
        return None


async def async_get_daily_outlook(db_path: str | None = None) -> list[dict[str, Any]]:
    return await asyncio.to_thread(get_daily_outlook, db_path)


async def async_get_trailing_avg(db_path: str | None = None) -> float | None:
    return await asyncio.to_thread(get_trailing_avg, db_path)


def classify_level(avg_spot_p50: float, reference_avg: float | None) -> str:
    """
    Classify a day's price level relative to the reference average.

    Args:
        avg_spot_p50: The day's average spot price (p50)
        reference_avg: The trailing average reference price, or None

    Returns:
        "cheap" if < 85% of reference
        "normal" if 85-115% of reference
        "expensive" if > 115% of reference
        "unknown" if reference is None
    """
    if reference_avg is None or reference_avg == 0:
        return "unknown"

    ratio = avg_spot_p50 / reference_avg

    if ratio < 0.85:
        return "cheap"
    elif ratio > 1.15:
        return "expensive"
    else:
        return "normal"


def classify_confidence(days_ahead: int) -> str:
    """
    Map days_ahead to confidence level.

    Args:
        days_ahead: Integer days ahead (1-7)

    Returns:
        "high" for D+1/D+2
        "medium" for D+3/D+4
        "low" for D+5-D+7
    """
    if days_ahead <= 2:
        return "high"
    elif days_ahead <= 4:
        return "medium"
    else:
        return "low"


def build_outlook_response(
    daily_outlook: list[dict[str, Any]], reference_avg: float | None, enabled: bool
) -> dict[str, Any]:
    """
    Build the complete outlook response with classifications.

    Args:
        daily_outlook: Raw daily outlook data from get_daily_outlook()
        reference_avg: Trailing average price or None
        enabled: Whether price forecasting is enabled

    Returns:
        Formatted response dict ready for JSON serialization.
    """
    if not enabled:
        return {"enabled": False, "days": [], "reference_avg": None, "status": "disabled"}

    if not daily_outlook:
        return {"enabled": True, "days": [], "reference_avg": reference_avg, "status": "no_data"}

    # Add classifications to each day
    days_with_classification: list[dict[str, Any]] = []
    for day in daily_outlook:
        day_copy = dict(day)
        day_copy["level"] = classify_level(day["avg_spot_p50"], reference_avg)
        day_copy["confidence"] = classify_confidence(day["days_ahead"])
        days_with_classification.append(day_copy)

    return {
        "enabled": True,
        "days": days_with_classification,
        "reference_avg": reference_avg,
        "status": "ok",
    }
