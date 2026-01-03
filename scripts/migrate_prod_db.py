import logging
import os
import sqlite3
import sys

sys.path.append(os.getcwd())

import pytz

from backend.learning.store import LearningStore

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "data/planner_learning.db"


def migrate_prod():
    if not os.path.exists(DB_PATH):
        print(f"CRITICAL: {DB_PATH} does not exist!")
        return

    print(f"Checking {DB_PATH}...")

    # 1. Check Schema BEFORE
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(slot_forecasts)")
    cols = [r[1] for r in cursor.fetchall()]
    print("Columns BEFORE:", cols)
    conn.close()

    # 2. Trigger Migration
    print("Triggering LearningStore init to run migration...")
    try:
        # Initialize store with correct path
        LearningStore(DB_PATH, pytz.UTC)
        print("Store initialized.")

        # 3. Check Schema AFTER
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(slot_forecasts)")
        cols_after = [r[1] for r in cursor.fetchall()]
        print("Columns AFTER:", cols_after)

        needed = ["pv_p10", "pv_p90"]
        missing = [c for c in needed if c not in cols_after]
        if missing:
            print("MIGRATION FAILED - Columns still missing:", missing)
        else:
            print("SUCCESS: Columns present.")

        # 4. Check Data Presence
        cursor.execute("SELECT COUNT(*) FROM slot_forecasts")
        print(f"Forecast Rows: {cursor.fetchone()[0]}")

        cursor.execute("SELECT COUNT(*) FROM slot_observations")
        print(f"Observation Rows: {cursor.fetchone()[0]}")

        conn.close()

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    migrate_prod()
