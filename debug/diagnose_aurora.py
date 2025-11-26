import sqlite3
import pandas as pd
from datetime import datetime
from learning import get_learning_engine
from ml.corrector import _determine_graduation_level, _count_days_with_data

engine = get_learning_engine()

print("--- 1. CHECKING BRAIN MATURITY ---")
level = _determine_graduation_level(engine)
days = _count_days_with_data(engine)
print(f"Days of Data: {days}")
print(f"Level:        {level.level} ({level.label})")

if level.level == 0:
    print("⚠️  System is INFANT. Corrections are disabled by design.")
else:
    print("✅ System is SMART. Corrections should be active.")

print("\n--- 2. CHECKING RAW DB FORMAT ---")
# We need to see exactly how the timestamp is stored (string literal)
with sqlite3.connect(engine.db_path) as conn:
    rows = conn.execute("""
        SELECT slot_start, correction_source
        FROM slot_forecasts
        WHERE forecast_version='aurora'
        AND slot_start > datetime('now')
        ORDER BY slot_start ASC LIMIT 3
    """).fetchall()

if not rows:
    print("❌ No future forecasts found.")
else:
    print(f"Raw Timestamp in DB:   '{rows[0][0]}'")
    print(f"Current Source in DB:  '{rows[0][1]}'")

print("\n--- 3. PIPELINE SIMULATION ---")
# Let's see what the corrector *wants* to do vs what is saved
from ml.corrector import predict_corrections
try:
    corrections, source = predict_corrections(horizon_hours=2)
    if not corrections:
        print("⚠️ Corrector returned NO rows.")
    else:
        first = corrections[0]
        print(f"Corrector Output Time: '{first['slot_start']}' (Type: {type(first['slot_start'])})")
        print(f"Corrector Output Src:  '{source}'")

        # Check for mismatch
        db_time_str = rows[0][0] if rows else "N/A"
        py_time_iso = first['slot_start'].isoformat() if hasattr(first['slot_start'], 'isoformat') else str(first['slot_start'])

        if rows and db_time_str != py_time_iso:
            print(f"\n❌ MISMATCH DETECTED!")
            print(f"DB Expects: '{db_time_str}'")
            print(f"Py Offers:  '{py_time_iso}'")
            print("The UPDATE clause is failing to find the row because strings don't match.")
        elif rows:
            print("\n✅ Timestamp formats match.")

except Exception as e:
    print(f"Pipeline Error: {e}")
