import sqlite3
import yaml
import os


def fix_price_gaps():
    # Load config to find DB
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")

    print(f"--- Fixing Price Gaps in {db_path} ---")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # 1. Get all rows sorted by time
        cursor.execute(
            """
            SELECT slot_start, import_price_sek_kwh, export_price_sek_kwh
            FROM slot_observations
            ORDER BY slot_start ASC
        """
        )
        rows = cursor.fetchall()

        updates = []
        last_valid_import = None
        last_valid_export = None
        last_valid_hour_str = None

        for slot_start, imp, exp in rows:
            # slot_start format: '2025-11-10T05:15:00+01:00'
            # Extract the "Hour" part (e.g., '2025-11-10T05')
            # This ensures we only forward-fill within the SAME hour.
            current_hour_str = slot_start[:13]

            if imp is not None:
                # We found a master record (usually the :00 slot)
                last_valid_import = imp
                last_valid_export = exp
                last_valid_hour_str = current_hour_str
            else:
                # We found a hole. Can we fill it?
                if last_valid_import is not None and current_hour_str == last_valid_hour_str:
                    # Yes, same hour. Fill it.
                    updates.append((last_valid_import, last_valid_export, slot_start))

        if updates:
            print(f"Found {len(updates)} gaps to fill.")
            print("Applying updates...")
            cursor.executemany(
                """
                UPDATE slot_observations
                SET import_price_sek_kwh = ?, export_price_sek_kwh = ?
                WHERE slot_start = ?
            """,
                updates,
            )
            conn.commit()
            print("Success.")
        else:
            print("No gaps found (or no master records to fill from).")


if __name__ == "__main__":
    fix_price_gaps()
