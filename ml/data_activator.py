"""
Logic for activating training/evaluation data for Aurora/Antares.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

import pytz
import requests
from learning import LearningEngine, get_learning_engine

from inputs import load_home_assistant_config, make_ha_headers


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp from Home Assistant."""
    if not value:
        return None
    try:
        # Python 3.11+ handles most ISO-8601 formats, including offsets
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt


def fetch_entity_history(
    entity_id: str,
    start_time: datetime,
    end_time: datetime,
    *,
    timeout: int = 30,
) -> list[tuple[datetime, float]]:
    """Fetch cumulative history for a single Home Assistant entity.

    Returns a list of (timestamp, numeric_value) tuples suitable for
    LearningEngine.etl_cumulative_to_slots.
    """
    ha_config = load_home_assistant_config()
    url = ha_config.get("url")
    token = ha_config.get("token")

    if not url or not token or not entity_id:
        print(
            f"Warning: Missing Home Assistant configuration or entity_id for "
            f"{entity_id!r}; skipping.",
        )
        return []

    headers = make_ha_headers(token)
    api_url = f"{url.rstrip('/')}/api/history/period/{start_time.isoformat()}"
    params = {
        "filter_entity_id": entity_id,
        "end_time": end_time.isoformat(),
        "significant_changes_only": False,
        "minimal_response": False,
    }

    try:
        response = requests.get(api_url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Warning: Failed to fetch history for '{entity_id}': {exc}")
        return []

    try:
        payload = response.json()
    except ValueError as exc:
        print(f"Warning: Invalid JSON when fetching history for '{entity_id}': {exc}")
        return []

    if not payload or not payload[0]:
        print(f"Warning: No history returned for '{entity_id}'.")
        return []

    # Home Assistant returns a list-of-lists: [[state, state, ...], ...]
    states = payload[0]
    records: list[tuple[datetime, float]] = []

    for state in states:
        ts_str = state.get("last_changed") or state.get("last_updated")
        raw_value = state.get("state")
        if raw_value in (None, "unknown", "unavailable"):
            continue

        # Support common non-numeric boolean-style entities for future features
        if isinstance(raw_value, str) and raw_value.lower() in {"on", "off"}:
            numeric_value: float
            numeric_value = 1.0 if raw_value.lower() == "on" else 0.0
        else:
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                # Skip non-numeric states (e.g. text)
                continue

        ts = _parse_iso_timestamp(ts_str)
        if ts is None:
            continue

        records.append((ts, numeric_value))

    if not records:
        print(f"Warning: Parsed no numeric samples for '{entity_id}'.")
    return records


def _build_cumulative_data(
    engine: LearningEngine,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, list[tuple[datetime, float]]]:
    """Build cumulative_data dict for etl_cumulative_to_slots from config input_sensors."""
    sensor_mappings = engine.config.get("input_sensors", {}) or {}
    if not sensor_mappings:
        print("Error: 'input_sensors' section not found in config. Aborting.")
        return {}

    print(f"Found {len(sensor_mappings)} sensor mappings in config.yaml.")

    cumulative_data: dict[str, list[tuple[datetime, float]]] = {}

    for canonical_name, entity_id in sensor_mappings.items():
        if not entity_id or "your_total" in str(entity_id):
            print(
                f"Warning: Skipping placeholder or empty sensor '{canonical_name}': {entity_id!r}",
            )
            continue

        history = fetch_entity_history(entity_id, start_time, end_time)
        if not history:
            print(f"Warning: No usable history for '{canonical_name}' ({entity_id}).")
            continue

        cumulative_data[canonical_name] = history
        print(
            f"Fetched {len(history)} samples for '{canonical_name}' from '{entity_id}'.",
        )

    if not cumulative_data:
        print("Error: No cumulative sensor data collected. Aborting.")

    return cumulative_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "AURORA data activator: backfill slot_observations using "
            "Home Assistant cumulative sensors."
        ),
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=30,
        help=("Number of days of history to backfill, counting backwards from now (default: 30)."),
    )
    return parser.parse_args()


def main() -> None:
    """Activate the data collection and processing pipeline for AURORA."""
    args = _parse_args()
    print("--- Starting AURORA Data Activator (Rev 3) ---")

    try:
        engine = get_learning_engine()
        assert isinstance(engine, LearningEngine)
        print(f"Initialized LearningEngine with DB at: {engine.db_path}")
    except Exception as exc:  # pragma: no cover - defensive startup logging
        print(f"Error: Could not initialize LearningEngine. {exc}")
        return

    now_utc = datetime.now(pytz.UTC)
    start_time = now_utc - timedelta(days=max(args.days_back, 1))
    end_time = now_utc

    print(
        f"Historical data range (UTC): {start_time.isoformat()} to {end_time.isoformat()}",
    )

    cumulative_data = _build_cumulative_data(engine, start_time, end_time)
    if not cumulative_data:
        return

    try:
        slot_df = engine.etl_cumulative_to_slots(cumulative_data)
    except Exception as exc:  # pragma: no cover - ETL safety
        print(f"Error during ETL process: {exc}")
        return

    if slot_df.empty:
        print("Warning: ETL process produced no slot data; nothing to store.")
        return

    print(f"ETL process created {len(slot_df)} slot-level observations.")

    try:
        engine.store_slot_observations(slot_df)
    except Exception as exc:  # pragma: no cover - DB safety
        print(f"Error storing slot observations in the database: {exc}")
        return

    print("Successfully stored processed data in the learning database.")
    print("--- AURORA Data Activator finished ---")


if __name__ == "__main__":
    main()
