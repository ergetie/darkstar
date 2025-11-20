import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as dtp
import pandas as pd
import pytz
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError

import pymysql


def _connect_mysql(secrets: Dict[str, Any]):
    db = secrets.get("mariadb", {})
    return pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user"),
        password=db.get("password"),
        database=db.get("database"),
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _load_schedule(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("schedule", [])


def _planner_version_from_meta(path: str, fallback: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("meta", {}).get("planner_version", fallback)
    except Exception:
        return fallback


def _localize_to_tz(value: Any, tz_name: str = "Europe/Stockholm") -> datetime:
    """Return a timezone-aware datetime normalized to the configured timezone."""
    tz = pytz.timezone(tz_name)
    if isinstance(value, datetime):
        dt = value
    else:
        # Accept both start_time and slot_datetime shapes (strings)
        dt = dtp.isoparse(str(value))

    if dt.tzinfo is None:
        try:
            dt = tz.localize(dt)
        except (AmbiguousTimeError, NonExistentTimeError):
            # When DST transitions make the timestamp ambiguous/nonexistent,
            # prefer the DST-aware interpretation to keep plan continuity.
            dt = tz.localize(dt, is_dst=True)
    else:
        dt = dt.astimezone(tz)
    return dt


def _normalise_start(value: Any, tz_name: str = "Europe/Stockholm") -> datetime:
    """Convert schedule start_time to naive local datetime for MySQL DATETIME."""
    return _localize_to_tz(value, tz_name).replace(tzinfo=None)


def _get_preserved_slots_from_db(
    today_start: datetime, now: datetime, secrets: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Get past slots from today that should be preserved from database (source of truth)."""
    if not secrets or not secrets.get("mariadb"):
        return []

    try:
        with _connect_mysql(secrets) as conn:
            with conn.cursor() as cur:
                query = """
                    SELECT slot_number, slot_start, charge_kw, export_kw, water_kw,
                           planned_load_kwh, planned_pv_kwh, soc_target, soc_projected,
                           planner_version
                    FROM current_schedule
                    WHERE slot_start >= %s AND slot_start < %s
                    ORDER BY slot_number ASC
                """
                cur.execute(query, (today_start.replace(tzinfo=None), now.replace(tzinfo=None)))
                rows = cur.fetchall()

        # Convert to dict format matching schedule structure (same as webapp)
        preserved = []
        for r in rows:
            # Calculate end_time from resolution (15 minutes)
            start = r["slot_start"]
            end = start + pd.Timedelta(minutes=15)

            stored_charge = float(r.get("charge_kw") or 0.0)
            battery_charge = max(stored_charge, 0.0)
            battery_discharge = max(-stored_charge, 0.0)
            record = {
                "slot_number": r.get("slot_number"),
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "battery_charge_kw": round(battery_charge, 2),
                "battery_discharge_kw": round(battery_discharge, 2),
                # DB stores export in kW; UI expects export_kwh (15-min → kWh = kW/4)
                "export_kwh": round(float(r.get("export_kw") or 0.0) / 4.0, 4),
                "water_heating_kw": round(float(r.get("water_kw") or 0.0), 2),
                "load_forecast_kwh": round(float(r.get("planned_load_kwh") or 0.0), 4),
                "pv_forecast_kwh": round(float(r.get("planned_pv_kwh") or 0.0), 4),
                "soc_target_percent": round(float(r.get("soc_target") or 0.0), 0),  # No decimals
                "projected_soc_percent": round(
                    float(r.get("soc_projected") or 0.0), 0
                ),  # No decimals
                "is_historical": True,  # Mark as historical/preserved slot
            }
            preserved.append(record)
        return preserved
    except Exception as e:
        print(f"[db_writer] Warning: Could not preserve past slots from database: {e}")
        return []


def _get_preserved_slots_from_local(
    today_start: datetime,
    now: datetime,
    tz_name: str = "Europe/Stockholm",
) -> List[Dict[str, Any]]:
    """Get past slots from today that should be preserved from local schedule.json (fallback)."""
    try:
        if not os.path.exists("schedule.json"):
            return []

        with open("schedule.json", "r", encoding="utf-8") as f:
            existing_data = json.load(f)
            existing_schedule = existing_data.get("schedule", [])

        # Remove duplicates from existing schedule first
        seen_times = set()
        unique_existing_schedule = []
        for slot in existing_schedule:
            if slot["start_time"] not in seen_times:
                seen_times.add(slot["start_time"])
                unique_existing_schedule.append(slot)

        preserved = []
        for slot in unique_existing_schedule:
            # Parse ISO format time, handling timezone offset
            start_value = slot.get("start_time") or slot.get("slot_datetime")
            if not start_value:
                continue
            slot_time = _localize_to_tz(start_value, tz_name)

            # Only preserve slots from today that are in the past
            if slot_time < now and slot_time.date() == now.date() and slot_time >= today_start:
                # Mark as historical and preserve
                slot["is_historical"] = True

                # Apply same formatting as database logic (integer SOC values)
                if "soc_target_percent" in slot and isinstance(slot["soc_target_percent"], float):
                    slot["soc_target_percent"] = int(round(slot["soc_target_percent"], 0))
                if "projected_soc_percent" in slot and isinstance(
                    slot["projected_soc_percent"], float
                ):
                    slot["projected_soc_percent"] = int(round(slot["projected_soc_percent"], 0))

                preserved.append(slot)

        return preserved
    except Exception as e:
        print(f"[db_writer] Warning: Could not preserve past slots from local file: {e}")
        return []


def get_preserved_slots(
    today_start: datetime,
    now: datetime,
    secrets: Optional[Dict[str, Any]] = None,
    tz_name: str = "Europe/Stockholm",
) -> List[Dict[str, Any]]:
    """
    Get past slots from today that should be preserved.
    Tries database first (source of truth), falls back to local schedule.json.

    Args:
        today_start: Start of today (datetime)
        now: Current time (datetime)
        secrets: Configuration secrets (optional, for database access)
        tz_name: Timezone string used when parsing preserved slots

    Returns:
        List of preserved slot dictionaries
    """
    # Try database first (source of truth)
    if secrets and secrets.get("mariadb"):
        db_slots = _get_preserved_slots_from_db(today_start, now, secrets)
        if db_slots:
            print(f"[preservation] Loaded {len(db_slots)} past slots from database")
            return db_slots
        else:
            print("[preservation] No past slots found in database, trying local fallback")

    # Fallback to local schedule.json
    local_slots = _get_preserved_slots_from_local(today_start, now, tz_name)
    if local_slots:
        print(f"[preservation] Loaded {len(local_slots)} past slots from local schedule.json")
    else:
        print("[preservation] No past slots found locally")

    return local_slots


def _write_merged_schedule(
    merged_rows: List[Dict[str, Any]],
    planner_version: str,
    config: Dict[str, Any],
    secrets: Dict[str, Any],
) -> int:
    """Write merged schedule without deleting past hours."""

    pv = planner_version  # Use version directly since we don't have a path
    tz_name = config.get("timezone", "Europe/Stockholm")
    mapped = [_map_row(i, slot, tz_name=tz_name) for i, slot in enumerate(merged_rows)]

    with _connect_mysql(secrets) as conn:
        with conn.cursor() as cur:
            # Delete only FUTURE slots, preserve past
            now_naive = datetime.now(pytz.timezone(tz_name)).replace(tzinfo=None)
            cur.execute("DELETE FROM current_schedule WHERE slot_start >= ?", (now_naive,))

            # Insert merged schedule
            schedule_columns = [
                "slot_number",
                "slot_start",
                "charge_kw",
                "export_kw",
                "water_kw",
                "planned_load_kwh",
                "planned_pv_kwh",
                "soc_target",
                "soc_projected",
                "planner_version",
            ]
            columns_str = ", ".join(schedule_columns)
            values_str = ", ".join(["%s"] * len(schedule_columns))
            insert_sql = "INSERT INTO current_schedule " f"({columns_str}) VALUES ({values_str})"
            cur.executemany(insert_sql, [r + (pv,) for r in mapped])

            # Also append to plan_history for audit trail
            history_columns = [
                "planned_at",
                "slot_number",
                "slot_start",
                "charge_kw",
                "export_kw",
                "water_kw",
                "planned_load_kwh",
                "planned_pv_kwh",
                "soc_target",
                "soc_projected",
                "planner_version",
            ]
            history_cols_str = ", ".join(history_columns)
            history_vals = ", ".join(["%s"] * (len(history_columns) - 1))
            insert_history_sql = (
                "INSERT INTO plan_history "
                f"({history_cols_str}) VALUES (CURRENT_TIMESTAMP, {history_vals})"
            )
            cur.executemany(insert_history_sql, [r + (pv,) for r in mapped])

    return len(mapped)


def _map_row(idx: int, slot: Dict[str, Any], *, tz_name: str = "Europe/Stockholm") -> Tuple:
    slot_number = slot.get("slot_number", idx + 1)
    slot_start_raw = slot.get("start_time") or slot.get("slot_datetime")
    slot_start = _normalise_start(slot_start_raw, tz_name)

    battery_charge_kw = float(slot.get("battery_charge_kw", slot.get("charge_kw", 0.0)) or 0.0)
    # export_kwh -> export_kw (kW) with 15-min slots (kWh * 4)
    export_kw = float(slot.get("export_kwh", 0.0) or 0.0) * 4.0
    water_kw = float(slot.get("water_heating_kw", 0.0) or 0.0)

    planned_load_kwh = float(slot.get("load_forecast_kwh", 0.0) or 0.0)
    planned_pv_kwh = float(slot.get("pv_forecast_kwh", 0.0) or 0.0)

    soc_target = float(slot.get("soc_target_percent", slot.get("soc_target", 0.0)) or 0.0)
    soc_projected = float(slot.get("projected_soc_percent", slot.get("soc_projected", 0.0)) or 0.0)
    # DB uses SMALLINT for SoC fields; map to integer percent
    soc_target_i = int(round(soc_target))
    soc_projected_i = int(round(soc_projected))

    battery_discharge_kw = float(
        slot.get("battery_discharge_kw", slot.get("discharge_kw", 0.0)) or 0.0
    )
    net_battery_kw = battery_charge_kw - battery_discharge_kw
    return (
        slot_number,
        slot_start,
        net_battery_kw,
        export_kw,
        water_kw,
        planned_load_kwh,
        planned_pv_kwh,
        soc_target_i,
        soc_projected_i,
    )


def write_schedule_to_db_with_preservation(
    schedule_path: str, planner_version: str, config: Dict[str, Any], secrets: Dict[str, Any]
) -> int:
    """Write schedule preserving past hours (slots < now) for today only."""

    # Load new schedule
    new_rows = _load_schedule(schedule_path)
    if not new_rows:
        return 0

    # If no DB secrets, fall back to regular write
    if not secrets or not secrets.get("mariadb"):
        return write_schedule_to_db(schedule_path, planner_version, config, secrets)

    # Get current time in local timezone
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Preserve past slots from today only
    preserved_slots = get_preserved_slots(today_start, now, secrets, tz_name=tz_name)

    # Filter new schedule to future slots only
    future_rows = []
    for slot in new_rows:
        slot_time = _normalise_start(slot.get("start_time"), tz_name)
        if slot_time >= now.replace(tzinfo=None):  # Future slots only
            future_rows.append(slot)

    # Merge preserved + future
    merged_rows = preserved_slots + future_rows

    # Write merged schedule
    return _write_merged_schedule(merged_rows, planner_version, config, secrets)


def write_schedule_to_db(
    schedule_path: str, planner_version: str, config: Dict[str, Any], secrets: Dict[str, Any]
) -> int:
    rows = _load_schedule(schedule_path)
    if not rows:
        return 0

    # If no DB secrets, just return the count without writing
    if not secrets or not secrets.get("mariadb"):
        return len(rows)

    pv = _planner_version_from_meta(schedule_path, planner_version)
    tz_name = (config or {}).get("timezone", "Europe/Stockholm")
    mapped = [_map_row(i, slot, tz_name=tz_name) for i, slot in enumerate(rows)]

    # Build REPLACE for current_schedule and INSERT for plan_history
    current_columns = [
        "slot_number",
        "slot_start",
        "charge_kw",
        "export_kw",
        "water_kw",
        "planned_load_kwh",
        "planned_pv_kwh",
        "soc_target",
        "soc_projected",
        "planner_version",
    ]
    values_str = ", ".join(["%s"] * len(current_columns))
    insert_current_sql = (
        "INSERT INTO current_schedule " f"({', '.join(current_columns)}) VALUES ({values_str})"
    )
    history_columns = [
        "planned_at",
        "slot_number",
        "slot_start",
        "charge_kw",
        "export_kw",
        "water_kw",
        "planned_load_kwh",
        "planned_pv_kwh",
        "soc_target",
        "soc_projected",
        "planner_version",
    ]
    history_values = ", ".join(["%s"] * (len(history_columns) - 1))
    insert_sql = (
        "INSERT INTO plan_history "
        f"({', '.join(history_columns)}) VALUES (CURRENT_TIMESTAMP, {history_values})"
    )

    with _connect_mysql(secrets) as conn:
        with conn.cursor() as cur:
            # Replace current plan by clearing the table and inserting fresh rows
            cur.execute("DELETE FROM current_schedule")
            cur.executemany(
                insert_current_sql,
                [r + (pv,) for r in mapped],
            )
            # Append to plan_history
            cur.executemany(
                insert_sql,
                [r + (pv,) for r in mapped],
            )

    return len(mapped)