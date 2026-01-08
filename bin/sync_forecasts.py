import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.append(str(Path.cwd()))

DB_PATH = "data/planner_learning.db"


def sync_forecasts():
    print(f"Syncing observations to forecasts in {DB_PATH}...")

    with sqlite3.connect(DB_PATH) as conn:
        # Find slots where forecast is suspicious (< 0.01) but observation is valid (> 0.01)
        # We need to join the tables.
        # Note: slot_forecasts has 'forecast_version' column. We should target 'aurora'.

        query = """
            SELECT
                f.slot_start,
                f.load_forecast_kwh as f_load,
                o.load_kwh as o_load,
                f.pv_forecast_kwh as f_pv,
                o.pv_kwh as o_pv
            FROM slot_forecasts f
            JOIN slot_observations o ON f.slot_start = o.slot_start
            WHERE f.forecast_version = 'aurora'
              AND (f.load_forecast_kwh < 0.01 OR f.load_forecast_kwh IS NULL)
              AND o.load_kwh > 0.01
        """

        df = pd.read_sql_query(query, conn)

        if df.empty:
            print("No discrepancies found.")
            return

        print(f"Found {len(df)} slots with bad forecasts but valid observations.")
        print(df.head())

        cursor = conn.cursor()
        count = 0

        for _, row in df.iterrows():
            slot_start = row["slot_start"]
            new_load = row["o_load"]
            # We can also sync PV if forecast is 0 but obs is > 0, but let's focus on load first.
            # Actually, let's sync PV too if it's bad.
            new_pv = row["f_pv"]
            if (row["f_pv"] < 0.01 or pd.isna(row["f_pv"])) and row["o_pv"] > 0.01:
                new_pv = row["o_pv"]

            cursor.execute(
                """
                UPDATE slot_forecasts
                SET load_forecast_kwh = ?, pv_forecast_kwh = ?
                WHERE slot_start = ? AND forecast_version = 'aurora'
            """,
                (new_load, new_pv, slot_start),
            )
            count += 1

        conn.commit()
        print(f"Updated {count} forecast rows.")


if __name__ == "__main__":
    sync_forecasts()
