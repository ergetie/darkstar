import argparse
import sqlite3
from datetime import date

import yaml


def get_db_path() -> str:
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    return config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")


def scan_tail(start_date: str, end_date: str | None = None) -> None:
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    params = [start_date]
    where = "date(slot_start) >= ?"

    if end_date is not None:
        where += " AND date(slot_start) <= ?"
        params.append(end_date)

    query = f"""
        SELECT date(slot_start) AS d,
               COUNT(*) AS num_slots,
               SUM(
                   CASE
                       WHEN import_price_sek_kwh IS NULL
                            OR import_price_sek_kwh = 0.0
                       THEN 1
                       ELSE 0
                   END
               ) AS num_zero,
               MIN(import_price_sek_kwh),
               MAX(import_price_sek_kwh)
        FROM slot_observations
        WHERE {where}
        GROUP BY d
        ORDER BY d;
    """

    print(
        f"[rev74] Tail price scan {start_date}{' → ' + end_date if end_date else ''} in {db_path}"
    )

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    for d, num_slots, num_zero, pmin, pmax in rows:
        flag = ""
        # Production rule: if almost all slots are zero / null, mark as bad.
        if num_slots >= 90 and num_zero >= 80:
            flag = "PRICE_BAD"
        print(f"{d}: slots={num_slots}, zero_or_null={num_zero}, min={pmin}, max={pmax} {flag}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Scan tail window for days with broken import prices in slot_observations.")
    )
    parser.add_argument(
        "--start-date",
        required=False,
        default=date.today().isoformat(),
        help="Start date (YYYY-MM-DD), default: today.",
    )
    parser.add_argument(
        "--end-date",
        required=False,
        help="Optional end date (YYYY-MM-DD).",
    )

    args = parser.parse_args()
    scan_tail(args.start_date, args.end_date)


if __name__ == "__main__":
    main()
