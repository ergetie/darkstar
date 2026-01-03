import argparse
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import yaml


def load_config() -> dict[str, Any]:
    with open("config.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_db_path(config: dict[str, Any]) -> str:
    learning_cfg = config.get("learning") or {}
    return learning_cfg.get("sqlite_path") or "data/planner_learning.db"


def parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from exc


def find_missing_slots(conn: sqlite3.Connection, day: date) -> list[datetime]:
    prefix = day.isoformat()
    cur = conn.cursor()
    cur.execute(
        "SELECT slot_start FROM slot_observations WHERE slot_start LIKE ? ORDER BY slot_start",
        (f"{prefix}%",),
    )
    rows = [row[0] for row in cur.fetchall()]
    if not rows:
        return []

    # Use configured timezone but rely on calendar day/00:00..23:45 grid.
    dt_start = datetime.fromisoformat(f"{prefix}T00:00:00+01:00")
    expected: list[datetime] = []
    current = dt_start
    for _ in range(96):
        expected.append(current)
        current += timedelta(minutes=15)

    existing = set(rows)
    missing: list[datetime] = []
    for ts in expected:
        ts_str = ts.isoformat()
        if ts_str not in existing:
            missing.append(ts)
    return missing


def insert_slots(conn: sqlite3.Connection, missing: list[datetime]) -> int:
    if not missing:
        return 0
    rows = []
    for start_dt in missing:
        end_dt = start_dt + timedelta(minutes=15)
        rows.append((start_dt.isoformat(), end_dt.isoformat()))
    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR IGNORE INTO slot_observations (slot_start, slot_end)
        VALUES (?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Insert missing 15-minute slot_observations rows for a given local day."
    )
    parser.add_argument("--date", required=True, type=parse_date, help="Target day (YYYY-MM-DD).")
    args = parser.parse_args()

    config = load_config()
    db_path = resolve_db_path(config)

    day: date = args.date
    print(f"[repair] Using database {db_path}")
    print(f"[repair] Scanning for missing slots on {day.isoformat()}...")

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        missing = find_missing_slots(conn, day)
        if not missing:
            print("[repair] No missing slots detected (96 present).")
            return

        print(f"[repair] Found {len(missing)} missing slots:")
        for ts in missing:
            print(f"  - {ts.isoformat()}")

        inserted = insert_slots(conn, missing)
        print(f"[repair] Inserted {inserted} new slot_observations rows.")


if __name__ == "__main__":
    main()
