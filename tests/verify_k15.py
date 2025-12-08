
import os
import sys
import sqlite3
import yaml
from datetime import datetime
import pandas as pd
import pytz

# Add project root to path
sys.path.insert(0, os.getcwd())

from backend.learning import get_learning_engine
from planner.pipeline import PlannerPipeline
from inputs import get_all_input_data

def verify_db_forecasts():
    print("--- Verifying DB Forecasts ---")
    engine = get_learning_engine()
    with sqlite3.connect(engine.db_path) as conn:
        cursor = conn.cursor()
        # Check columns
        cursor.execute("PRAGMA table_info(slot_forecasts)")
        cols = [info[1] for info in cursor.fetchall()]
        print(f"Columns in slot_forecasts: {cols}")
        
        required = ["pv_p10", "pv_p90", "load_p10", "load_p90"]
        missing = [c for c in required if c not in cols]
        if missing:
            print(f"❌ Missing columns: {missing}")
            return False
            
        # Check data for future slots
        now = datetime.now().isoformat()
        cursor.execute(f"SELECT COUNT(*), COUNT(pv_p10), COUNT(load_p90) FROM slot_forecasts WHERE slot_start > '{now}'")
        row = cursor.fetchone()
        print(f"Future slots: {row[0]}, Non-null pv_p10: {row[1]}, Non-null load_p90: {row[2]}")
        
        if row[0] > 0 and row[1] == row[0]:
            print("✅ Probabilistic forecasts present in DB.")
            return True
        else:
            print("❌ Forecasts missing or null.")
            return False

def verify_planner_pipeline():
    print("\n--- Verifying Planner Pipeline ---")
    try:
        # Load inputs
        print("Fetching inputs...")
        input_data = get_all_input_data("config.yaml")
        
        # Load config
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
            
        print(f"Config S-Index Mode: {config.get('s_index', {}).get('mode')}")
        
        pipeline = PlannerPipeline(config)
        # Run schedule generation (mocking save to file to avoid overwriting real schedule if needed, 
        # but overwrite is fine for dev)
        df = pipeline.generate_schedule(input_data, save_to_file=False)
        
        print(f"Generated schedule with {len(df)} slots.")
        if not df.empty:
            print("✅ Planner ran successfully.")
            return True
        else:
            print("❌ Planner returned empty dataframe.")
            return False
            
    except Exception as e:
        print(f"❌ Planner execution failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    db_ok = verify_db_forecasts()
    planner_ok = verify_planner_pipeline()
    
    if db_ok and planner_ok:
        print("\n✅ VERIFICATION SUCCESSFUL")
        sys.exit(0)
    else:
        print("\n❌ VERIFICATION FAILED")
        sys.exit(1)
