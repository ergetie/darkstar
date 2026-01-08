import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import yaml


def explode_rows():
    config_path = Path("config.yaml")
    with config_path.open() as f:
        config = yaml.safe_load(f)
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
    pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    print(f"--- Exploding Hourly Rows in {db_path} ---")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Select all hourly rows (minute = 00)
        cursor.execute(
            """
            SELECT * FROM slot_observations
            WHERE strftime('%M', slot_start) = '00'
            ORDER BY slot_start
        """
        )
        hourly_rows = cursor.fetchall()

        new_rows = []

        print(f"Found {len(hourly_rows)} hourly rows. Processing...")

        for row in hourly_rows:
            # Parse start time
            try:
                # Handle ISO string with/without timezone
                dt_str = row["slot_start"]
                if dt_str.endswith("Z"):
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromisoformat(dt_str)
            except ValueError:
                continue

            # We assume the values in the :00 row are ALREADY 15-min scaled
            # (because we ran backfill_ha which divided by 4, even if it only updated this one row)
            # OR they are 1-hour values.
            # Given your logs showed 0.02 (which is ~0.1/4), the values in :00 are likely already 15-min scale.
            # So we just clone them.

            load_val = row["load_kwh"]
            pv_val = row["pv_kwh"]
            import_price = row["import_price_sek_kwh"]
            export_price = row["export_price_sek_kwh"]

            # Create :15, :30, :45
            for minutes in [15, 30, 45]:
                new_start = dt + timedelta(minutes=minutes)
                new_end = new_start + timedelta(minutes=15)

                # Check if exists (optimization: try insert ignore or just collect)
                new_rows.append(
                    (
                        new_start.isoformat(),
                        new_end.isoformat(),
                        import_price,
                        export_price,
                        pv_val,
                        load_val,
                    )
                )

        if new_rows:
            print(f"Inserting {len(new_rows)} missing sub-slots...")
            # Use INSERT OR IGNORE so we don't break if some exist
            cursor.executemany(
                """
                INSERT OR IGNORE INTO slot_observations
                (slot_start, slot_end, import_price_sek_kwh, export_price_sek_kwh, pv_kwh, load_kwh)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                new_rows,
            )
            conn.commit()
            print("Done.")
        else:
            print("No rows to explode.")


if __name__ == "__main__":
    explode_rows()
