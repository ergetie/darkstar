"""
Output Formatter Module

Convert schedule DataFrames to JSON response format for frontend.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import pytz


def dataframe_to_json_response(
    df: pd.DataFrame,
    now_override: datetime | None = None,
    timezone_name: str = "Europe/Stockholm",
) -> list[dict[str, Any]]:
    """
    Convert a DataFrame to the JSON response format required by the frontend.
    Only includes current and future slots (past slots are filtered out).

    Args:
        df: The schedule DataFrame
        now_override: Optional timestamp to use as "now" for filtering
        timezone_name: Timezone for timestamp handling

    Returns:
        List of dictionaries ready for JSON response
    """
    # Reset index in case start_time is stored as index
    df_copy = df.reset_index().copy()

    # Handle case where index was named 'index' after reset
    if "index" in df_copy.columns and "start_time" not in df_copy.columns:
        # Check if the index values look like timestamps
        try:
            test_val = df_copy["index"].iloc[0] if len(df_copy) > 0 else None
            if test_val is not None and isinstance(test_val, (pd.Timestamp, datetime)):
                df_copy = df_copy.rename(columns={"index": "start_time"})
        except Exception:
            pass

    drop_cols = [col for col in ("action", "classification") if col in df_copy.columns]
    if drop_cols:
        df_copy = df_copy.drop(columns=drop_cols, errors="ignore")

    tz = pytz.timezone(timezone_name)

    # Validate required column exists
    if "start_time" not in df_copy.columns:
        available_cols = list(df_copy.columns)
        raise ValueError(
            f"Schedule DataFrame is missing required 'start_time' column. "
            f"Available columns: {available_cols}. "
            f"This usually means the planner/solver returned malformed data. "
            f"Check the Kepler solver output or try re-running the planner."
        )

    # Normalize timestamps
    start_series = pd.to_datetime(df_copy["start_time"], errors="coerce")
    if not start_series.dt.tz:
        start_series = start_series.dt.tz_localize(tz)
    else:
        start_series = start_series.dt.tz_convert(tz)
    df_copy["start_time"] = start_series

    # Validate end_time exists
    if "end_time" not in df_copy.columns:
        raise ValueError(
            "Schedule DataFrame is missing required 'end_time' column. "
            "Check the Kepler solver output or try re-running the planner."
        )

    end_series = pd.to_datetime(df_copy["end_time"], errors="coerce")
    if not end_series.dt.tz:
        end_series = end_series.dt.tz_localize(tz)
    else:
        end_series = end_series.dt.tz_convert(tz)
    df_copy["end_time"] = end_series

    if now_override is not None:
        now = now_override
        now = tz.localize(now) if now.tzinfo is None else now.astimezone(tz)
    else:
        now = datetime.now(tz)

    # Filter to future slots only
    future_df = df_copy[df_copy["start_time"] >= now]
    if future_df.empty and not df_copy.empty:
        future_df = df_copy
    df_copy = future_df

    records = df_copy.to_dict("records")

    for i, record in enumerate(records):
        record["slot_number"] = i + 1
        record["start_time"] = record["start_time"].isoformat()
        record["end_time"] = record["end_time"].isoformat()

        # Prefer explicit battery power fields; fallback to legacy
        if "battery_charge_kw" not in record and "charge_kw" in record:
            record["battery_charge_kw"] = record.get("charge_kw", 0.0)
        if "battery_discharge_kw" not in record:
            record["battery_discharge_kw"] = 0.0

        # Determine reason/priority based on numeric actions
        charge_kw = float(record.get("battery_charge_kw") or record.get("charge_kw") or 0.0)
        discharge_kw = float(record.get("battery_discharge_kw") or 0.0)
        export_kwh = float(record.get("export_kwh") or 0.0)
        water_kw = float(record.get("water_heating_kw") or 0.0)
        grid_charge_kw = float(record.get("charge_kw") or 0.0)

        if export_kwh > 0:
            reason = "profitable_export"
            priority = "medium"
        elif discharge_kw > 0:
            reason = "expensive_grid_power"
            priority = "high"
        elif charge_kw > 0:
            is_importing = (
                grid_charge_kw > 0
                or float(record.get("import_kwh") or record.get("grid_import_kw") or 0.0) > 0
            )
            reason = "cheap_grid_power" if is_importing else "excess_pv"
            priority = "high"
        elif water_kw > 0:
            reason = "water_heating"
            priority = "medium"
        else:
            reason = "no_action_needed"
            priority = "low"

        record["reason"] = reason
        record["priority"] = priority
        record["is_historical"] = record.get("is_historical", False)

        # Rev K22: Calculate planned cash flow cost (Grid Bill only)
        import_kwh = float(record.get("kepler_import_kwh") or record.get("import_kwh") or 0.0)
        export_kwh_actual = float(
            record.get("kepler_export_kwh") or record.get("export_kwh") or 0.0
        )
        buy_price = float(record.get("import_price_sek_kwh") or 0.0)
        sell_price = float(record.get("export_price_sek_kwh") or 0.0)
        record["planned_cost_sek"] = (import_kwh * buy_price) - (export_kwh_actual * sell_price)

        for key, value in record.items():
            if isinstance(value, float):
                record[key] = round(value, 2)

    return records
