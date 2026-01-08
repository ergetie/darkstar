"""
Terminal Value Calculation Module

Calculate the value of energy remaining in the battery at end of horizon.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


def calculate_terminal_value(
    df: pd.DataFrame,
    risk_factor: float,
) -> tuple[float, dict[str, Any]]:
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
