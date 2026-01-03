"""
Schedule Output

Handles saving the final schedule to JSON, including:
- Formatting future records
- Preserving past slots from database
- Generating and recording debug payloads
"""

import json
import os
import subprocess
from datetime import datetime
from typing import Any

import pandas as pd
import pytz
import yaml

from planner.observability.logging import record_debug_payload
from planner.output.debug import generate_debug_payload
from planner.output.formatter import dataframe_to_json_response

# Try to import db_writer from root
try:
    from db_writer import get_preserved_slots
except ImportError:
    # Fallback if running from a context where root is not in path
    # This might happen during tests if not set up correctly
    def get_preserved_slots(*args, **kwargs):
        print("[planner] Warning: db_writer not found, cannot preserve past slots")
        return []


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

    # Preserve past slots from database (source of truth) with local fallback
    existing_past_slots = []
    try:
        # Load secrets for database access
        secrets_path = "secrets.yaml"
        secrets = {}
        if os.path.exists(secrets_path):
            with open(secrets_path) as f:
                secrets = yaml.safe_load(f) or {}

        # Get current time in local timezone
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)

        # Use now_slot as the cutoff for preservation if available
        # This ensures we don't preserve the current slot if we just re-planned it
        preservation_cutoff = now
        if now_slot is not None:
            # Convert pandas Timestamp to python datetime
            preservation_cutoff = now_slot.to_pydatetime()

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        existing_past_slots = get_preserved_slots(
            today_start, preservation_cutoff, secrets, tz_name=tz_name
        )

    except Exception as e:
        print(f"[planner] Warning: Could not preserve past slots: {e}")

    # Fix slot number conflicts: ensure future slots continue from max historical slot number
    max_historical_slot = 0
    if existing_past_slots:
        max_historical_slot = max(slot.get("slot_number", 0) for slot in existing_past_slots)

    # Reassign slot numbers for future records to continue from historical max
    for i, record in enumerate(new_future_records):
        record["slot_number"] = max_historical_slot + i + 1

    # Merge: preserved past + new future pulls, ensuring no duplicates
    merged_schedule = existing_past_slots + new_future_records

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

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, cls=DateTimeEncoder)
