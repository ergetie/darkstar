"""One-off tagging script for fix-observability-gaps #8 / findings.md #8.

Marks slot_observations rows in the January 2026 corruption window
(2026-01-16..2026-01-20) that match the physical-impossibility criterion
(battery charging with negligible import and insufficient PV to explain it)
with "exclude": true in their quality_flags JSON, so ml/train.py's
_load_slot_observations filter drops them from future training runs.

Only the quality_flags annotation is written; no measurement column is
touched, and no rows are deleted.

Dry-run by default. To apply against production, after deploy:
    python scripts/flag_january_bad_slots.py --apply
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import yaml

BAD_WINDOW_START = "2026-01-16"
BAD_WINDOW_END = "2026-01-20T23:59:59.999999"

SELECT_CANDIDATES = """
    SELECT slot_start, quality_flags
    FROM slot_observations
    WHERE slot_start >= ? AND slot_start <= ?
      AND batt_charge_kwh > 0.3
      AND import_kwh < 0.05
      AND pv_kwh < 0.5 * batt_charge_kwh
"""


def load_db_path() -> str:
    try:
        with Path("config.yaml").open(encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)
            config = cast("dict[str, Any]", raw) if raw else {}
    except FileNotFoundError:
        config = {}
    learning_cfg = cast("dict[str, Any]", config.get("learning", {}) or {})
    return cast("str", learning_cfg.get("sqlite_path", "data/planner_learning.db"))


def merge_exclude_flag(raw_flags: str | None) -> str:
    flags: dict[str, Any]
    if raw_flags:
        try:
            parsed = json.loads(raw_flags)
            flags = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            flags = {}
    else:
        flags = {}
    flags["exclude"] = True
    return json.dumps(flags, sort_keys=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Flag known-bad January 2026 slot_observations rows with "
            '"exclude": true so ML training skips them. Dry-run by default; '
            "pass --apply to write."
        )
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write the exclude flag (default is dry-run)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = load_db_path()
    print(f"Database: {db_path}")
    print(f"Window: {BAD_WINDOW_START} .. {BAD_WINDOW_END}")

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(SELECT_CANDIDATES, (BAD_WINDOW_START, BAD_WINDOW_END)).fetchall()

        print(f"Matching rows: {len(rows)}")
        for slot_start, _quality_flags in rows:
            print(f"  {slot_start}")

        if not args.apply:
            print("Dry run — no changes written. Re-run with --apply to write.")
            return

        for slot_start, quality_flags in rows:
            new_flags = merge_exclude_flag(quality_flags)
            conn.execute(
                "UPDATE slot_observations SET quality_flags = ? WHERE slot_start = ?",
                (new_flags, slot_start),
            )
        conn.commit()
        print(f"Applied exclude flag to {len(rows)} row(s).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
