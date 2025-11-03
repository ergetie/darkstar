import json
from typing import Any, Dict, List, Tuple

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


def _map_row(idx: int, slot: Dict[str, Any]) -> Tuple:
    slot_number = slot.get('slot_number', idx + 1)
    slot_start = slot.get('start_time') or slot.get('slot_datetime')

    charge_kw = float(slot.get('battery_charge_kw', slot.get('charge_kw', 0.0)) or 0.0)
    # export_kwh -> export_kw (kW) with 15-min slots (kWh * 4)
    export_kw = float(slot.get('export_kwh', 0.0) or 0.0) * 4.0
    water_kw = float(slot.get('water_heating_kw', 0.0) or 0.0)

    planned_load_kwh = float(slot.get('load_forecast_kwh', 0.0) or 0.0)
    planned_pv_kwh = float(slot.get('pv_forecast_kwh', 0.0) or 0.0)

    soc_target = float(slot.get('soc_target_percent', slot.get('soc_target', 0.0)) or 0.0)
    soc_projected = float(slot.get('projected_soc_percent', slot.get('soc_projected', 0.0)) or 0.0)

    classification = str(slot.get('action', slot.get('classification', 'Hold')))

    # commitment fields left NULL for now
    commitment_id = None
    committed_source_price = None
    commitment_reason = None
    marginal_profit = None

    return (
        slot_number,
        slot_start,
        charge_kw,
        export_kw,
        water_kw,
        planned_load_kwh,
        planned_pv_kwh,
        soc_target,
        soc_projected,
        classification,
        commitment_id,
        committed_source_price,
        commitment_reason,
        marginal_profit,
    )


def write_schedule_to_db(schedule_path: str, planner_version: str, config: Dict[str, Any], secrets: Dict[str, Any]) -> int:
    rows = _load_schedule(schedule_path)
    if not rows:
        return 0

    pv = _planner_version_from_meta(schedule_path, planner_version)
    mapped = [_map_row(i, slot) for i, slot in enumerate(rows)]

    # Build REPLACE for current_schedule and INSERT for plan_history
    replace_sql = (
        "REPLACE INTO current_schedule "
        "(slot_number, slot_start, charge_kw, export_kw, water_kw, planned_load_kwh, planned_pv_kwh, "
        " soc_target, soc_projected, classification, commitment_id, committed_source_price, commitment_reason, marginal_profit, planner_version) "
        "VALUES (" + ",".join(["%s"] * 15) + ")"
    )
    insert_sql = (
        "INSERT INTO plan_history "
        "(planned_at, slot_number, slot_start, charge_kw, export_kw, water_kw, planned_load_kwh, planned_pv_kwh, "
        " soc_target, soc_projected, classification, commitment_id, committed_source_price, commitment_reason, marginal_profit, planner_version) "
        "VALUES (CURRENT_TIMESTAMP, " + ",".join(["%s"] * 15) + ")"
    )

    with _connect_mysql(secrets) as conn:
        with conn.cursor() as cur:
            # current_schedule
            cur.executemany(
                replace_sql,
                [r + (pv,) for r in mapped],
            )
            # plan_history
            cur.executemany(
                insert_sql,
                [r + (pv,) for r in mapped],
            )

    return len(mapped)

