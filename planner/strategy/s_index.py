"""
S-Index Calculation Module

Strategic Index calculation for dynamic load adjustment and risk assessment.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz

from planner.strategy.price_reserve import (
    PriceReserveResult,
    evaluate_price_reserve,
    inactive_price_reserve,
    reserve_threshold_sek,
)
from utils.time_utils import dst_safe_localize

if TYPE_CHECKING:
    from collections.abc import Callable

    from planner.strategy.price_reserve import PriceReserveInputs


async def calculate_dynamic_s_index(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    max_factor: float,
    timezone_name: str,
    daily_pv_forecast: dict[str, float] | None = None,
    daily_load_forecast: dict[str, float] | None = None,
    fetch_temperature_fn: Callable[[list[int], Any], Any] | None = None,
) -> tuple[float | None, dict[str, Any], dict[int, float]]:
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

    # Determine days to check (s_index_horizon_days is the single source of truth)
    horizon_days = s_index_cfg.get("s_index_horizon_days", 4)
    try:
        day_offsets = list(range(1, int(horizon_days) + 1))
    except (ValueError, TypeError):
        day_offsets = [1, 2, 3, 4]

    normalized_days: list[int] = []
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
        local_index: pd.DatetimeIndex = df.index.tz_convert(tz)  # type: ignore[assignment]
    except TypeError:
        local_index = dst_safe_localize(df.index, tz)  # type: ignore[assignment]
    local_dates: pd.Series = pd.Series(local_index.date, index=df.index)  # type: ignore[arg-type]
    today = datetime.now(tz).date()

    daily_pv_map = daily_pv_forecast or {}
    daily_load_map = daily_load_forecast or {}

    deficits: list[float] = []
    considered_days: list[int] = []
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
        return (
            None,
            {
                "base_factor": base_factor,
                "reason": "insufficient_forecast_data",
                "requested_days": normalized_days,
            },
            {},
        )

    avg_deficit = sum(deficits) / len(deficits) if deficits else 0.0

    temps_map: dict[int, float] = {}
    mean_temp: float | None = None
    temp_adjustment = 0.0
    if temp_weight > 0 and fetch_temperature_fn is not None:
        temps_map = await fetch_temperature_fn(considered_days, tz)
        temperature_values = [
            temps_map.get(offset) for offset in considered_days if temps_map.get(offset) is not None
        ]
        if temperature_values:
            mean_temp = sum(temperature_values) / len(temperature_values)  # type: ignore[assignment]
            span = temp_baseline - temp_cold
            if span <= 0:
                span = 1.0
            temp_adjustment = max(0.0, min(1.0, (temp_baseline - mean_temp) / span))  # type: ignore[arg-type]

    raw_factor = base_factor + (pv_weight * avg_deficit) + (temp_weight * temp_adjustment)
    factor = min(max_factor, max(0.0, raw_factor))

    debug_data: dict[str, Any] = {
        "mode": "dynamic",
        "base_factor": round(base_factor, 4),
        "avg_deficit": round(avg_deficit, 4),
        "pv_deficit_weight": round(pv_weight, 4),
        "temp_weight": round(temp_weight, 4),
        "temp_adjustment": round(temp_adjustment, 4),
        "mean_temperature_c": round(mean_temp, 2) if mean_temp is not None else None,  # type: ignore[arg-type]
        "considered_days": considered_days,
        "requested_days": normalized_days,
        "temperatures": {str(k): v for k, v in temps_map.items()} if temps_map else None,
        "factor_unclamped": round(raw_factor, 4),
    }

    return factor, debug_data, temps_map


def calculate_probabilistic_s_index(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    max_factor: float,
    timezone_name: str,
    daily_probabilistic: dict[str, dict[str, float]] | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """
    Compute S-index factor using Sigma Scaling (Rev A28).

    Logic:
        1. Calculate Uncertainty (Sigma Proxy): (Load_p90 - Load_p50) + (PV_p50 - PV_p10)
        2. Map User 'risk_appetite' (1-5) to Target Sigma.
        3. Safety Margin = Uncertainty * Target Sigma
        4. Target Load = Load_p50 + Safety Margin
        5. Factor = Target Load / Load_p50

    Args:
        df: DataFrame with slot forecasts (may only cover price horizon)
        s_index_cfg: S-Index configuration dict
        max_factor: Maximum allowed factor
        timezone_name: Timezone for date calculations
        daily_probabilistic: Optional extended daily probabilistic aggregates for days
                             beyond price horizon. Structure:
                             {"pv_p10": {"2024-01-01": 1.5, ...}, "pv_p90": {...},
                              "load_p10": {...}, "load_p90": {...}}
    """
    # 1. Configuration with Defaults
    # Support legacy base_factor if risk_appetite is missing, but prefer appetite.
    risk_appetite = int(s_index_cfg.get("risk_appetite", 3))

    # Sigma Mapping (1=Safety to 5=Gambler)
    # 1: p90 (+1.28 sigma)
    # 2: p75 (+0.67 sigma)
    # 3: p50 (0.00 sigma) - Neutral
    # 4: p40 (-0.25 sigma)
    # 5: p25 (-0.67 sigma)
    RISK_SIGMA_MAP = {1: 1.28, 2: 0.67, 3: 0.00, 4: -0.25, 5: -0.67}
    target_sigma = RISK_SIGMA_MAP.get(risk_appetite, 0.0)

    # Determine days to check (s_index_horizon_days is the single source of truth)
    horizon_days = s_index_cfg.get("s_index_horizon_days", 4)
    try:
        day_offsets = list(range(1, int(horizon_days) + 1))
    except (ValueError, TypeError):
        day_offsets = [1, 2, 3, 4]

    normalized_days: list[int] = sorted({int(d) for d in day_offsets if int(d) > 0})
    if not normalized_days:
        return None, {"mode": "probabilistic", "reason": "no_valid_days"}

    tz = pytz.timezone(timezone_name)
    today = datetime.now(tz).date()

    # Check for probabilistic columns in df (for price horizon slots)
    has_probs_in_df = all(col in df.columns for col in ["load_p90", "load_p10", "pv_p90", "pv_p10"])

    # Also check extended data availability
    daily_probs = daily_probabilistic or {}
    has_extended = all(k in daily_probs for k in ["load_p10", "load_p90", "pv_p10", "pv_p90"])

    if not has_probs_in_df and not has_extended:
        return None, {"mode": "probabilistic", "reason": "missing_probabilistic_columns"}

    # Ensure dataframe has datetime index with correct timezone
    try:
        local_index: pd.DatetimeIndex = df.index.tz_convert(tz)  # type: ignore[assignment]
    except TypeError:
        local_index = dst_safe_localize(df.index, tz)  # type: ignore[assignment]
    local_dates: pd.Series = pd.Series(local_index.date, index=df.index)  # type: ignore[arg-type]

    total_uncertainty_kwh = 0.0
    total_load_p50 = 0.0
    considered_days: list[int] = []
    data_source: list[str] = []  # Track where data came from

    for offset in normalized_days:
        target_date = today + timedelta(days=offset)
        date_key = target_date.isoformat()
        mask = local_dates == target_date

        # Try to get data from df first (price horizon slots)
        if mask.any() and has_probs_in_df:
            # Calculate daily sums from slot-level data
            l_p50 = df.loc[mask, "load_forecast_kwh"].sum()
            l_p90 = df.loc[mask, "load_p90"].sum()
            p_p50 = df.loc[mask, "pv_forecast_kwh"].sum()
            p_p10 = df.loc[mask, "pv_p10"].sum()
            source = "slots"
        elif has_extended and date_key in daily_probs.get("load_p90", {}):
            # Fall back to extended daily aggregates (p50 values are available)
            l_p50 = daily_probs.get("load_p50", {}).get(date_key, 0.0)
            l_p90 = daily_probs.get("load_p90", {}).get(date_key, 0.0)
            p_p50 = daily_probs.get("pv_p50", {}).get(date_key, 0.0)
            p_p10 = daily_probs.get("pv_p10", {}).get(date_key, 0.0)
            source = "extended"
        else:
            # No data for this day
            continue

        considered_days.append(offset)
        data_source.append(source)

        # Uncertainty components (Standard Deviation Proxy)
        # We define Uncertainty = (Load_Upside_Risk) + (PV_Downside_Risk)
        load_sigma = max(0.0, l_p90 - l_p50)
        pv_sigma = max(0.0, p_p50 - p_p10)

        total_uncertainty_kwh += load_sigma + pv_sigma
        total_load_p50 += l_p50

    if not considered_days or total_load_p50 <= 0:
        return None, {
            "mode": "probabilistic",
            "reason": "insufficient_data_or_zero_load",
            "considered_days": considered_days,
        }

    # Sigma Scaling Calculation
    safety_margin_kwh = total_uncertainty_kwh * target_sigma
    target_load_kwh = total_load_p50 + safety_margin_kwh

    # Calculate derived factor (Plan / Baseline)
    # Clamp to reasonable physics (e.g., 0.5x minimum to avoid divide-by-zero or zeroing out usage)
    target_load_kwh = max(total_load_p50 * 0.5, target_load_kwh)

    raw_factor = target_load_kwh / total_load_p50

    # Apply Configured Max Cap (Safety Guardrail)
    factor = min(max_factor, raw_factor)

    # Note: We explicitly DO NOT floor at 1.0 anymore (User request).
    # But we ensure it's non-negative above.

    debug_data: dict[str, Any] = {
        "mode": "probabilistic_sigma_scaling",
        "risk_appetite": risk_appetite,
        "target_sigma": target_sigma,
        "considered_days": considered_days,
        "data_sources": data_source,
        "total_load_p50": round(total_load_p50, 2),
        "total_uncertainty_kwh": round(total_uncertainty_kwh, 2),
        "safety_margin_kwh": round(safety_margin_kwh, 2),
        "target_load_kwh": round(target_load_kwh, 2),
        "raw_factor": round(raw_factor, 4),
        "clamped_factor": round(factor, 4),
    }

    return factor, debug_data


# ------------------------------------------------------------------
# REV K23 Phase 3: Physical Deficit Logic (S-Index Refactor)
# ------------------------------------------------------------------


def calculate_deficit_ratio(
    total_load: float,
    total_pv: float,
) -> float:
    """
    Calculate the physical energy deficit ratio.

    Ratio = (Load - PV) / Load

    - Ratio > 0: Deficit (Load > PV) -> Need safety buffer
    - Ratio <= 0: Surplus (PV >= Load) -> No safety buffer needed (0)

    Args:
        total_load: Sum of load forecast (kWh)
        total_pv: Sum of PV forecast (kWh)

    Returns:
        float: Deficit ratio [0.0, 1.0] (Clamped at 0)
    """
    if total_load <= 0:
        return 0.0

    deficit = total_load - total_pv
    if deficit <= 0:
        return 0.0

    return min(1.0, deficit / total_load)


def calculate_temporal_deficit(df: pd.DataFrame) -> float:
    """
    Calculate temporal (per-slot) deficit: sum(max(0, load - pv)) for each slot.

    This captures the energy the battery must provide when PV is unavailable,
    regardless of aggregate surplus/deficit over the entire horizon.

    Args:
        df: DataFrame with 'load_forecast_kwh' and 'pv_forecast_kwh' columns

    Returns:
        Total temporal deficit in kWh
    """
    if df.empty:
        return 0.0

    load = df["load_forecast_kwh"]
    pv = df["pv_forecast_kwh"]

    # Per-slot net deficit: max(0, load - pv)
    slot_deficit = (load - pv).clip(lower=0.0)

    return float(slot_deficit.sum())


def calculate_safety_floor(
    df: pd.DataFrame,
    battery_config: dict[str, Any],
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    fetch_temperature_fn: Callable[[list[int], Any], Any] | None = None,
    full_forecast_df: pd.DataFrame | None = None,
    price_horizon_end: datetime | pd.Timestamp | None = None,
    price_reserve_inputs: PriceReserveInputs | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    Calculate the Safety Floor (Min kWh) based on Temporal Deficit.

    Temporal Safety Floor Logic:
    1. Calculate temporal deficit over 24h window beyond price horizon:
       sum(max(0, load - pv)) per slot
    2. Apply risk margin to the deficit (higher risk = lower margin)
    3. Add minimum floor per risk level (ensures floor never collapses to min_soc)
    4. Add weather buffer (temp, snow, clouds)
    5. Cap at max_safety_buffer_pct

    Args:
        df: DataFrame with 'load_forecast_kwh', 'pv_forecast_kwh', etc. (price-truncated)
        battery_config: Battery config (capacity, min_soc)
        s_index_cfg: Strategy config (risk_appetite, max_safety_buffer_pct)
        timezone_name: Timezone string
        fetch_temperature_fn: Callback for weather data
        full_forecast_df: Full forecast DataFrame extending beyond price horizon
        price_horizon_end: Timestamp where price data ends (start of look-ahead window)
        price_reserve_inputs: Inputs for the first-unseen-day price reserve, or None
            when price forecasting is disabled (the reserve is then 0).

    Returns:
        Tuple of (final_floor_kwh, debug_data). The final floor is
        ``max(safety_floor, min_soc + price_reserve)`` clamped to
        ``[min_soc, max_soc]``: the reserve never lowers the deficit-based floor
        and is never added on top of it.
    """
    import logging

    logger = logging.getLogger("darkstar.planner")

    # 1. Config & Inputs
    capacity_kwh = float(battery_config.get("capacity_kwh", 13.5))
    min_soc_pct = float(battery_config.get("min_soc_percent", 5.0))
    min_soc_kwh = (min_soc_pct / 100.0) * capacity_kwh

    max_soc_kwh = (float(battery_config.get("max_soc_percent", 100.0)) / 100.0) * capacity_kwh

    risk_appetite = int(s_index_cfg.get("risk_appetite", 3))

    # Max buffer as % of capacity (default 20%, Risk 3 / Neutral baseline; scaled
    # per risk level below via cap_scale to prevent runaway)
    max_safety_buffer_pct = float(s_index_cfg.get("max_safety_buffer_percent", 20.0)) / 100.0

    # 2. Risk Configuration: margin on deficit + minimum floor above min_soc +
    # cap_scale (multiplier applied to max_safety_buffer_pct for this risk level)
    # Risk 1 (Safety): 30% margin, minimum 25% capacity buffer, 1.50x cap
    # Risk 2 (Conservative): 20% margin, minimum 15% capacity buffer, 1.25x cap
    # Risk 3 (Neutral): 15% margin, minimum 10% capacity buffer, 1.00x cap (baseline)
    # Risk 4 (Aggressive): 5% margin, minimum 3% capacity buffer, 0.85x cap
    # Risk 5 (Gambler): 0% margin, 0% minimum (returns min_soc), 0.75x cap
    RISK_CONFIG = {
        1: {"margin": 1.30, "min_buffer_pct": 0.25, "cap_scale": 1.50},  # Safety
        2: {"margin": 1.20, "min_buffer_pct": 0.15, "cap_scale": 1.25},  # Conservative
        3: {"margin": 1.15, "min_buffer_pct": 0.10, "cap_scale": 1.00},  # Neutral
        4: {"margin": 1.05, "min_buffer_pct": 0.03, "cap_scale": 0.85},  # Aggressive
        5: {"margin": 1.00, "min_buffer_pct": 0.00, "cap_scale": 0.75},  # Gambler
    }

    risk_config = RISK_CONFIG.get(risk_appetite, RISK_CONFIG[3])
    risk_margin = risk_config["margin"]
    min_buffer_kwh = capacity_kwh * risk_config["min_buffer_pct"]
    cap_scale = risk_config["cap_scale"]

    # Effective cap: scale the configured (Risk 3 baseline) cap per risk level,
    # then floor it at this risk level's own minimum buffer so the promised
    # min_buffer_pct can never be suppressed by the cap.
    max_buffer_kwh = capacity_kwh * max_safety_buffer_pct * cap_scale
    max_buffer_kwh = max(max_buffer_kwh, min_buffer_kwh)

    # 3. Determine the look-ahead window (24h beyond price horizon)
    lookahead_start: datetime | pd.Timestamp
    using_extended_data = False
    fallback_warning = False

    if price_horizon_end is not None:
        lookahead_start = price_horizon_end
    elif not df.empty and isinstance(df.index, pd.DatetimeIndex):
        # Fallback: use end of current df
        lookahead_start = df.index[-1]
        logger.warning(
            "Temporal Safety Floor: price_horizon_end not provided, using last timestamp of df"
        )
    elif df.empty:
        # No data available
        logger.warning("Temporal Safety Floor: No forecast data available, using minimum floor")
        safety_floor_kwh = min_soc_kwh + min_buffer_kwh
        return safety_floor_kwh, {
            "method": "temporal_deficit",
            "temporal_deficit_kwh": 0.0,
            "risk_appetite": risk_appetite,
            "risk_margin": risk_margin,
            "min_buffer_kwh": round(min_buffer_kwh, 2),
            "base_reserve_kwh": 0.0,
            "weather_buffer_kwh": 0.0,
            "max_buffer_kwh": round(max_buffer_kwh, 2),
            "cap_scale": cap_scale,
            "min_soc_kwh": round(min_soc_kwh, 2),
            "calculated_floor_kwh": round(safety_floor_kwh, 2),
            "fallback": "no_data",
            **_price_reserve_debug(
                inactive_price_reserve("no_known_window"),
                risk_appetite,
                None,
                None,
                safety_floor_kwh,
                safety_floor_kwh,
                None,
            ),
        }
    else:
        # Has data but no DatetimeIndex (e.g., test DataFrames)
        # Use a default lookahead window
        lookahead_start = datetime.now(pytz.timezone(timezone_name))
        logger.debug(
            "Temporal Safety Floor: Using current time as lookahead start (no DatetimeIndex)"
        )

    lookahead_end = lookahead_start + timedelta(hours=24)

    # 4. Calculate temporal deficit over the look-ahead window
    temporal_deficit_kwh = 0.0
    deficit_df: pd.DataFrame | None = None

    # Try to use extended forecast data beyond price horizon
    if full_forecast_df is not None and not full_forecast_df.empty:
        # Filter to the look-ahead window
        # Cast timestamps for proper type compatibility with DatetimeIndex
        start_ts = pd.Timestamp(lookahead_start)
        end_ts = pd.Timestamp(lookahead_end)
        mask = (full_forecast_df.index > start_ts) & (full_forecast_df.index <= end_ts)
        deficit_df = full_forecast_df.loc[mask].copy()

        if not deficit_df.empty:
            temporal_deficit_kwh = calculate_temporal_deficit(deficit_df)
            using_extended_data = True

    # Fallback: if extended data not available or insufficient, use available df
    if not using_extended_data:
        fallback_warning = True

        # Try to use as much of df as falls within the lookahead window
        # Only filter by timestamp if df has a DatetimeIndex
        if not df.empty and isinstance(df.index, pd.DatetimeIndex):
            # Cast to Timestamp for proper type compatibility
            start_ts = pd.Timestamp(lookahead_start)
            end_ts = pd.Timestamp(lookahead_end)
            mask = (df.index > start_ts) & (df.index <= end_ts)
            deficit_df = df.loc[mask].copy()

            if not deficit_df.empty:
                temporal_deficit_kwh = calculate_temporal_deficit(deficit_df)
        elif not df.empty:
            # No DatetimeIndex - use entire df (for backwards compatibility in tests)
            deficit_df = df.copy()
            temporal_deficit_kwh = calculate_temporal_deficit(deficit_df)

        if fallback_warning:
            logger.warning(
                "Temporal Safety Floor: Extended forecast data unavailable or insufficient, "
                "using available horizon only. Look-ahead window: %s to %s",
                lookahead_start,
                lookahead_end,
            )

    # 5. Calculate Base Reserve
    # Base reserve = temporal deficit * risk margin
    # This is the energy we want to preserve for the period beyond the horizon
    base_reserve_kwh = temporal_deficit_kwh * risk_margin

    # 6. Weather Buffer (Explicit adders)
    weather_buffer_kwh = 0.0
    weather_debug: dict[str, float] = {}

    # Use the deficit_df if available for weather data, otherwise use df
    weather_source_df = deficit_df if deficit_df is not None and not deficit_df.empty else df

    if not weather_source_df.empty:
        # A. Temperature (Cold = High risk)
        avg_temp = 20.0
        if "temperature_c" in weather_source_df.columns:
            avg_temp = float(weather_source_df["temperature_c"].mean())

        if avg_temp < 0:
            weather_buffer_kwh += 1.0  # Sub-zero
            weather_debug["temp_adder"] = 1.0
        if avg_temp < -10:
            weather_buffer_kwh += 1.0  # Extreme cold (Total +2.0)
            weather_debug["temp_adder"] = 2.0

        # B. Snow (If available in forecast)
        if "snow_prob" in weather_source_df.columns:
            snow_hours = int((weather_source_df["snow_prob"] > 50).sum())
            if snow_hours > 0:
                snow_adder = 0.5 * (snow_hours / 24.0)
                weather_buffer_kwh += snow_adder
                weather_debug["snow_adder"] = round(snow_adder, 2)

        # C. Cloud Cover (High clouds = PV uncertainty)
        if "cloud_cover" in weather_source_df.columns:
            avg_cloud = float(weather_source_df["cloud_cover"].mean())
            if avg_cloud > 70:
                weather_buffer_kwh += 0.5
                weather_debug["cloud_adder"] = 0.5

    # 7. Calculate Final Floor
    # Floor = min_soc + max(temporal_deficit_reserve, min_buffer) + weather_buffer
    # The minimum buffer ensures we never collapse to min_soc even with zero deficit
    effective_reserve = max(base_reserve_kwh, min_buffer_kwh)

    raw_floor = min_soc_kwh + effective_reserve + weather_buffer_kwh

    # Apply max_safety_buffer_pct cap to total buffer above min_soc
    safety_floor_kwh = min(raw_floor, min_soc_kwh + max_buffer_kwh)

    # Clamp to physical limits (can't exceed capacity)
    safety_floor_kwh = max(min_soc_kwh, min(capacity_kwh, safety_floor_kwh))

    debug: dict[str, Any] = {
        "method": "temporal_deficit",
        "temporal_deficit_kwh": round(temporal_deficit_kwh, 2),
        "lookahead_start": str(lookahead_start),
        "lookahead_end": str(lookahead_end),
        "using_extended_data": using_extended_data,
        "fallback_warning": fallback_warning,
        "risk_appetite": risk_appetite,
        "risk_margin": risk_margin,
        "min_buffer_kwh": round(min_buffer_kwh, 2),
        "base_reserve_kwh": round(base_reserve_kwh, 2),
        "effective_reserve_kwh": round(effective_reserve, 2),
        "weather_buffer_kwh": round(weather_buffer_kwh, 2),
        "weather_details": weather_debug,
        "max_buffer_kwh": round(max_buffer_kwh, 2),
        "cap_scale": cap_scale,
        "min_soc_kwh": round(min_soc_kwh, 2),
        "calculated_floor_kwh": round(safety_floor_kwh, 2),
    }

    # Price reserve for the first unseen day (the 24 h after the price horizon, the
    # same window as the deficit above). Combined with max(), never added: the
    # deficit floor already reserves energy for that same window.
    reserve = evaluate_price_reserve(
        price_reserve_inputs,
        full_forecast_df,
        lookahead_start,
        lookahead_end,
        risk_appetite=risk_appetite,
        min_soc_kwh=min_soc_kwh,
        max_soc_kwh=max_soc_kwh,
    )
    final_floor_kwh = max(
        min_soc_kwh, min(max_soc_kwh, max(safety_floor_kwh, min_soc_kwh + reserve.reserve_kwh))
    )

    debug.update(
        _price_reserve_debug(
            reserve,
            risk_appetite,
            lookahead_start,
            lookahead_end,
            safety_floor_kwh,
            final_floor_kwh,
            price_reserve_inputs.forecast_issue_timestamp if price_reserve_inputs else None,
        )
    )

    return final_floor_kwh, debug


