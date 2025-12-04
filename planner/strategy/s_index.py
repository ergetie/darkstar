"""
S-Index Calculation Module

Strategic Index calculation for dynamic load adjustment and risk assessment.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import pytz


def calculate_dynamic_s_index(
    df: pd.DataFrame,
    s_index_cfg: Dict[str, Any],
    max_factor: float,
    timezone_name: str,
    daily_pv_forecast: Optional[Dict[str, float]] = None,
    daily_load_forecast: Optional[Dict[str, float]] = None,
    fetch_temperature_fn: Optional[Callable[[List[int], Any], Dict[int, float]]] = None,
) -> Tuple[Optional[float], Dict[str, Any], Dict[int, float]]:
    """
    Compute dynamic S-index factor based on PV/load deficit and temperature.
    
    Args:
        df: DataFrame with load_forecast_kwh and pv_forecast_kwh columns
        s_index_cfg: S-index configuration from config.yaml
        max_factor: Maximum allowed S-index factor
        timezone_name: Timezone for date calculations
        daily_pv_forecast: Optional daily PV forecast map (date_str -> kwh)
        daily_load_forecast: Optional daily load forecast map (date_str -> kwh)
        fetch_temperature_fn: Optional callback to fetch temperature forecasts
        
    Returns:
        Tuple of (factor, debug_data, temps_map)
    """
    base_factor = float(s_index_cfg.get("base_factor", s_index_cfg.get("static_factor", 1.05)))
    pv_weight = float(s_index_cfg.get("pv_deficit_weight", 0.0))
    temp_weight = float(s_index_cfg.get("temp_weight", 0.0))
    temp_baseline = float(s_index_cfg.get("temp_baseline_c", 20.0))
    temp_cold = float(s_index_cfg.get("temp_cold_c", -15.0))

    # Determine days to check
    horizon_days = s_index_cfg.get("s_index_horizon_days")
    if horizon_days is not None:
        try:
            day_offsets = list(range(1, int(horizon_days) + 1))
        except (ValueError, TypeError):
            day_offsets = [1, 2, 3, 4]
    else:
        day_offsets = s_index_cfg.get("days_ahead_for_sindex", [1, 2, 3, 4])
        if not isinstance(day_offsets, (list, tuple)):
            day_offsets = [1, 2, 3, 4]

    normalized_days: List[int] = []
    for offset in day_offsets:
        try:
            offset_int = int(offset)
        except (TypeError, ValueError):
            continue
        if offset_int > 0:
            normalized_days.append(offset_int)

    normalized_days = sorted(set(normalized_days))
    if not normalized_days:
        return None, {"base_factor": base_factor, "reason": "no_valid_days"}, {}

    tz = pytz.timezone(timezone_name)
    try:
        local_index = df.index.tz_convert(tz)
    except TypeError:
        local_index = df.index.tz_localize(tz)
    local_dates = pd.Series(local_index.date, index=df.index)
    today = datetime.now(tz).date()

    daily_pv_map = daily_pv_forecast or {}
    daily_load_map = daily_load_forecast or {}

    deficits: List[float] = []
    considered_days: List[int] = []
    for offset in normalized_days:
        target_date = today + timedelta(days=offset)
        mask = local_dates == target_date
        if mask.any():
            considered_days.append(offset)
            load_sum = float(df.loc[mask, "load_forecast_kwh"].sum())
            pv_sum = float(df.loc[mask, "pv_forecast_kwh"].sum())
        else:
            key = target_date.isoformat()
            load_sum = float(daily_load_map.get(key, 0.0))
            pv_sum = float(daily_pv_map.get(key, 0.0))
            if load_sum <= 0 and pv_sum <= 0:
                continue
            considered_days.append(offset)

        if load_sum <= 0:
            deficits.append(0.0)
        else:
            ratio = max(0.0, (load_sum - pv_sum) / max(load_sum, 1e-6))
            deficits.append(ratio)

    if not considered_days:
        return None, {
            "base_factor": base_factor,
            "reason": "insufficient_forecast_data",
            "requested_days": normalized_days,
        }, {}

    avg_deficit = sum(deficits) / len(deficits) if deficits else 0.0

    temps_map: Dict[int, float] = {}
    mean_temp = None
    temp_adjustment = 0.0
    if temp_weight > 0 and fetch_temperature_fn is not None:
        temps_map = fetch_temperature_fn(considered_days, tz)
        temperature_values = [
            temps_map.get(offset)
            for offset in considered_days
            if temps_map.get(offset) is not None
        ]
        if temperature_values:
            mean_temp = sum(temperature_values) / len(temperature_values)
            span = temp_baseline - temp_cold
            if span <= 0:
                span = 1.0
            temp_adjustment = max(0.0, min(1.0, (temp_baseline - mean_temp) / span))

    raw_factor = base_factor + (pv_weight * avg_deficit) + (temp_weight * temp_adjustment)
    factor = min(max_factor, max(0.0, raw_factor))

    debug_data = {
        "mode": "dynamic",
        "base_factor": round(base_factor, 4),
        "avg_deficit": round(avg_deficit, 4),
        "pv_deficit_weight": round(pv_weight, 4),
        "temp_weight": round(temp_weight, 4),
        "temp_adjustment": round(temp_adjustment, 4),
        "mean_temperature_c": round(mean_temp, 2) if mean_temp is not None else None,
        "considered_days": considered_days,
        "requested_days": normalized_days,
        "temperatures": {str(k): v for k, v in temps_map.items()} if temps_map else None,
        "factor_unclamped": round(raw_factor, 4),
    }

    return factor, debug_data, temps_map


def calculate_future_risk_factor(
    df: pd.DataFrame,
    s_index_cfg: Dict[str, Any],
    timezone_name: str,
    fetch_temperature_fn: Optional[Callable[[List[int], Any], Dict[int, float]]] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate S-Index for the Future (D2) to determine Terminal Value.
    Uses D2 Temperature and PV forecasts.
    
    Args:
        df: DataFrame (used for fallback, not primary calculation)
        s_index_cfg: S-index configuration
        timezone_name: Timezone name
        fetch_temperature_fn: Optional callback to fetch temperature
        
    Returns:
        Tuple of (risk_factor, debug_data)
    """
    base_factor = float(s_index_cfg.get("base_factor", 1.05))
    max_factor = float(s_index_cfg.get("max_factor", 1.50))
    temp_weight = float(s_index_cfg.get("temp_weight", 0.0))
    temp_baseline = float(s_index_cfg.get("temp_baseline_c", 20.0))
    temp_cold = float(s_index_cfg.get("temp_cold_c", -15.0))
    
    tz = pytz.timezone(timezone_name)
    today = datetime.now(tz).date()
    d2_date = today + timedelta(days=2)
    
    # Fetch D2 Temperature
    temps_map: Dict[int, float] = {}
    if fetch_temperature_fn is not None:
        temps_map = fetch_temperature_fn([2], tz)
    d2_temp = temps_map.get(2)
    
    temp_adjustment = 0.0
    if d2_temp is not None and temp_weight > 0:
        span = temp_baseline - temp_cold
        if span <= 0:
            span = 1.0
        temp_adjustment = max(0.0, min(1.0, (temp_baseline - d2_temp) / span))
        
    raw_factor = base_factor + (temp_weight * temp_adjustment)
    risk_factor = min(max_factor, max(0.0, raw_factor))
    
    debug = {
        "d2_date": d2_date.isoformat(),
        "d2_temp_c": d2_temp,
        "temp_adjustment": round(temp_adjustment, 4),
        "risk_factor": round(risk_factor, 4)
    }
    return risk_factor, debug
