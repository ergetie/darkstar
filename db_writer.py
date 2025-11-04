import json
from typing import Any, Dict, List, Tuple
from datetime import datetime

import pytz

import pymysql
import yaml


def _connect_mysql(secrets: Dict[str, Any]):
    db = secrets.get('mariadb', {})
    return pymysql.connect(
        host=db.get('host', '127.0.0.1'),
        port=int(db.get('port', 3306)),
        user=db.get('user'),
        password=db.get('password'),
        database=db.get('database'),
        charset='utf8mb4',
        autocommit=True,
        cursorclass=pymysql.cursors.Cursor,
    )


def _load_schedule(path: str) -> List[Dict[str, Any]]:
    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    return payload.get('schedule', [])


def _planner_version_from_meta(path: str, fallback: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        return payload.get('meta', {}).get('planner_version', fallback)
    except Exception:
        return fallback


def _normalise_start(value: Any, tz_name: str = 'Europe/Stockholm') -> datetime:
    """Convert schedule start_time to naive local datetime for MySQL DATETIME."""
    tz = pytz.timezone(tz_name)
    if isinstance(value, datetime):
        dt = value
    else:
        # Accept both start_time and slot_datetime shapes (strings)
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz)
    # Return naive (no tz) for MySQL DATETIME
    return dt.replace(tzinfo=None)


def _map_row(idx: int, slot: Dict[str, Any], *, tz_name: str = 'Europe/Stockholm') -> Tuple:
    slot_number = slot.get('slot_number', idx + 1)
    slot_start_raw = slot.get('start_time') or slot.get('slot_datetime')
    slot_start = _normalise_start(slot_start_raw, tz_name)

    charge_kw = float(slot.get('battery_charge_kw', slot.get('charge_kw', 0.0)) or 0.0)
    # export_kwh -> export_kw (kW) with 15-min slots (kWh * 4)
    export_kw = float(slot.get('export_kwh', 0.0) or 0.0) * 4.0
    water_kw = float(slot.get('water_heating_kw', 0.0) or 0.0)

    planned_load_kwh = float(slot.get('load_forecast_kwh', 0.0) or 0.0)
    planned_pv_kwh = float(slot.get('pv_forecast_kwh', 0.0) or 0.0)

    soc_target = float(slot.get('soc_target_percent', slot.get('soc_target', 0.0)) or 0.0)
    soc_projected = float(slot.get('projected_soc_percent', slot.get('soc_projected', 0.0)) or 0.0)
    # DB uses SMALLINT for SoC fields; map to integer percent
    soc_target_i = int(round(soc_target))
    soc_projected_i = int(round(soc_projected))

    classification = str(slot.get('action', slot.get('classification', 'Hold')))

    return (
        slot_number,
        slot_start,
        charge_kw,
        export_kw,
        water_kw,
        planned_load_kwh,
        planned_pv_kwh,
        soc_target_i,
        soc_projected_i,
        classification,
    )


def write_schedule_to_db(schedule_path: str, planner_version: str, config: Dict[str, Any], secrets: Dict[str, Any]) -> int:
    rows = _load_schedule(schedule_path)
    if not rows:
        return 0

    pv = _planner_version_from_meta(schedule_path, planner_version)
    tz_name = (config or {}).get('timezone', 'Europe/Stockholm')
    mapped = [_map_row(i, slot, tz_name=tz_name) for i, slot in enumerate(rows)]

    # Build REPLACE for current_schedule and INSERT for plan_history
    insert_current_sql = (
        "INSERT INTO current_schedule "
        "(slot_number, slot_start, charge_kw, export_kw, water_kw, planned_load_kwh, planned_pv_kwh, "
        " soc_target, soc_projected, classification, planner_version) "
        "VALUES (" + ",".join(["%s"] * 11) + ")"
    )
    insert_sql = (
        "INSERT INTO plan_history "
        "(planned_at, slot_number, slot_start, charge_kw, export_kw, water_kw, soc_target, planned_load_kwh, planned_pv_kwh, "
        " soc_projected, classification, planner_version) "
        "VALUES (CURRENT_TIMESTAMP, " + ",".join(["%s"] * 11) + ")"
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
