"""
Terminal Value Calculation Module

Calculate the value of energy remaining in the battery at end of horizon.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pandas as pd


def calculate_terminal_value(
    df: pd.DataFrame,
    risk_factor: float,
) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate the value of energy remaining in the battery at the end of the horizon.
    Terminal Value = Average Price (D1) * Risk Factor (D2).

    Args:
        df: DataFrame with import_price_sek_kwh column
        risk_factor: Risk factor from future risk calculation

    Returns:
        Tuple of (terminal_value, debug_data)
    """
    if df.empty:
        return 0.0, {}

    avg_price = df["import_price_sek_kwh"].mean()
    terminal_value = avg_price * risk_factor

    debug = {
        "avg_price_sek_kwh": round(avg_price, 4),
        "risk_factor_d2": round(risk_factor, 4),
        "terminal_value_sek_kwh": round(terminal_value, 4),
    }
    return terminal_value, debug


def calculate_dynamic_target_soc(
    risk_factor: float,
    min_soc_percent: float,
    capacity_kwh: float,
    soc_scaling_factor: float = 50.0,
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Calculate dynamic target SoC based on risk factor.

    Target % = Min % + (Risk - 1.0) * Scaling

    Args:
        risk_factor: Future risk factor (1.0 = baseline)
        min_soc_percent: Minimum SoC percent
        capacity_kwh: Total battery capacity
        soc_scaling_factor: How much to scale risk into SoC target

    Returns:
        Tuple of (target_soc_percent, target_soc_kwh, debug_data)
    """
    target_soc_pct = min_soc_percent + max(0.0, (risk_factor - 1.0) * soc_scaling_factor)
    target_soc_pct = min(100.0, target_soc_pct)

    target_soc_kwh = (target_soc_pct / 100.0) * capacity_kwh if capacity_kwh > 0 else 0.0

    debug = {
        "risk_factor": round(risk_factor, 4),
        "scaling_factor": soc_scaling_factor,
        "target_percent": round(target_soc_pct, 2),
        "target_kwh": round(target_soc_kwh, 2),
    }
    return target_soc_pct, target_soc_kwh, debug
