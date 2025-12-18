import sys
import os
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import pytz

sys.path.append(os.getcwd())
try:
    from backend.learning.store import LearningStore
except ImportError:
    # Minimal mock if import fails (shouldn't happen in verified env)
    pass

DB_PATH = "data/planner_learning.db"


def check_window():
    print(f"Checking window in {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("DB not found.")
        return

    conn = sqlite3.connect(DB_PATH)

    # Get Now (UTC implied by DB usually, or ISO strings)
    # The DB stores ISO strings with offsets usually

    # Let's count rows passing a simple string filter for "2025-12-12" (Today)
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM slot_observations WHERE slot_start LIKE '2025-12-12%'")
    count_today = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM slot_observations WHERE slot_start LIKE '2025-12-11%'")
    count_yesterday = cursor.fetchone()[0]

    print(f"Rows for 2025-12-12 (Today): {count_today}")
    print(f"Rows for 2025-12-11 (Yesterday): {count_yesterday}")

    if count_today > 0:
        cursor.execute(
            "SELECT slot_start, pv_kwh FROM slot_observations WHERE slot_start LIKE '2025-12-12%' ORDER BY slot_start DESC LIMIT 3"
        )
        print("Sample Today:", cursor.fetchall())

    conn.close()


if __name__ == "__main__":
    check_window()
