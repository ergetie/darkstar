"""
Manual Plan Application Module

Apply user-created manual actions to the schedule.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd
import pytz


def apply_manual_plan(
    df: pd.DataFrame,
    manual_plan: Any,
    config: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Apply user-created manual actions to the plan and annotate manual_action flags.
    
    Args:
        df: Schedule DataFrame
        manual_plan: Manual plan data (dict or list of entries)
        config: Configuration dictionary
        
    Returns:
        DataFrame with manual actions applied
    """
    if config is None:
        config = {}

    timezone_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)

    charge_cap_kw = (
        config.get("system", {}).get("battery", {}).get("max_charge_power_kw")
        or config.get("battery", {}).get("max_charge_power_kw")
        or 0.0
    )
    water_kw_default = config.get("water_heating", {}).get("power_kw", 0.0)

    working_df = df.copy()
    if "charge_kw" not in working_df.columns:
        working_df["charge_kw"] = 0.0
    if "water_heating_kw" not in working_df.columns:
        working_df["water_heating_kw"] = 0.0
    if "manual_action" not in working_df.columns:
        working_df["manual_action"] = pd.Series([None] * len(working_df), index=working_df.index)

    if isinstance(manual_plan, dict):
        manual_items = (
            manual_plan.get("plan") or manual_plan.get("schedule") or manual_plan.get("items") or []
        )
    elif isinstance(manual_plan, list):
        manual_items = manual_plan
    else:
        manual_items = []

    def _infer_action(entry: dict) -> Optional[str]:
        action = entry.get("content") or entry.get("action") or entry.get("title")
        if action:
            return str(action).strip()

        _id = entry.get("id")
        if isinstance(_id, str):
            low = _id.lower()
            if "charge" in low:
                return "Charge"
            if "water" in low:
                return "Water Heating"
            if "export" in low:
                return "Export"
            if "hold" in low:
                return "Hold"

        group = (entry.get("group") or "").lower()
        if group == "battery":
            return "Charge"
        if group == "water":
            return "Water Heating"
        if group == "export":
            return "Export"
        if group == "hold":
            return "Hold"
        return None

    for entry in manual_items:
        _id = str(entry.get("id") or "")
        _type = (entry.get("type") or "").lower()
        _class = (entry.get("className") or "").lower()
        if _type == "background" or _id.startswith("lane-spacer-") or "lane-spacer" in _class:
            continue

        action = _infer_action(entry)
        if not action:
            continue
        normalized = action.strip().lower()

        start_raw = entry.get("start") or entry.get("start_time")
        end_raw = entry.get("end") or entry.get("end_time")
        if not start_raw or not end_raw:
            continue

        start_time = pd.to_datetime(start_raw)
        end_time = pd.to_datetime(end_raw)
        if start_time.tzinfo is None:
            start_time = tz.localize(start_time)
        else:
            start_time = start_time.tz_convert(tz)
        if end_time.tzinfo is None:
            end_time = tz.localize(end_time)
        else:
            end_time = end_time.tz_convert(tz)

        mask = (working_df.index >= start_time) & (working_df.index < end_time)
        if not mask.any():
            continue

        if normalized == "charge":
            working_df.loc[mask, "charge_kw"] = float(charge_cap_kw)
            working_df.loc[mask, "manual_action"] = "Charge"
        elif normalized == "water heating":
            working_df.loc[mask, "water_heating_kw"] = float(water_kw_default)
            working_df.loc[mask, "manual_action"] = "Water Heating"
        elif normalized == "export":
            working_df.loc[mask, "manual_action"] = "Export"
        elif normalized == "hold":
            working_df.loc[mask, "manual_action"] = "Hold"

    return working_df
