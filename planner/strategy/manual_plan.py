"""
Manual Plan Application Module

Apply user-created manual actions to the schedule.
Extracted from planner_legacy.py during Rev K13 modularization.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pandas as pd
import pytz
from pandas import Timestamp

from planner.battery_limits import resolve_battery_power_limits

logger = logging.getLogger("darkstar.planner.manual_plan")


def apply_manual_plan(
    df: pd.DataFrame,
    manual_plan: Any,
    config: dict[str, Any] | None = None,
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

    charge_cap_kw = resolve_battery_power_limits(config)[0]
    water_kw_default = config.get("water_heating", {}).get("power_kw", 0.0)

    working_df = df.copy()
    if "charge_kw" not in working_df.columns:
        working_df["charge_kw"] = 0.0
    if "water_heating_kw" not in working_df.columns:
        working_df["water_heating_kw"] = 0.0
    if "manual_action" not in working_df.columns:
        working_df["manual_action"] = pd.Series([None] * len(working_df), index=working_df.index)

    manual_items: list[dict[str, Any]]
    if isinstance(manual_plan, dict):
        raw_items: list[dict[str, Any]] = cast(
            "list[dict[str, Any]]",
            manual_plan.get("plan")  # type: ignore
            or manual_plan.get("schedule")  # type: ignore
            or manual_plan.get("items")  # type: ignore
            or [],
        )
        manual_items = raw_items
    elif isinstance(manual_plan, list):
        manual_items = cast("list[dict[str, Any]]", manual_plan)
    else:
        manual_items = []

    def _infer_action(entry: dict[str, Any]) -> str | None:
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

    for raw_entry in manual_items:
        entry: dict[str, Any] = raw_entry
        _id: str = str(entry.get("id") or "")
        _type_raw: Any = entry.get("type")
        _type: str = str(_type_raw or "").lower()
        _class_raw: Any = entry.get("className")
        _class: str = str(_class_raw or "").lower()
        if _type == "background" or _id.startswith("lane-spacer-") or "lane-spacer" in _class:
            continue

        action: str | None = _infer_action(entry)
        if not action:
            continue
        normalized: str = action.strip().lower()

        start_raw: Any = entry.get("start") or entry.get("start_time")
        end_raw: Any = entry.get("end") or entry.get("end_time")
        if not start_raw or not end_raw:
            continue

        start_time: Timestamp = pd.to_datetime(start_raw)  # type: ignore
        end_time: Timestamp = pd.to_datetime(end_raw)  # type: ignore
        if start_time.tzinfo is None:  # type: ignore
            start_time = tz.localize(start_time)  # type: ignore
        else:
            start_time = start_time.tz_convert(tz)  # type: ignore
        end_time = tz.localize(end_time) if end_time.tzinfo is None else end_time.tz_convert(tz)  # type: ignore

        mask: Any = (working_df.index >= start_time) & (working_df.index < end_time)  # type: ignore
        if not mask.any():  # type: ignore
            continue

        if normalized == "charge":
            if charge_cap_kw <= 0:
                logger.warning(
                    "Battery max charge limit is not configured; manual Charge plans 0 kW"
                )
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
