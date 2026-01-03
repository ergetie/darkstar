"""
S-Index Calculation Module

Strategic Index calculation for dynamic load adjustment and risk assessment.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz


def calculate_dynamic_s_index(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    max_factor: float,
    timezone_name: str,
    daily_pv_forecast: dict[str, float] | None = None,
    daily_load_forecast: dict[str, float] | None = None,
    fetch_temperature_fn: Callable[[list[int], Any], dict[int, float]] | None = None,
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
        local_index = df.index.tz_convert(tz)
    except TypeError:
        local_index = df.index.tz_localize(tz)
    local_dates = pd.Series(local_index.date, index=df.index)
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
    mean_temp = None
    temp_adjustment = 0.0
    if temp_weight > 0 and fetch_temperature_fn is not None:
        temps_map = fetch_temperature_fn(considered_days, tz)
        temperature_values = [
            temps_map.get(offset) for offset in considered_days if temps_map.get(offset) is not None
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

    normalized_days: list[int] = sorted(set(int(d) for d in day_offsets if int(d) > 0))
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
        local_index = df.index.tz_convert(tz)
    except TypeError:
        local_index = df.index.tz_localize(tz)
    local_dates = pd.Series(local_index.date, index=df.index)

    total_uncertainty_kwh = 0.0
    total_load_p50 = 0.0
    considered_days = []
    data_source = []  # Track where data came from

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

    debug_data = {
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


def calculate_target_soc_risk_factor(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    fetch_temperature_fn: Callable[[list[int], Any], dict[int, float]] | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    Calculate risk factor for end-of-day target SOC.

    This function determines how much energy buffer to hold at end-of-day
    based on tomorrow's forecasted conditions and user's risk tolerance.

    Incorporates:
    - base_factor: Learned or configured baseline buffer
    - risk_appetite (1-5): Controls how aggressively to buffer
    - PV vs Load deficit: If tomorrow has low PV vs load, increase buffer
    - Temperature: Cold days may need more buffer (existing logic)

    Logic:
        1. Calculate PV deficit ratio for D1+D2: (load - pv) / load
           - Positive = deficit (need more buffer)
           - Negative = surplus (can reduce buffer if gambler mode)

        2. Apply risk_appetite via sigma scaling:
           - Safety (1): +1.28σ → higher buffer
           - Neutral (3): 0σ → baseline
           - Gambler (5): -0.67σ → lower buffer (can go below baseline)

        3. Combine: raw_factor = base + pv_deficit_contribution + temp_contribution
           - Apply sigma scaling to allow gambler mode to reduce below base

    Returns:
        Tuple of (risk_factor, debug_data)
    """
    # Configuration
    base_factor = float(s_index_cfg.get("base_factor", 1.05))
    max_factor = float(s_index_cfg.get("max_factor", 1.50))
    min_factor = float(s_index_cfg.get("min_factor", 0.8))  # Floor for gambler mode
    pv_deficit_weight = float(s_index_cfg.get("pv_deficit_weight", 0.2))
    temp_weight = float(s_index_cfg.get("temp_weight", 0.0))
    temp_baseline = float(s_index_cfg.get("temp_baseline_c", 20.0))
    temp_cold = float(s_index_cfg.get("temp_cold_c", -15.0))
    risk_appetite = int(s_index_cfg.get("risk_appetite", 3))

    # Sigma mapping (same as probabilistic s-index for consistency)
    RISK_SIGMA_MAP = {
        1: 1.28,  # Safety: +1.28σ
        2: 0.67,  # Conservative: +0.67σ
        3: 0.00,  # Neutral: 0σ
        4: -0.25,  # Aggressive: -0.25σ
        5: -0.67,  # Gambler: -0.67σ
    }
    target_sigma = RISK_SIGMA_MAP.get(risk_appetite, 0.0)

    tz = pytz.timezone(timezone_name)
    today = datetime.now(tz).date()

    # Ensure dataframe has timezone-aware index
    try:
        local_index = df.index.tz_convert(tz)
    except TypeError:
        local_index = df.index.tz_localize(tz)
    local_dates = pd.Series(local_index.date, index=df.index)

    # Calculate PV deficit for D1 and D2 (weighted: D1 more important)
    d1_date = today + timedelta(days=1)
    d2_date = today + timedelta(days=2)

    pv_deficit_ratio = 0.0
    d1_deficit = None
    d2_deficit = None
    total_load = 0.0
    total_pv = 0.0

    for offset, target_date, weight in [(1, d1_date, 0.7), (2, d2_date, 0.3)]:
        mask = local_dates == target_date
        if mask.any():
            load_sum = float(df.loc[mask, "load_forecast_kwh"].sum())
            pv_sum = float(df.loc[mask, "pv_forecast_kwh"].sum())
            total_load += load_sum
            total_pv += pv_sum

            if load_sum > 0:
                # Deficit ratio: positive = need more energy than PV provides
                # Negative = PV surplus
                deficit = (load_sum - pv_sum) / load_sum
                deficit = max(-1.0, min(1.0, deficit))  # Clamp to [-1, 1]

                if offset == 1:
                    d1_deficit = deficit
                else:
                    d2_deficit = deficit

                pv_deficit_ratio += weight * deficit

    # Temperature adjustment (same as before, but only additive)
    temps_map: dict[int, float] = {}
    if fetch_temperature_fn is not None:
        temps_map = fetch_temperature_fn([1, 2], tz)

    d1_temp = temps_map.get(1)
    d2_temp = temps_map.get(2)
    mean_temp = None
    temp_adjustment = 0.0

    if temp_weight > 0:
        temp_values = [t for t in [d1_temp, d2_temp] if t is not None]
        if temp_values:
            mean_temp = sum(temp_values) / len(temp_values)
            span = temp_baseline - temp_cold
            if span <= 0:
                span = 1.0
            # Cold → higher adjustment (add buffer), warm → 0
            temp_adjustment = max(0.0, min(1.0, (temp_baseline - mean_temp) / span))

    # Calculate raw factor before risk_appetite adjustment
    # PV deficit contribution: positive deficit → add buffer, surplus → reduce
    pv_contribution = pv_deficit_weight * pv_deficit_ratio
    temp_contribution = temp_weight * temp_adjustment

    raw_factor = base_factor + pv_contribution + temp_contribution

    # OPTION B: Apply weather volatility to the buffer BEFORE risk_appetite
    # This increases the base buffer during uncertain weather, but risk_appetite
    # buffer_multiplier still applies on top, so both factors work together.
    #
    # e.g. with cloud_vol=0.5: buffer increases by 20% (1 + 0.5 * 0.4)
    # Then risk_appetite=5 (Gambler) can STILL reduce it to near 0
    weather_vol = s_index_cfg.get("weather_volatility", {})
    cloud_vol = float(weather_vol.get("cloud", 0.0) or 0.0)
    temp_vol_adj = float(weather_vol.get("temp", 0.0) or 0.0)

    # Weather volatility amplifies the buffer above 1.0
    # MAX_WEATHER_BUFFER_AMPLIFICATION = 0.4 means at max volatility, buffer is 1.4x
    MAX_WEATHER_BUFFER_AMPLIFICATION = 0.4
    weather_amplification = 1.0 + max(cloud_vol, temp_vol_adj) * MAX_WEATHER_BUFFER_AMPLIFICATION

    buffer_before_weather = raw_factor - 1.0
    buffer_after_weather = buffer_before_weather * weather_amplification
    raw_factor_with_weather = 1.0 + buffer_after_weather

    # Apply risk_appetite via direct scaling of the buffer above 1.0
    #
    # The "buffer" is how much above 1.0 the raw_factor is.
    # risk_appetite controls what percentage of this buffer to use:
    #
    # - Safety (1): Use 150% of buffer → Higher target SOC
    # - Neutral (3): Use 100% of buffer → raw_factor unchanged
    # - Aggressive (4): Use 50% of buffer → Lower target SOC
    # - Gambler (5): Use ~10% of buffer → Target near min_soc (bet on cheap overnight!)
    #
    # The key insight: risk_factor = 1.0 means target SOC = min_soc_percent
    # So for Level 5, we want adjusted_factor → 1.0

    buffer_above_one = raw_factor_with_weather - 1.0

    # Direct mapping of risk_appetite to buffer multiplier
    # Negative values for Gambler mode allow targeting BELOW min_soc
    BUFFER_MULTIPLIER_MAP = {
        1: 1.5,  # Safety: 150% buffer (higher than neutral)
        2: 1.2,  # Conservative: 120% buffer
        3: 1.0,  # Neutral: 100% buffer (raw_factor)
        4: 0.5,  # Aggressive: 50% buffer
        5: -0.5,  # Gambler: NEGATIVE buffer (target below min_soc, bet on replan!)
    }
    buffer_multiplier = BUFFER_MULTIPLIER_MAP.get(risk_appetite, 1.0)

    adjusted_buffer = buffer_above_one * buffer_multiplier
    adjusted_factor = 1.0 + adjusted_buffer

    # Apply bounds
    # Gambler mode (risk_appetite=5) can go as low as min_factor
    # Safety mode is capped at max_factor
    risk_factor = min(max_factor, max(min_factor, adjusted_factor))

    debug = {
        "mode": "target_soc_risk",
        "base_factor": round(base_factor, 4),
        "risk_appetite": risk_appetite,
        "target_sigma": target_sigma,
        "d1_date": d1_date.isoformat(),
        "d2_date": d2_date.isoformat(),
        "d1_deficit_ratio": round(d1_deficit, 4) if d1_deficit is not None else None,
        "d2_deficit_ratio": round(d2_deficit, 4) if d2_deficit is not None else None,
        "pv_deficit_ratio_weighted": round(pv_deficit_ratio, 4),
        "pv_contribution": round(pv_contribution, 4),
        "total_load_kwh": round(total_load, 2),
        "total_pv_kwh": round(total_pv, 2),
        "d1_temp_c": d1_temp,
        "d2_temp_c": d2_temp,
        "mean_temp_c": round(mean_temp, 1) if mean_temp is not None else None,
        "temp_adjustment": round(temp_adjustment, 4),
        "temp_contribution": round(temp_contribution, 4),
        "raw_factor": round(raw_factor, 4),
        "weather_volatility": {
            "cloud": round(cloud_vol, 2),
            "temp": round(temp_vol_adj, 2),
            "amplification": round(weather_amplification, 4),
        },
        "raw_factor_with_weather": round(raw_factor_with_weather, 4),
        "buffer_above_one": round(buffer_above_one, 4),
        "buffer_multiplier": round(buffer_multiplier, 4),
        "adjusted_buffer": round(adjusted_buffer, 4),
        "adjusted_factor": round(adjusted_factor, 4),
        "risk_factor": round(risk_factor, 4),
    }
    return risk_factor, debug


