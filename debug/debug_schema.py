import os
import sqlite3

from learning import get_learning_engine

engine = get_learning_engine()
print(f"PYTHON CONFIG DB PATH: {engine.db_path}")
print(f"PYTHON ABSOLUTE PATH:  {os.path.abspath(engine.db_path)}")

# Check schema from within Python
with sqlite3.connect(engine.db_path) as conn:
    cursor = conn.execute("PRAGMA table_info(slot_forecasts)")
    columns = [row[1] for row in cursor.fetchall()]
    print("\nPYTHON SEES COLUMNS:")
    print(columns)

if "pv_correction_kwh" in columns:
    print("\n✅ SUCCESS: Python sees the new columns.")
else:
    print("\n❌ FAILURE: Python does NOT see the new columns.")
