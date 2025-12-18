from __future__ import annotations

"""
Fix zero price slots in slot_observations by treating zeros as missing and
filling them from neighbouring non-zero prices within the same day.

Usage:
    PYTHONPATH=. python debug/fix_zero_price_slots.py

This is intended as a one-off data repair tool for days where some slots
have import_price_sek_kwh = 0.0 but other slots that day have valid prices.
Entire days with all-zero prices are left untouched so they can be inspected
separately.
"""

import sqlite3
from typing import Any, Dict, List, Tuple

import pandas as pd
import yaml


def _load_db_path(config_path: str = "config.yaml") -> str:
    with open(config_path, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    learning = cfg.get("learning", {}) or {}
    return learning.get("sqlite_path", "data/planner_learning.db")


def _find_days_with_zero_prices(conn: sqlite3.Connection) -> List[Tuple[str, int, int]]:
    rows = conn.execute(
        """
        SELECT
            DATE(slot_start) AS day,
            COUNT(*) AS total_slots,
            SUM(CASE WHEN import_price_sek_kwh = 0.0 THEN 1 ELSE 0 END) AS zero_import
        FROM slot_observations
        GROUP BY day
        ORDER BY day ASC
        """
    ).fetchall()

    result: List[Tuple[str, int, int]] = []
    for day, total, zero_import in rows:
        zero_import = zero_import or 0
        if zero_import > 0 and zero_import < total:
            result.append((str(day), int(total), int(zero_import)))
    return result


def _fix_day(conn: sqlite3.Connection, day: str) -> int:
    df = pd.read_sql_query(
        """
        SELECT slot_start, import_price_sek_kwh, export_price_sek_kwh
        FROM slot_observations
        WHERE DATE(slot_start) = ?
        ORDER BY slot_start ASC
        """,
        conn,
        params=(day,),
    )
    if df.empty:
        return 0

    # Treat zero import prices as missing if there is at least one non-zero.
    imp = df["import_price_sek_kwh"].astype(float)
    zero_mask = imp == 0.0
    if not zero_mask.any() or (~zero_mask).sum() == 0:
        return 0

    imp_fixed = imp.copy()
    imp_fixed[zero_mask] = pd.NA
    imp_fixed = imp_fixed.ffill().bfill()

    # Export: if present and sometimes zero, treat zeros as missing and fill.
    exp = df["export_price_sek_kwh"].astype(float)
    exp_zero_mask = exp == 0.0
    if (~exp_zero_mask).sum() > 0:
        exp_fixed = exp.copy()
        exp_fixed[exp_zero_mask] = pd.NA
        exp_fixed = exp_fixed.ffill().bfill()
    else:
        # If export is entirely zero/NULL, fall back to import as a proxy.
        exp_fixed = imp_fixed.copy()

    updates: List[Tuple[float, float, str]] = []
    for slot_start, old_imp, old_exp, new_imp, new_exp in zip(
        df["slot_start"],
        imp,
        exp,
        imp_fixed,
        exp_fixed,
    ):
        if float(old_imp) == float(new_imp) and float(old_exp) == float(new_exp):
            continue
        updates.append((float(new_imp), float(new_exp), str(slot_start)))

    if not updates:
        return 0

    conn.executemany(
        """
        UPDATE slot_observations
        SET import_price_sek_kwh = ?, export_price_sek_kwh = ?
        WHERE slot_start = ?
        """,
        updates,
    )
    return len(updates)


def main() -> int:
    db_path = _load_db_path()
    print(f"[fix-zero-prices] Using SQLite DB at {db_path}")

    with sqlite3.connect(db_path, timeout=30.0) as conn:
        days = _find_days_with_zero_prices(conn)
        if not days:
            print("[fix-zero-prices] No mixed zero/non-zero price days found.")
            return 0

        print("[fix-zero-prices] Days with mixed zero/non-zero import prices:")
        for day, total, zero_import in days:
            print(f"  {day}: total={total}, zero_import={zero_import}")

        total_updates = 0
        for day, _, _ in days:
            changed = _fix_day(conn, day)
            if changed > 0:
                print(f"[fix-zero-prices] {day}: updated {changed} slots.")
                total_updates += changed

        conn.commit()

    print(f"[fix-zero-prices] Done. Total slots updated: {total_updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