# Keep old function as alias for backwards compatibility
def calculate_future_risk_factor(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    fetch_temperature_fn: Callable[[list[int], Any], dict[int, float]] | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    DEPRECATED: Use calculate_target_soc_risk_factor instead.

    This function is kept for backwards compatibility but now delegates
    to the new function that properly incorporates risk_appetite and PV deficit.
    """
    return calculate_target_soc_risk_factor(df, s_index_cfg, timezone_name, fetch_temperature_fn)


def calculate_dynamic_target_soc(
    risk_factor: float,
    battery_config: dict[str, Any],
    s_index_cfg: dict[str, Any],
    raw_factor: float | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """
    Calculate Dynamic Target SoC based on risk_appetite level.

    NEW APPROACH (Rev K16):
    - Each risk level has a FIXED base buffer above min_soc
    - Weather/PV deficit adjustments are added on top (capped at ±8%)
    - Weather adjustment is INDEPENDENT of risk level (uses raw_factor)
    - This guarantees: Level 1 > Level 2 > Level 3 > Level 4 > Level 5 (ALWAYS)

    Args:
        risk_factor: Final risk factor (kept for backwards compatibility)
        battery_config: Battery configuration
        s_index_cfg: S-index configuration
        raw_factor: Raw weather/PV factor BEFORE buffer_multiplier (used for adjustment)

    Returns:
        Tuple of (target_soc_pct, target_soc_kwh, debug_data)
    """
    min_soc_pct = float(battery_config.get("min_soc_percent", 10.0))
    risk_appetite = int(s_index_cfg.get("risk_appetite", 3))

    # FIXED base buffer per risk level (percentage points above min_soc)
    # These are the user's expected targets regardless of weather
    # Tuned for: Level 3 → ~30% winter, ~20% summer (with min_soc=12%)
    LEVEL_BUFFER_MAP = {
        1: 35.0,  # Safety: +35% above min_soc
        2: 20.0,  # Conservative: +20%
        3: 10.0,  # Neutral: +10%
        4: 3.0,  # Aggressive: +3%
        5: -7.0,  # Gambler: -7% (target below min_soc, bet on MPC replan!)
    }
    base_buffer = LEVEL_BUFFER_MAP.get(risk_appetite, 10.0)

    # Weather/PV deficit adjustment (derived from RAW factor, not modified risk_factor)
    # This ensures weather adjustment is INDEPENDENT of risk level selection
    # raw_factor > 1.0 = risky conditions (high load/low PV) = add buffer
    # raw_factor < 1.0 = favorable conditions (low load/high PV) = reduce buffer
    # Cap the adjustment to ±8% to prevent extreme swings
    weather_base = raw_factor if raw_factor is not None else risk_factor
    weather_adjustment = (weather_base - 1.0) * 40.0  # Scale to percentage points
    weather_adjustment = max(-8.0, min(8.0, weather_adjustment))

    # Final target = min_soc + fixed_buffer + weather_adjustment
    target_soc_pct = min_soc_pct + base_buffer + weather_adjustment

    # Absolute floor at 5% to prevent dangerous states
    target_soc_pct = max(5.0, min(100.0, target_soc_pct))

    capacity_kwh = float(battery_config.get("capacity_kwh", 0.0))
    target_soc_kwh = (target_soc_pct / 100.0) * capacity_kwh if capacity_kwh > 0 else 0.0

    debug = {
        "risk_appetite": risk_appetite,
        "raw_factor": round(weather_base, 4),
        "base_buffer_pct": base_buffer,
        "weather_adjustment_pct": round(weather_adjustment, 2),
        "target_percent": round(target_soc_pct, 2),
        "target_kwh": round(target_soc_kwh, 2),
    }

    return target_soc_pct, target_soc_kwh, debug
