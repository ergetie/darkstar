"""
Data Preparation Module

Functions for building and preprocessing DataFrames from price and forecast data.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import pytz
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError


def normalize_timestamp(value: Any, tz_name: str) -> pd.Timestamp:
    """
    Return a timezone-aware timestamp normalized to the requested timezone.
    
    Args:
        value: Any datetime-like value (string, datetime, Timestamp)
        tz_name: Target timezone name (e.g., "Europe/Stockholm")
        
    Returns:
        Timezone-aware pd.Timestamp, or pd.NaT if value is None
    """
    tz = pytz.timezone(tz_name)
    if value is None:
        return pd.NaT
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        dt = ts.to_pydatetime()
        try:
            localized = tz.localize(dt)
        except (AmbiguousTimeError, NonExistentTimeError):
            localized = tz.localize(dt, is_dst=True)
        return pd.Timestamp(localized)
    return ts.tz_convert(tz)


def build_price_dataframe(price_data: list, tz_name: str) -> pd.DataFrame:
    """
    Build the price DataFrame indexed by the localized start_time.
    
    Args:
        price_data: List of price slot dictionaries with start_time, import/export prices
        tz_name: Timezone name for normalization
        
    Returns:
        DataFrame indexed by start_time with end_time, import_price_sek_kwh, export_price_sek_kwh
    """
    if not price_data:
        empty_idx = pd.DatetimeIndex([], tz=pytz.timezone(tz_name))
        return pd.DataFrame(
            columns=["end_time", "import_price_sek_kwh", "export_price_sek_kwh"],
            index=empty_idx,
        )

    records = []
    for slot in price_data:
        start = normalize_timestamp(slot.get("start_time"), tz_name)
        end = normalize_timestamp(slot.get("end_time"), tz_name)
        if start is pd.NaT:
            continue
        records.append(
            {
                "start_time": start,
                "end_time": end,
                "import_price_sek_kwh": float(slot.get("import_price_sek_kwh") or 0.0),
                "export_price_sek_kwh": float(
                    slot.get("export_price_sek_kwh") or slot.get("import_price_sek_kwh") or 0.0
                ),
            }
        )

    if not records:
        empty_idx = pd.DatetimeIndex([], tz=pytz.timezone(tz_name))
        return pd.DataFrame(
            columns=["end_time", "import_price_sek_kwh", "export_price_sek_kwh"],
            index=empty_idx,
        )

    df = pd.DataFrame(records)
    df = df.set_index("start_time").sort_index()
    return df


def build_forecast_dataframe(forecast_data: list, tz_name: str) -> pd.DataFrame:
    """
    Build forecast DataFrame indexed by localized start_time with PV/load columns.
    
    Args:
        forecast_data: List of forecast slot dictionaries with pv_forecast_kwh, load_forecast_kwh
        tz_name: Timezone name for normalization
        
    Returns:
        DataFrame indexed by start_time with pv_forecast_kwh, load_forecast_kwh
    """
    empty_idx = pd.DatetimeIndex([], tz=pytz.timezone(tz_name))
    if not forecast_data:
        return pd.DataFrame(
            columns=["pv_forecast_kwh", "load_forecast_kwh"],
            index=empty_idx,
        )

    records = []
    for slot in forecast_data:
        start = normalize_timestamp(slot.get("start_time"), tz_name)
        if start is pd.NaT:
            continue
        records.append(
            {
                "start_time": start,
                "pv_forecast_kwh": float(slot.get("pv_forecast_kwh") or 0.0),
                "load_forecast_kwh": float(slot.get("load_forecast_kwh") or 0.0),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=["pv_forecast_kwh", "load_forecast_kwh"],
            index=empty_idx,
        )

    df = pd.DataFrame(records)
    df = df.set_index("start_time").sort_index()
    return df


def prepare_df(input_data: Dict[str, Any], tz_name: Optional[str] = None) -> pd.DataFrame:
    """
    Merge price and forecast feeds by timestamp and return a timezone-aware DataFrame.

    Args:
        input_data: Dictionary containing ``price_data`` and ``forecast_data``.
        tz_name: Optional timezone override (defaults to Europe/Stockholm).

    Returns:
        A DataFrame indexed by ``start_time`` with import/export prices and PV/load forecasts.
    """
    timezone_str = tz_name or input_data.get("timezone") or "Europe/Stockholm"
    price_df = build_price_dataframe(input_data.get("price_data") or [], timezone_str)
    forecast_df = build_forecast_dataframe(input_data.get("forecast_data") or [], timezone_str)

    df = price_df.join(
        forecast_df[["pv_forecast_kwh", "load_forecast_kwh"]],
        how="left",
    )
    df["pv_forecast_kwh"] = df["pv_forecast_kwh"].fillna(0.0)
    df["load_forecast_kwh"] = df["load_forecast_kwh"].ffill().fillna(0.0)
    return df.sort_index()



def apply_safety_margins(
    df: pd.DataFrame,
    config: Dict[str, Any],
    overlays: Dict[str, Any],
    effective_load_margin: float,
) -> pd.DataFrame:
    """
    Apply safety margins to PV and load forecasts.
    
    Args:
        df: DataFrame with forecasts
        config: Full configuration dictionary
        overlays: Learning overlays dictionary
        effective_load_margin: Calculated load inflation factor (S-Index)
        
    Returns:
        DataFrame with adjusted forecasts (adjusted_pv_kwh, adjusted_load_kwh)
    """
    forecasting = config.get("forecasting", {})
    pv_confidence = forecasting.get("pv_confidence_percent", 90.0) / 100.0

    df["adjusted_pv_kwh"] = df["pv_forecast_kwh"] * pv_confidence
    df["adjusted_load_kwh"] = df["load_forecast_kwh"] * effective_load_margin

    # Apply per-hour learning adjustments if available
    pv_adj = overlays.get("pv_adjustment_by_hour_kwh")
    load_adj = overlays.get("load_adjustment_by_hour_kwh")
    
    if pv_adj or load_adj:
        try:
            timezone_name = config.get("timezone", "Europe/Stockholm")
            tz = pytz.timezone(timezone_name)
        except Exception:
            tz = pytz.timezone("Europe/Stockholm")

        try:
            local_index = df.index.tz_convert(tz)
        except TypeError:
            local_index = df.index.tz_localize(tz)

        hours = local_index.hour
        if pv_adj:
            if len(pv_adj) == 24:
                # Apply adjustment and clamp to 0 to prevent negative PV
                raw_pv = df["adjusted_pv_kwh"] + hours.map(lambda h: float(pv_adj[h])).values
                df["adjusted_pv_kwh"] = raw_pv.clip(lower=0.0)
        if load_adj:
            if len(load_adj) == 24:
                # Apply adjustment and clamp to 0 to prevent negative load
                raw_adjusted = (
                    df["adjusted_load_kwh"] + hours.map(lambda h: float(load_adj[h])).values
                )
                df["adjusted_load_kwh"] = raw_adjusted.clip(lower=0.0)

    return df


# Legacy aliases for backward compatibility
_normalize_timestamp = normalize_timestamp
_build_price_dataframe = build_price_dataframe
_build_forecast_dataframe = build_forecast_dataframe

