
import sys
import os
import pandas as pd
import lightgbm as lgb
from datetime import datetime, timedelta
import pytz

# Add project root to path
sys.path.append(os.getcwd())

from backend.learning import get_learning_engine
from ml.forward import _load_models, generate_forward_slots

def debug_aurora():
    print("--- 🧠 Aurora ML Debugger ---")
    
    # 1. Check Learning Engine
    try:
        engine = get_learning_engine()
        print(f"✅ Learning Engine loaded. DB: {engine.db_path}")
        print(f"   Timezone: {engine.timezone}")
    except Exception as e:
        print(f"❌ Failed to load Learning Engine: {e}")
        return

    # 2. Check Models
    print("\n--- Model Loading ---")
    models = _load_models("ml/models")
    if not models:
        print("❌ No models found in ml/models!")
    else:
        for name, booster in models.items():
            print(f"✅ Loaded {name}: {booster.num_trees()} trees")

    # 3. Test Inference Logic (Forward)
    print("\n--- Inference Test ---")
    try:
        # Hijack print to capture output? No, just run it.
        generate_forward_slots(horizon_hours=48, forecast_version="aurora_debug")
    except Exception as e:
        print(f"❌ Inference failed: {e}")
        import traceback
        traceback.print_exc()

    # 4. Check outputs in DB
    print("\n--- DB Inspection ---")
    import sqlite3
    with sqlite3.connect(engine.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT slot_start, pv_forecast_kwh, load_forecast_kwh FROM slot_forecasts WHERE forecast_version='aurora_debug' ORDER BY slot_start LIMIT 5")
        rows = cursor.fetchall()
        if not rows:
            print("❌ No forecast rows found for 'aurora_debug'!")
        else:
            print(f"✅ Found {len(rows)} rows (first 5):")
            for r in rows:
                print(f"   {r[0]}: PV={r[1]:.4f}, Load={r[2]:.4f}")

if __name__ == "__main__":
    debug_aurora()