def _price_reserve_debug(
    reserve: PriceReserveResult,
    risk_appetite: int,
    window_start: datetime | pd.Timestamp | None,
    window_end: datetime | pd.Timestamp | None,
    safety_floor_kwh: float,
    final_floor_kwh: float,
    forecast_issue_timestamp: str | None,
) -> dict[str, Any]:
    """Price reserve debug fields; every key is present whether or not the reserve is active."""
    applied = max(0.0, final_floor_kwh - safety_floor_kwh)
    debug: dict[str, Any] = {
        "price_reserve_active": reserve.active,
        "price_reserve_reason": reserve.reason,
        "price_reserve_threshold_sek": reserve_threshold_sek(risk_appetite),
        "unseen_window_start": str(window_start) if window_start is not None else None,
        "unseen_window_end": str(window_end) if window_end is not None else None,
        "known_cost_sek_kwh": reserve.known_cost_sek_kwh,
        "own_day_cost_sek_kwh": reserve.own_day_cost_sek_kwh,
        "price_reserve_kwh": round(reserve.reserve_kwh, 3),
        "price_reserve_applied_kwh": round(applied, 3),
        "forecast_issue_timestamp": forecast_issue_timestamp,
        "final_floor_kwh": round(final_floor_kwh, 2),
    }
    if reserve.capped_by is not None:
        debug["price_reserve_capped_by"] = reserve.capped_by
    return debug
