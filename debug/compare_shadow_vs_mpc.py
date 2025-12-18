from __future__ import annotations

"""
Compare MPC vs Antares policy costs on real data (Phase 4 helper).

This uses the same cost machinery as Rev 73, and additionally checks that
Antares shadow plans exist in MariaDB for the requested days.

Usage:
    PYTHONPATH=. python debug/compare_shadow_vs_mpc.py --start-date 2025-11-18 --end-date 2025-11-25
"""

import argparse
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from learning import LearningEngine, get_learning_engine
from ml.eval_antares_policy_cost import _run_mpc_cost, _run_policy_cost, _get_engine  # type: ignore
from ml.policy.antares_policy import AntaresPolicyV1


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value).date()


def _load_policy_and_engine() -> Tuple[AntaresPolicyV1, LearningEngine]:
    engine = _get_engine()
    policy_run = None
    import sqlite3

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        row = conn.execute(
            """
            SELECT run_id, models_dir
            FROM antares_policy_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row:
        policy_run = {"run_id": row[0], "models_dir": row[1]}

    if policy_run is None:
        raise RuntimeError("No antares_policy_runs rows found; train policy first.")

    policy = AntaresPolicyV1.load_from_dir(policy_run["models_dir"])
    return policy, engine


def _scan_shadow_days(start: date, end: date) -> List[str]:
    """Return list of dates that have shadow plans in MariaDB, if accessible."""
    try:
        with open("secrets.yaml", "r", encoding="utf-8") as handle:
            secrets_cfg = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return []

    mariadb_cfg = (secrets_cfg.get("mariadb") or {}) if isinstance(secrets_cfg, dict) else {}
    required = ("host", "user", "password", "database")
    if not all(mariadb_cfg.get(key) for key in required):
        return []

    try:
        import pymysql
    except ImportError:
        return []

    host = mariadb_cfg["host"]
    user = mariadb_cfg["user"]
    password = mariadb_cfg["password"]
    database = mariadb_cfg["database"]
    port = int(mariadb_cfg.get("port") or 3306)

    days: List[str] = []
    sql = """
        SELECT DISTINCT plan_date
        FROM antares_plan_history
        WHERE plan_date >= %s AND plan_date <= %s
        ORDER BY plan_date
    """

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            connect_timeout=5,
        )
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (start.isoformat(), end.isoformat()))
                rows = cursor.fetchall()
                for r in rows:
                    d = r.get("plan_date")
                    if isinstance(d, (date, datetime)):
                        days.append(
                            d.date().isoformat() if isinstance(d, datetime) else d.isoformat()
                        )
    except Exception:
        return []

    return days


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare MPC vs Antares policy costs for a date range, "
        "and check that Antares shadow plans exist in MariaDB.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    args = parser.parse_args()

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    if end < start:
        raise SystemExit("end-date must be >= start-date")

    policy, engine = _load_policy_and_engine()

    shadow_days = set(_scan_shadow_days(start, end))
    if shadow_days:
        print(f"[shadow-compare] Shadow plans present in MariaDB for: {sorted(shadow_days)}")
    else:
        print(
            "[shadow-compare] No shadow plans found in MariaDB for this window (or DB unreachable)."
        )

    # Evaluate MPC vs policy costs over the window using the existing env-based cost model.
    days: List[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)

    records = []
    for d in days:
        try:
            mpc_cost = _run_mpc_cost(d)
            policy_cost = _run_policy_cost(d, policy)
        except Exception as exc:
            print(f"[shadow-compare] Skipping {d}: {exc}")
            continue

        records.append({"date": d, "mpc_cost": mpc_cost, "policy_cost": policy_cost})

    if not records:
        print("[shadow-compare] No usable days in window.")
        return 1

    df = pd.DataFrame(records)
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    if df.empty:
        print("[shadow-compare] All costs are NaN/inf.")
        return 1

    print("\n[shadow-compare] Per-day cost comparison (SEK):")
    for _, row in df.iterrows():
        d = row["date"]
        mpc = float(row["mpc_cost"])
        pol = float(row["policy_cost"])
        delta = pol - mpc
        print(f"  {d}: MPC={mpc:8.2f}  Policy={pol:8.2f}  ΔP-M={delta:7.2f}")

    mpc_total = float(df["mpc_cost"].sum())
    pol_total = float(df["policy_cost"].sum())
    delta_total = pol_total - mpc_total
    rel = (delta_total / mpc_total * 100.0) if mpc_total != 0 else 0.0

    print("\n[shadow-compare] Aggregate stats:")
    print(f"  MPC total:    {mpc_total:8.2f} SEK")
    print(f"  Policy total: {pol_total:8.2f} SEK")
    print(f"  ΔPolicy-MPC:  {delta_total:8.2f} SEK ({rel:0.1f} % of MPC)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
