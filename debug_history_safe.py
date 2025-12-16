import sys
import os
import yaml
import pytz
from datetime import datetime, timedelta
import pandas as pd

# Add project root to path
sys.path.append(os.getcwd())

from backend.learning.store import LearningStore

def get_db_path():
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
            # Try to find db path in config, default to data/learning.db
            return config.get("learning", {}).get("db_path", "data/learning.db")
    except:
        return "data/learning.db"

def debug_safe():
    db_path = get_db_path()
    print(f"Target DB: {db_path}")
    
    if not os.path.exists(db_path):
        print("DB file not found! Checking current dir for alternatives...")
        if os.path.exists("test.db"):
            print("Found test.db, using that.")
            db_path = "test.db"
        else:
            print("No DB found.")
            return

    try:
        # Initialize Store (lightweight)
        store = LearningStore(db_path, pytz.UTC)
        
        # 1. Fetch Data
        print("\n--- Fetching Last 48h (PV) ---")
        df = store.get_forecast_vs_actual(days_back=2, target="pv")
        
        print(f"Rows returned: {len(df)}")
        if df.empty:
            print("DataFrame is empty.")
        else:
            print("Columns:", df.columns.tolist())
            print("\nRecent 5 rows:")
            print(df.tail(5)[["slot_start", "actual", "forecast", "p10", "p90"]])
            
            # Check timestamps
            last_ts = df.iloc[-1]["slot_start"]
            print(f"\nLast data point time: {last_ts}")
            
            # Check comparisons for filtering
            now = datetime.now(pytz.UTC)
            start_check = (now - timedelta(hours=24)).isoformat()
            
            print(f"Now (UTC): {now}")
            print(f"Would filter >=: {start_check}")
            
            filtered = df[df["slot_start"] >= start_check]
            print(f"Rows after -24h filter: {len(filtered)}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_safe()
