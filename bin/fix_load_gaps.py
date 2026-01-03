import sqlite3

import yaml


def fix_load_gaps():
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")

    print(f"--- Fixing Load/PV Gaps in {db_path} ---")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()

        # Get all rows
        cursor.execute(
            """
            SELECT slot_start, load_kwh, pv_kwh
            FROM slot_observations
            ORDER BY slot_start ASC
        """
        )
        rows = cursor.fetchall()

        updates = []
        last_hour_str = None
        current_hour_load = 0.0
        current_hour_pv = 0.0

        # Pass 1: Identify hourly masters and distribute
        for slot_start, load, pv in rows:
            hour_str = slot_start[:13]  # '2025-11-10T05'

            # Heuristic: If we see a big number (>0) followed by zeros, it's an hourly sum
            # Note: HA returns "change" for the hour.
            # We need to spread it.

            if (load and load > 0) or (pv and pv > 0):
                # Found data. Is it an hourly sum sitting in the :00 slot?
                # We assume yes if we are running this fix.

                # Divide by 4 to get per-15-min avg power equivalent
                val_load = float(load or 0) / 4.0
                val_pv = float(pv or 0) / 4.0

                # Update THIS slot (the master)
                updates.append((val_load, val_pv, slot_start))

                # Store for the next 3 slots
                current_hour_load = val_load
                current_hour_pv = val_pv
                last_hour_str = hour_str

            elif last_hour_str == hour_str:
                # We are in the :15, :30, :45 of a known hour
                # Fill with the distributed value
                updates.append((current_hour_load, current_hour_pv, slot_start))

        if updates:
            print(f"Applying {len(updates)} fix updates...")
            cursor.executemany(
                """
                UPDATE slot_observations
                SET load_kwh = ?, pv_kwh = ?
                WHERE slot_start = ?
            """,
                updates,
            )
            conn.commit()
            print("Done.")
        else:
            print("No updates needed.")


if __name__ == "__main__":
    fix_load_gaps()
