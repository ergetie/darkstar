import logging
import os
import sys

sys.path.append(os.getcwd())

import pytz

from backend.learning.store import LearningStore

# Setup logging to see migration errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = "data/learning.db"
if not os.path.exists(DB_PATH):
    print(f"Warning: {DB_PATH} not found, trying test.db")
    DB_PATH = "test.db"

print(f"Initializing store at {DB_PATH} to trigger migration...")
try:
    store = LearningStore(DB_PATH, pytz.UTC)
    print("Store initialized.")

    # Now check columns via SQL raw
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(slot_forecasts)")
    cols = [r[1] for r in cursor.fetchall()]
    print("Columns after init:", cols)

    conn.close()

except Exception as e:
    print(f"Error: {e}")
