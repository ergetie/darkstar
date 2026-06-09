"""
Price forecasting feature engineering for Darkstar/Aurora.

This module provides feature extraction for the Nordpool spot price
forecasting model, including calendar features, price lags, and weather inputs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz
from dateutil.easter import easter

from backend.learning.models import SlotObservation
from utils.time_utils import dst_safe_date_range

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _is_swedish_holiday(date: datetime) -> bool:
    """
    Check if a date is a Swedish public holiday.

    Swedish public holidays: New Year's Day, Epiphany (Jan 6), Good Friday,
    Easter Monday, May 1 (Labour Day), Ascension Day, National Day (June 6),
    Midsummer's Eve, Midsummer's Day, All Saints' Day, Christmas Eve,
    Christmas Day, Boxing Day, New Year's Eve.

    For simplicity, we use a fixed list of dates. In production, you might
    want to use the `holidays` library.
    """
    # Simple fixed-date holidays
    month_day = (date.month, date.day)

    fixed_holidays = {
        (1, 1),  # New Year's Day
        (1, 6),  # Epiphany
        (5, 1),  # Labour Day
        (6, 6),  # National Day
        (12, 24),  # Christmas Eve
        (12, 25),  # Christmas Day
        (12, 26),  # Boxing Day
        (12, 31),  # New Year's Eve
    }

    if month_day in fixed_holidays:
        return True

    # Easter-based holidays (variable dates)
    # Convert datetime to date for comparison with easter() results
    date_only = date.date()
    easter_sunday = easter(date.year)

    # Good Friday (Friday before Easter Sunday)
    good_friday = easter_sunday - timedelta(days=2)
    if date_only == good_friday:
        return True

    # Easter Monday (Monday after Easter Sunday)
    easter_monday = easter_sunday + timedelta(days=1)
    if date_only == easter_monday:
        return True

    # Ascension Day (40 days after Easter Sunday, always Thursday)
    ascension_day = easter_sunday + timedelta(days=39)
    if date_only == ascension_day:
        return True

    # All Saints' Day (Saturday between Oct 31 and Nov 6)
    # Actually falls on the first Saturday of November in Sweden
    # But commonly observed on the Saturday between Oct 31 - Nov 6
    if date_only.month == 11:
        # Find the first Saturday of November
        from datetime import date as date_cls

        nov_1 = date_cls(date.year, 11, 1)
        days_until_saturday = (5 - nov_1.weekday()) % 7
        all_saints = nov_1 + timedelta(days=days_until_saturday)
        if date_only == all_saints:
            return True

    # Midsummer's Eve (Friday between June 19-25)
    if date.month == 6 and 19 <= date.day <= 25 and date.weekday() == 4:
        return True

    # Midsummer's Day (Saturday between June 20-26)
    return date.month == 6 and 20 <= date.day <= 26 and date.weekday() == 5


def build_price_features(
    slot_start: datetime,
    days_ahead: int,
    db_session: Session | None = None,
    wind_index: float | None = None,
    temperature_c: float | None = None,
    cloud_cover: float | None = None,
    radiation_wm2: float | None = None,
) -> dict[str, Any]:
    """
    Build feature dictionary for price forecasting.

    Args:
        slot_start: Target slot timestamp (timezone-aware)
        days_ahead: Number of days ahead this forecast is for (1-7)
        db_session: SQLAlchemy session for querying price lags (optional)
        wind_index: Regional wind index value
        temperature_c: Temperature in Celsius
        cloud_cover: Cloud cover percentage
        radiation_wm2: Shortwave radiation in W/m²

    Returns:
        Dictionary with feature names and values
    """
    # Ensure slot_start is timezone-aware
    if slot_start.tzinfo is None:
        slot_start = pytz.UTC.localize(slot_start)

    # Calendar features
    features: dict[str, Any] = {
        "hour": slot_start.hour,
        "day_of_week": slot_start.weekday(),  # 0=Monday, 6=Sunday
        "month": slot_start.month,
        "is_weekend": int(slot_start.weekday() >= 5),
        "is_holiday": int(_is_swedish_holiday(slot_start)),
        "days_ahead": days_ahead,
    }

    # Price lag features (query from database if session provided)
    if db_session is not None:
        price_lags = _get_price_lags(slot_start, db_session)
        features.update(price_lags)
    else:
        # Set to NaN if no database session
        features.update(
            {
                "price_lag_1d": float("nan"),
                "price_lag_7d": float("nan"),
                "price_lag_24h_avg": float("nan"),
            }
        )

    # Weather features
    features["wind_index"] = wind_index if wind_index is not None else float("nan")
    features["temperature_c"] = temperature_c if temperature_c is not None else float("nan")
    features["cloud_cover"] = cloud_cover if cloud_cover is not None else float("nan")
    features["radiation_wm2"] = radiation_wm2 if radiation_wm2 is not None else float("nan")

    return features


def _get_price_lags(
    slot_start: datetime,
    db_session: Session,
) -> dict[str, float]:
    """
    Query price lags from slot_observations.

    Returns price lags for:
    - price_lag_1d: Same hour yesterday
    - price_lag_7d: Same hour last week
    - price_lag_24h_avg: Trailing 24-hour average

    Missing values are returned as NaN.
    """
    lags: dict[str, float] = {
        "price_lag_1d": float("nan"),
        "price_lag_7d": float("nan"),
        "price_lag_24h_avg": float("nan"),
    }

    try:
        # Price lag 1 day ago (same hour)
        lag_1d_time = slot_start - timedelta(days=1)
        lag_1d_str = lag_1d_time.isoformat()

        result = (
            db_session.query(SlotObservation)
            .filter(SlotObservation.slot_start == lag_1d_str)
            .first()
        )

        if result and result.export_price_sek_kwh is not None:
            lags["price_lag_1d"] = result.export_price_sek_kwh

        # Price lag 7 days ago (same hour)
        lag_7d_time = slot_start - timedelta(days=7)
        lag_7d_str = lag_7d_time.isoformat()

        result = (
            db_session.query(SlotObservation)
            .filter(SlotObservation.slot_start == lag_7d_str)
            .first()
        )

        if result and result.export_price_sek_kwh is not None:
            lags["price_lag_7d"] = result.export_price_sek_kwh

        # Trailing 24-hour average
        # Get all slots in the 24 hours before lag_1d_time
        trailing_start = lag_1d_time - timedelta(hours=23)  # 24 hours total including lag_1d_time
        trailing_start_str = trailing_start.isoformat()

        results = (
            db_session.query(SlotObservation)
            .filter(
                SlotObservation.slot_start >= trailing_start_str,
                SlotObservation.slot_start <= lag_1d_str,
                SlotObservation.export_price_sek_kwh.isnot(None),
            )
            .all()
        )

        if results:
            prices = [r.export_price_sek_kwh for r in results if r.export_price_sek_kwh is not None]
            if prices:
                lags["price_lag_24h_avg"] = sum(prices) / len(prices)

    except Exception as exc:
        # Log error but return NaN values
        logger.warning("Error querying price lags: %s", exc)

    return lags


def build_price_features_batch(
    start_time: datetime,
    end_time: datetime,
    days_ahead: int,
    db_session: Session | None = None,
    weather_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build price features for a range of slots.

    Args:
        start_time: Start of the time window
        end_time: End of the time window
        days_ahead: Number of days ahead these forecasts are for
        db_session: SQLAlchemy session for querying price lags
        weather_df: DataFrame with weather features (wind_index, temp_c, cloud_cover, radiation)

    Returns:
        DataFrame with one row per slot and columns for each feature
    """
    # Ensure timezone-aware
    tz = start_time.tzinfo or pytz.UTC
    if start_time.tzinfo is None:
        start_time = pytz.UTC.localize(start_time)
    if end_time.tzinfo is None:
        end_time = pytz.UTC.localize(end_time)

    # Convert timezone to string for dst_safe_date_range
    tz_str = str(tz) if tz else "UTC"

    # Generate slot timestamps
    slots = dst_safe_date_range(start=start_time, end=end_time, freq="15min", tz=tz_str)

    records: list[dict[str, Any]] = []
    for slot in slots:
        # Get weather for this slot if available
        wind_index = None
        temp_c = None
        cloud_cover = None
        radiation = None

        if weather_df is not None and not weather_df.empty and slot in weather_df.index:
            row = weather_df.loc[slot]
            _wind = row.get("wind_index")
            _temp = row.get("temperature_c") or row.get("temp_c")
            _cloud = row.get("cloud_cover") or row.get("cloud_cover_pct")
            _rad = row.get("radiation_wm2") or row.get("shortwave_radiation_w_m2")

            # Ensure scalar values (not Series)
            if _wind is not None and not isinstance(_wind, pd.Series):
                wind_index = float(_wind)
            if _temp is not None and not isinstance(_temp, pd.Series):
                temp_c = float(_temp)
            if _cloud is not None and not isinstance(_cloud, pd.Series):
                cloud_cover = float(_cloud)
            if _rad is not None and not isinstance(_rad, pd.Series):
                radiation = float(_rad)

        features = build_price_features(
            slot_start=slot,
            days_ahead=days_ahead,
            db_session=db_session,
            wind_index=wind_index,
            temperature_c=temp_c,
            cloud_cover=cloud_cover,
            radiation_wm2=radiation,
        )

        features["slot_start"] = slot.isoformat()
        records.append(features)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if "slot_start" in df.columns:
        df.set_index("slot_start", inplace=True)

    return df
