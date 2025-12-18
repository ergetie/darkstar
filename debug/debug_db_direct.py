import sqlite3
import os
import sys

DB_PATH = "learning.db"  # Default guess, checking list_dir next


def check_db(db_path):
    if not os.path.exists(db_path):
        print(f"DB not found at {db_path}")
        return

    print(f"Checking DB: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check Columns in slot_forecasts
        cursor.execute("PRAGMA table_info(slot_forecasts)")
        cols = [r[1] for r in cursor.fetchall()]
        print("slot_forecasts columns:", cols)

        needed = ["pv_p10", "pv_p90", "load_p10", "load_p90"]
        missing = [c for c in needed if c not in cols]
        if missing:
            print("MISSING COLUMNS:", missing)
        else:
            print("p10/p90 columns exist.")

        # Check Recent Data
        print("\nRecent Forecasts with P-values:")
        cursor.execute(
            """
            SELECT slot_start, pv_p10, pv_p90 
            FROM slot_forecasts 
            ORDER BY slot_start DESC LIMIT 5
        """
        )
        for row in cursor.fetchall():
            print(row)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    # Locate DB
    # Based on store.py, it expects a path passed in.
    # Usually it's in data/learning.db or similar.
    # Searching for .db files in current dir...
    target = None
    for f in os.listdir("."):
        if f.endswith(".db"):
            target = f
            break

    if target:
        check_db(target)
    else:
        # Check known location from config defaults or previous learnings
        if os.path.exists("data/learning.db"):
            check_db("data/learning.db")
        else:
            print("Could not find database file.")
