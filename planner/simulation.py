"""
Simulation Module

Functions for simulating battery state and costs based on a schedule.
"""

from typing import Any

import pandas as pd


def simulate_schedule(
    df: pd.DataFrame, config: dict[str, Any], initial_state: dict[str, Any]
) -> pd.DataFrame:
    """
    Simulate a schedule with given battery actions and return the projected results.

    Args:
        df: DataFrame with charge_kw, discharge_kw, etc. set
        config: Configuration dictionary
        initial_state: Initial battery state

    Returns:
        DataFrame with simulated projections (projected_soc_percent, etc.)
    """
    df = df.copy()

    battery_config = config.get("battery", {})
    capacity_kwh = float(battery_config.get("capacity_kwh", 0.0))
    float(battery_config.get("min_soc_percent", 10.0))
    float(battery_config.get("max_soc_percent", 100.0))

    # Efficiency
    roundtrip = float(battery_config.get("roundtrip_efficiency_percent", 95.0))
    eff_one_way = (roundtrip / 100.0) ** 0.5

    # Initial SoC
    current_soc_kwh = float(initial_state.get("battery_soc_kwh", 0.0))
    if "battery_soc_percent" in initial_state and "battery_soc_kwh" not in initial_state:
        current_soc_kwh = (float(initial_state["battery_soc_percent"]) / 100.0) * capacity_kwh

    # Iterate and update state
    projected_soc_kwh = []
    projected_soc_pct = []

    for idx, row in df.iterrows():
        # Determine slot duration
        duration_h = (row["end_time"] - idx).total_seconds() / 3600.0 if "end_time" in row else 0.25
        # Default 15 min

        charge_kw = float(row.get("charge_kw", 0.0))
        discharge_kw = float(row.get("discharge_kw", 0.0))

        # Apply efficiency
        energy_in = charge_kw * duration_h * eff_one_way
        energy_out = discharge_kw * duration_h / eff_one_way

        current_soc_kwh += energy_in - energy_out

        # Clamp (though simulation should probably show if it violates?)
        # Legacy planner clamps in _pass_6.
        current_soc_kwh = max(0.0, min(current_soc_kwh, capacity_kwh))

        pct = (current_soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0

        projected_soc_kwh.append(current_soc_kwh)
        projected_soc_pct.append(pct)

    df["projected_soc_kwh"] = projected_soc_kwh
    df["projected_soc_percent"] = projected_soc_pct

    # Calculate costs/revenues if prices available
    if "import_price_sek_kwh" in df.columns:
        df["import_cost"] = df.get("import_kwh", 0.0) * df["import_price_sek_kwh"]
    if "export_price_sek_kwh" in df.columns:
        df["export_revenue"] = df.get("export_kwh", 0.0) * df["export_price_sek_kwh"]

    return df
