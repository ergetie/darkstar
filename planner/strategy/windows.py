"""
Window Identification Strategy

Logic for identifying cheap charging windows based on price thresholds and dynamic expansion.
"""

import math
import pandas as pd
from typing import Any, Dict, Tuple


def identify_windows(
    df: pd.DataFrame, config: Dict[str, Any], initial_state: Dict[str, Any], now_slot: Any
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Identify cheap windows with Dynamic Expansion (Smart Thresholds).

    Args:
        df: DataFrame with import_price_sek_kwh
        config: Full configuration dictionary
        initial_state: Initial battery state
        now_slot: Current time slot

    Returns:
        Tuple of (df with is_cheap column, debug_data)
    """
    df = df.copy()

    charging_strategy = config.get("charging_strategy", {})
    battery_config = config.get("battery", {})
    strategic_charging = config.get("strategic_charging", {})
    manual_planning = config.get("manual_planning", {}) or {}

    # 1. Basic Config
    charge_threshold_percentile = float(charging_strategy.get("charge_threshold_percentile", 15))
    cheap_price_tolerance_sek = float(charging_strategy.get("cheap_price_tolerance_sek", 0.10))
    price_smoothing_sek_kwh = float(charging_strategy.get("price_smoothing_sek_kwh", 0.05))

    # 2. Calculate Baseline Threshold
    if "import_price_sek_kwh" not in df.columns:
        df["is_cheap"] = False
        return df, {}

    quantile_value = df["import_price_sek_kwh"].quantile(charge_threshold_percentile / 100.0)
    if pd.isna(quantile_value):
        quantile_value = df["import_price_sek_kwh"].dropna().median() or 0.0

    # Initial mask
    initial_cheap = df["import_price_sek_kwh"] <= quantile_value

    # Refine threshold based on tolerance
    cheap_subset = df.loc[initial_cheap, "import_price_sek_kwh"]
    max_price_in_initial = cheap_subset.max() if not cheap_subset.empty else quantile_value
    baseline_threshold = max_price_in_initial + cheap_price_tolerance_sek + price_smoothing_sek_kwh

    # -------------------------------------------------------
    # DYNAMIC WINDOW EXPANSION (Smart Thresholds)
    # -------------------------------------------------------
    final_threshold = baseline_threshold

    # A. Calculate Required Energy
    capacity_kwh = float(battery_config.get("capacity_kwh", 10.0))
    max_soc_percent = float(battery_config.get("max_soc_percent", 100))

    # Use manual override if present, else config target
    target_percent = manual_planning.get("charge_target_percent")
    if target_percent is None:
        target_percent = float(strategic_charging.get("target_soc_percent", max_soc_percent))

    current_kwh = float(initial_state.get("battery_kwh", 0.0))
    if "battery_soc_percent" in initial_state and "battery_kwh" not in initial_state:
        current_kwh = (float(initial_state["battery_soc_percent"]) / 100.0) * capacity_kwh

    target_kwh = (target_percent / 100.0) * capacity_kwh

    # Deficit we need to cover
    deficit_kwh = max(0.0, target_kwh - current_kwh)

    # B. Calculate Available Capacity in Baseline Window
    # Only look at future slots (from now_slot)
    future_mask = df.index >= now_slot

    # Max charge per slot (kWh)
    max_charge_kw = float(battery_config.get("max_charge_power_kw", 5.0))
    slot_kwh_limit = max_charge_kw * 0.25

    # Count slots currently marked as cheap
    baseline_cheap_mask = (df["import_price_sek_kwh"] <= baseline_threshold) & future_mask
    baseline_slots_count = baseline_cheap_mask.sum()
    baseline_capacity_kwh = baseline_slots_count * slot_kwh_limit

    # C. Expand if Deficit Exists
    expanded = False
    if deficit_kwh > baseline_capacity_kwh:
        needed_slots = math.ceil(deficit_kwh / slot_kwh_limit)
        # Find the price of the Nth cheapest slot in the future
        future_prices = df.loc[future_mask, "import_price_sek_kwh"].sort_values()

        if not future_prices.empty and needed_slots > 0:
            idx = min(len(future_prices) - 1, needed_slots - 1)
            target_price = future_prices.iloc[idx]

            expanded_threshold = max(baseline_threshold, target_price + 0.0001)
            final_threshold = expanded_threshold
            expanded = True

    # Step D: Final is_cheap Application
    df["is_cheap"] = (df["import_price_sek_kwh"] <= final_threshold).fillna(False).astype(bool)

    debug_data = {
        "baseline_threshold": baseline_threshold,
        "final_threshold": final_threshold,
        "expanded": expanded,
        "deficit_kwh": deficit_kwh,
        "baseline_capacity_kwh": baseline_capacity_kwh,
        "cheap_slot_count": int(df["is_cheap"].sum()),
        "non_cheap_slot_count": len(df) - int(df["is_cheap"].sum()),
    }

    return df, debug_data
