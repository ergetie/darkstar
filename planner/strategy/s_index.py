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

from utils.time_utils import dst_safe_localize

if TYPE_CHECKING:
    from collections.abc import Callable


# Risk-level scaling for the price floor addon (Module 3, design Decision 4).
# Fraction of battery capacity added to the safety floor per 1 SEK/kWh weighted
# spread. Risk appetite is the single user-facing lever — no config knob.
RISK_PRICE_KW_FRACTION: dict[int, float] = {
    1: 0.15,  # Safety:       15% of capacity per SEK/kWh weighted spread
    2: 0.12,  # Conservative: 12% of capacity per SEK/kWh weighted spread
    3: 0.10,  # Neutral:      10% of capacity per SEK/kWh weighted spread
    4: 0.05,  # Aggressive:    5% of capacity per SEK/kWh weighted spread
    5: 0.02,  # Gambler:       2% of capacity per SEK/kWh weighted spread
}

# Time-proximity decay for the price signal: weight(d) = 0.5 ** ((d - 1) / half_life).
# Half-life 2 days matches the battery's realistic 1-2 day bridging horizon
# (a spike counts fully at D+1, half at D+3, ~13% at D+7). See design Decision 2.
PRICE_PROXIMITY_HALF_LIFE_DAYS: float = 2.0


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


