"""
Schedule Output

Handles saving the final schedule to JSON, including:
- Formatting future records
- Preserving past slots from database
- Generating and recording debug payloads
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from planner.observability.logging import record_debug_payload
from planner.output.debug import generate_debug_payload
from planner.output.formatter import dataframe_to_json_response


def get_git_version() -> str:
    """Get the current git version string."""
    try:
        version = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always", "--dirty"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        return version
    except Exception:
        return "dev"


def save_schedule_to_json(
    schedule_df: pd.DataFrame,
    config: dict[str, Any],
    now_slot: pd.Timestamp | None,
    forecast_meta: dict[str, Any],
    s_index_debug: dict[str, Any] | None,
    window_responsibilities: list[dict[str, Any]],
    planner_state: dict[str, Any],
    output_path: str = "schedule.json",
) -> None:
    """
    Save the final schedule to schedule.json in the required format.
    Preserves past hours from existing schedule when regenerating.

    Args:
        schedule_df: The final schedule DataFrame
        config: Full configuration dictionary
        now_slot: The current slot timestamp (start of planning)
        forecast_meta: Metadata about forecasts used
        s_index_debug: Debug info for S-Index
        window_responsibilities: List of window responsibilities
        planner_state: Dictionary containing planner state metrics
        output_path: Path to save the JSON file
    """
    # Generate new future schedule
    new_future_records = dataframe_to_json_response(schedule_df, now_override=now_slot)

    # Add is_historical: false to new slots
    for record in new_future_records:
        record["is_historical"] = False

    # Simple slot numbering (legacy MariaDB preservation removed in REV LCL01)
    for i, record in enumerate(new_future_records):
        record["slot_number"] = i + 1

    # Final schedule is just the new future records
    merged_schedule = new_future_records

    # Update forecast meta with provided data
    final_forecast_meta = forecast_meta.copy()


    version = get_git_version()

    output = {
        "schedule": merged_schedule,
        "meta": {
            "planned_at": datetime.now().isoformat(),
            "planner_version": version,
            "forecast": final_forecast_meta,
            "s_index": s_index_debug or {},
        },
    }

    # Add debug payload if enabled
    debug_config = config.get("debug", {})
    if debug_config.get("enable_planner_debug", False):
        debug_payload = generate_debug_payload(
            schedule_df, window_responsibilities, debug_config, planner_state, s_index_debug
        )
        output["debug"] = debug_payload

        learning_config = config.get("learning", {})
        record_debug_payload(debug_payload, learning_config)

    class DateTimeEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (datetime, pd.Timestamp)):
                return obj.isoformat()
            return super().default(obj)

    with Path(output_path).open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, cls=DateTimeEncoder)
