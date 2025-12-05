"""
Debug Payload Generation

This module handles the generation of debug payloads for the planner,
including window responsibilities, water analysis, and metrics.
"""

from typing import Any, Dict, List, Optional
import pandas as pd


def prepare_windows_for_json(window_responsibilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare window responsibilities for JSON serialization.

    Args:
        window_responsibilities: List of window responsibility dictionaries

    Returns:
        list: List of window dictionaries with timestamps converted to strings
    """
    json_windows = []

    for window in window_responsibilities:
        json_window = {}
        for key, value in window.items():
            if key == "window":
                # Handle nested window dict with timestamps
                json_window[key] = {}
                for w_key, w_value in value.items():
                    if hasattr(w_value, "isoformat"):  # Timestamp
                        json_window[key][w_key] = w_value.isoformat()
                    else:
                        json_window[key][w_key] = w_value
            elif isinstance(value, float):
                json_window[key] = round(value, 2)
            else:
                json_window[key] = value
        json_windows.append(json_window)

    return json_windows


def prepare_sample_schedule_for_json(sample_df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Prepare sample schedule DataFrame for JSON serialization.

    Args:
        sample_df (pd.DataFrame): Sample DataFrame

    Returns:
        list: List of records ready for JSON serialization
    """
    if sample_df.empty:
        return []

    # Reset index and convert to dict
    records = sample_df.reset_index().to_dict("records")

    # Convert timestamps to strings
    for record in records:
        for key, value in record.items():
            if hasattr(value, "isoformat"):  # Timestamp objects
                record[key] = value.isoformat()
            elif isinstance(value, float):
                record[key] = round(value, 2)

    return records


def generate_debug_payload(
    schedule_df: pd.DataFrame,
    window_responsibilities: List[Dict[str, Any]],
    debug_config: Dict[str, Any],
    planner_state: Dict[str, Any],
    s_index_debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate debug payload with windows, gaps, charging plan, water analysis, and metrics.

    Args:
        schedule_df (pd.DataFrame): The final schedule DataFrame
        window_responsibilities (list): List of window responsibilities
        debug_config (dict): Debug configuration
        planner_state (dict): Dictionary containing planner state metrics
                              (cheap_threshold_sek_kwh, smoothing_tolerance_sek_kwh,
                               cheap_slot_count, non_cheap_slot_count)
        s_index_debug (dict, optional): S-Index debug info

    Returns:
        dict: Debug payload
    """
    sample_size = debug_config.get("sample_size", 30)

    # Sample the schedule for debug (first N slots)
    sample_df = schedule_df.head(sample_size)

    windows_list = prepare_windows_for_json(window_responsibilities)
    windows_summary = {
        "cheap_threshold_sek_kwh": planner_state.get("cheap_price_threshold"),
        "smoothing_tolerance_sek_kwh": planner_state.get("price_smoothing_tolerance"),
        "cheap_slot_count": planner_state.get("cheap_slot_count", 0),
        "non_cheap_slot_count": planner_state.get("non_cheap_slot_count", 0),
    }
    
    # Calculate totals safely
    total_water = schedule_df["water_heating_kw"].sum() * 0.25 if "water_heating_kw" in schedule_df else 0.0
    water_pv = schedule_df["water_from_pv_kwh"].sum() if "water_from_pv_kwh" in schedule_df else 0.0
    water_batt = schedule_df["water_from_battery_kwh"].sum() if "water_from_battery_kwh" in schedule_df else 0.0
    water_grid = schedule_df["water_from_grid_kwh"].sum() if "water_from_grid_kwh" in schedule_df else 0.0
    
    charge_kw = schedule_df.get("charge_kw", schedule_df.get("battery_charge_kw", pd.Series([0] * len(schedule_df))))
    total_charge = charge_kw.sum() * 0.25
    
    export_kwh = schedule_df["export_kwh"].sum() if "export_kwh" in schedule_df else 0.0
    export_rev = schedule_df["export_revenue"].sum() if "export_revenue" in schedule_df else 0.0
    
    pv_gen = schedule_df["adjusted_pv_kwh"].sum() if "adjusted_pv_kwh" in schedule_df else 0.0
    load_kwh = schedule_df["adjusted_load_kwh"].sum() if "adjusted_load_kwh" in schedule_df else 0.0
    
    final_soc = 0.0
    if not schedule_df.empty and "projected_soc_percent" in schedule_df:
        final_soc = schedule_df["projected_soc_percent"].iloc[-1]
        
    avg_batt_cost = 0.0
    if not schedule_df.empty and "projected_battery_cost" in schedule_df:
        avg_batt_cost = schedule_df["projected_battery_cost"].mean()

    debug_payload = {
        "windows": {**windows_summary, "list": windows_list},
        "water_analysis": {
            "total_water_scheduled_kwh": round(total_water, 2),
            "water_from_pv_kwh": round(water_pv, 2),
            "water_from_battery_kwh": round(water_batt, 2),
            "water_from_grid_kwh": round(water_grid, 2),
        },
        "charging_plan": {
            "total_charge_kwh": round(total_charge, 2),
            "total_export_kwh": round(export_kwh, 2),
            "total_export_revenue": round(export_rev, 2),
        },
        "metrics": {
            "total_pv_generation_kwh": round(pv_gen, 2),
            "total_load_kwh": round(load_kwh, 2),
            "net_energy_balance_kwh": round(pv_gen - load_kwh, 2),
            "final_soc_percent": round(final_soc, 2),
            "average_battery_cost": round(avg_batt_cost, 2),
        },
        "s_index": s_index_debug,
        "sample_schedule": prepare_sample_schedule_for_json(sample_df),
    }

    return debug_payload