async def calculate_target_soc_risk_factor(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    daily_pv_forecast: dict[str, float] | None = None,
    daily_load_forecast: dict[str, float] | None = None,
    fetch_temperature_fn: Callable[[list[int], Any], Any] | None = None,
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
           - Safety (1): +1.28 sigma → higher buffer
           - Neutral (3): 0 sigma → baseline
           - Gambler (5): -0.67 sigma → lower buffer (can go below baseline)

        3. Combine: raw_factor = base + pv_deficit_contribution + temp_contribution
           - Apply sigma scaling to allow gambler mode to reduce below base

    Args:
        df: DataFrame with price slots (may only cover today)
        s_index_cfg: S-Index configuration dict
        timezone_name: Timezone for date calculations
        daily_pv_forecast: Daily PV totals by date key (ISO format) for extended horizon
        daily_load_forecast: Daily load totals by date key (ISO format) for extended horizon
        fetch_temperature_fn: Optional callback to fetch temperature forecasts

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
        1: 1.28,  # Safety: +1.28 sigma
        2: 0.67,  # Conservative: +0.67 sigma
        3: 0.00,  # Neutral: 0 sigma
        4: -0.25,  # Aggressive: -0.25 sigma
        5: -0.67,  # Gambler: -0.67 sigma
    }
    target_sigma = RISK_SIGMA_MAP.get(risk_appetite, 0.0)

    tz = pytz.timezone(timezone_name)
    today = datetime.now(tz).date()

    # Ensure dataframe has timezone-aware index
    try:
        local_index: pd.DatetimeIndex = df.index.tz_convert(tz)  # type: ignore[assignment]
    except TypeError:
        local_index = dst_safe_localize(df.index, tz)  # type: ignore[assignment]
    local_dates: pd.Series = pd.Series(local_index.date, index=df.index)  # type: ignore[arg-type]

    # Calculate PV deficit for D1 and D2 (weighted: D1 more important)
    d1_date = today + timedelta(days=1)
    d2_date = today + timedelta(days=2)

    pv_deficit_ratio = 0.0
    d1_deficit = None
    d2_deficit = None
    total_load = 0.0
    total_pv = 0.0

    for offset, target_date, weight in [(1, d1_date, 0.7), (2, d2_date, 0.3)]:
        date_key = target_date.isoformat()
        mask = local_dates == target_date

        # Try slot-level data from df first
        if mask.any():
            load_sum = float(df.loc[mask, "load_forecast_kwh"].sum())
            pv_sum = float(df.loc[mask, "pv_forecast_kwh"].sum())
        # Fall back to daily aggregates from Aurora extended horizon
        elif daily_load_forecast and daily_pv_forecast:
            load_sum = float(daily_load_forecast.get(date_key, 0.0))
            pv_sum = float(daily_pv_forecast.get(date_key, 0.0))
            if load_sum > 0 or pv_sum > 0:
                pass
            else:
                continue
        else:
            continue

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
        temps_map = await fetch_temperature_fn([1, 2], tz)

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
async def calculate_future_risk_factor(
    df: pd.DataFrame,
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    daily_pv_forecast: dict[str, float] | None = None,
    daily_load_forecast: dict[str, float] | None = None,
    fetch_temperature_fn: Callable[[list[int], Any], Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    DEPRECATED: Use calculate_target_soc_risk_factor instead.

    This function is kept for backwards compatibility but now delegates
    to the new function that properly incorporates risk_appetite and PV deficit.
    """
    return await calculate_target_soc_risk_factor(
        df,
        s_index_cfg,
        timezone_name,
        daily_pv_forecast=daily_pv_forecast,
        daily_load_forecast=daily_load_forecast,
        fetch_temperature_fn=fetch_temperature_fn,
    )


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


def calculate_price_floor_addon(
    upcoming_daily_avg_spots: dict[int, float],  # days-ahead (1..7) -> avg spot p50 (SEK/kWh)
    trailing_avg_spot: float | None,  # 14-day trailing avg (SEK/kWh)
    capacity_kwh: float,
    risk_appetite: int,
) -> tuple[float, dict[str, Any]]:
    """
    Compute the price-driven safety floor addon (Module 3, design Decision 2/3/4).

    The addon is `capacity_kwh * weighted_spread_sek * risk_fraction`, where the
    weighted spread is the maximum proximity-weighted daily spread across forecast
    days D+1..D+7 against the trailing 14-day average. The signal may be negative
    (cheap period ahead) — the caller clamps it to zero effect (additive only).

    Args:
        upcoming_daily_avg_spots: days-ahead offset (int) -> daily avg spot p50.
        trailing_avg_spot: 14-day trailing average spot price (SEK/kWh), or None.
        capacity_kwh: Battery capacity in kWh.
        risk_appetite: Risk appetite level (1..5).

    Returns:
        Tuple of (price_addon_kwh, debug_dict). The addon may be negative; it is
        the caller's responsibility to clamp it asymmetrically when applying it to
        the safety floor. The debug dict reports ``price_adjustment_active`` and
        either the full computation details or a reason for inactivity.
    """
    if not upcoming_daily_avg_spots:
        return 0.0, {
            "price_adjustment_active": False,
            "price_adjustment_reason": "insufficient_forecast_data",
        }
    if trailing_avg_spot is None or trailing_avg_spot <= 0:
        return 0.0, {
            "price_adjustment_active": False,
            "price_adjustment_reason": "insufficient_historical_data",
        }

    driving_day = 0
    raw_spread_sek = 0.0
    proximity_weight = 0.0
    weighted_spread_sek: float | None = None
    driving_day_spot = 0.0

    for d, spot in upcoming_daily_avg_spots.items():
        try:
            d_int = int(d)
            spot_f = float(spot)
        except (TypeError, ValueError):
            continue
        if d_int <= 0 or spot_f < 0:
            continue

        weight_d = 0.5 ** ((d_int - 1) / PRICE_PROXIMITY_HALF_LIFE_DAYS)
        spread_d = (spot_f - trailing_avg_spot) * weight_d

        if weighted_spread_sek is None or spread_d > weighted_spread_sek:
            weighted_spread_sek = spread_d
            driving_day = d_int
            raw_spread_sek = spot_f - trailing_avg_spot
            proximity_weight = weight_d
            driving_day_spot = spot_f

    if weighted_spread_sek is None:
        return 0.0, {
            "price_adjustment_active": False,
            "price_adjustment_reason": "insufficient_forecast_data",
        }

    risk_fraction = RISK_PRICE_KW_FRACTION.get(risk_appetite, 0.10)
    price_addon_kwh = capacity_kwh * weighted_spread_sek * risk_fraction

    debug: dict[str, Any] = {
        "price_adjustment_active": True,
        "price_spread_sek": weighted_spread_sek,
        "raw_spread_sek": raw_spread_sek,
        "driving_day_offset": driving_day,
        "proximity_weight": proximity_weight,
        "peak_upcoming_spot_sek": driving_day_spot,
        "trailing_avg_spot_sek": trailing_avg_spot,
        "price_addon_kwh": price_addon_kwh,
        "price_reserve_fraction": risk_fraction,
    }
    return price_addon_kwh, debug


def calculate_safety_floor(
    df: pd.DataFrame,
    battery_config: dict[str, Any],
    s_index_cfg: dict[str, Any],
    timezone_name: str,
    fetch_temperature_fn: Callable[[list[int], Any], Any] | None = None,
    full_forecast_df: pd.DataFrame | None = None,
    price_horizon_end: datetime | pd.Timestamp | None = None,
    upcoming_daily_avg_spots: dict[int, float] | None = None,  # days-ahead (1..7) -> avg spot p50
    trailing_avg_spot: float | None = None,
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
        upcoming_daily_avg_spots: Optional days-ahead (1..7) -> daily avg spot p50 map.
            When provided alongside ``trailing_avg_spot`` and ``price_forecast.enabled``
            is true, a Layer 2 price addon is applied to the capped safety floor.
            The addon is additive only (negative addons clamp to zero effect).
        trailing_avg_spot: Optional 14-day trailing average spot price (SEK/kWh).

    Returns:
        Tuple of (final_floor_kwh, debug_data). When price data is provided the
        returned value includes the Layer 2 addon; otherwise it equals the existing
        Layer 1 ``safety_floor_kwh`` byte-for-byte.
    """
    import logging

    logger = logging.getLogger("darkstar.planner")

    # 1. Config & Inputs
    capacity_kwh = float(battery_config.get("capacity_kwh", 13.5))
    min_soc_pct = float(battery_config.get("min_soc_percent", 5.0))
    min_soc_kwh = (min_soc_pct / 100.0) * capacity_kwh

    risk_appetite = int(s_index_cfg.get("risk_appetite", 3))

    # Max buffer as % of capacity (default 20% to prevent runaway)
    max_safety_buffer_pct = float(s_index_cfg.get("max_safety_buffer_percent", 20.0)) / 100.0
    max_buffer_kwh = capacity_kwh * max_safety_buffer_pct

    # 2. Risk Configuration: margin on deficit + minimum floor above min_soc
    # Risk 1 (Safety): 30% margin, minimum 25% capacity buffer
    # Risk 2 (Conservative): 20% margin, minimum 15% capacity buffer
    # Risk 3 (Neutral): 15% margin, minimum 10% capacity buffer
    # Risk 4 (Aggressive): 5% margin, minimum 3% capacity buffer
    # Risk 5 (Gambler): 0% margin, 0% minimum (returns min_soc)
    RISK_CONFIG = {
        1: {"margin": 1.30, "min_buffer_pct": 0.25},  # Safety
        2: {"margin": 1.20, "min_buffer_pct": 0.15},  # Conservative
        3: {"margin": 1.15, "min_buffer_pct": 0.10},  # Neutral
        4: {"margin": 1.05, "min_buffer_pct": 0.03},  # Aggressive
        5: {"margin": 1.00, "min_buffer_pct": 0.00},  # Gambler
    }

    risk_config = RISK_CONFIG.get(risk_appetite, RISK_CONFIG[3])
    risk_margin = risk_config["margin"]
    min_buffer_kwh = capacity_kwh * risk_config["min_buffer_pct"]

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
            "min_soc_kwh": round(min_soc_kwh, 2),
            "calculated_floor_kwh": round(safety_floor_kwh, 2),
            "fallback": "no_data",
            "price_adjustment_active": False,
            "price_adjustment_reason": "disabled_or_no_data",
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
        "min_soc_kwh": round(min_soc_kwh, 2),
        "calculated_floor_kwh": round(safety_floor_kwh, 2),
    }

    # Layer 2: price floor addon (applied after existing 20% cap, additive only).
    # The price signal can only RAISE the floor, never lower it. A negative addon
    # (cheap period ahead) is computed for debug visibility but clamped to zero
    # effect so price optimisation never undercuts the deficit-based safety floor.
    final_floor_kwh = safety_floor_kwh
    if upcoming_daily_avg_spots is not None and trailing_avg_spot is not None:
        price_addon_kwh, price_debug = calculate_price_floor_addon(
            upcoming_daily_avg_spots, trailing_avg_spot, capacity_kwh, risk_appetite
        )
        # Asymmetric clamp: lower bound is the Layer 1 safety floor, not min_soc.
        final_floor_kwh = max(
            safety_floor_kwh,
            min(safety_floor_kwh + price_addon_kwh, 0.80 * capacity_kwh),
        )
        debug.update(price_debug)
        debug["price_addon_applied_kwh"] = final_floor_kwh - safety_floor_kwh
        debug["final_floor_kwh"] = round(final_floor_kwh, 2)

        # Strategy log: only when the floor is meaningfully raised (negative addons
        # produce no event since they have no effect on the floor).
        if price_addon_kwh >= 0.5:
            try:
                from backend.strategy.history import append_strategy_event

                peak_upcoming_sek = float(price_debug.get("peak_upcoming_spot_sek", 0.0))
                raw_spread_sek = float(price_debug.get("raw_spread_sek", 0.0))
                weighted_spread_sek = float(price_debug.get("price_spread_sek", 0.0))
                driving_day = int(price_debug.get("driving_day_offset", 0))
                append_strategy_event(
                    event_type="STRATEGY_CHANGE",
                    message=(
                        f"Price signal: {peak_upcoming_sek:.2f} SEK/kWh forecast in D+{driving_day} "
                        f"({raw_spread_sek:+.2f} vs trailing avg, {weighted_spread_sek:+.2f} weighted) "
                        f"→ floor raised by {price_addon_kwh:.1f} kWh"
                    ),
                    details={
                        "price_spread_sek": weighted_spread_sek,
                        "raw_spread_sek": raw_spread_sek,
                        "driving_day_offset": driving_day,
                        "price_addon_kwh": price_addon_kwh,
                        "peak_upcoming_spot_sek": peak_upcoming_sek,
                    },
                )
            except Exception as exc:
                logger.warning("Failed to log price strategy event: %s", exc)
    else:
        debug["price_adjustment_active"] = False
        debug["price_adjustment_reason"] = "disabled_or_no_data"

    return final_floor_kwh, debug
