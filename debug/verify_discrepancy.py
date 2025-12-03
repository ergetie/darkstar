import sys
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, date
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine

# User provided data
USER_IMPORT_NOV_24_30 = 258.0
USER_LOAD_NOV_24_30 = 276.0

USER_PRICES_IMPORT_TODAY = [
    1.9236, 1.9204, 2.0693, 2.0661, 2.0252, 2.0157, 2.0665, 2.0647, 2.0623, 2.0608, 2.0634, 2.062, 
    1.9561, 1.9555, 2.0331, 2.0356, 1.958, 1.987, 2.0028, 2.0165, 2.0541, 2.0668, 2.0724, 2.0785, 
    2.087, 2.1017, 2.1448, 2.1697, 2.1568, 2.215, 2.3214, 2.575, 2.5273, 2.6104, 2.6454, 2.8666, 
    3.7075, 3.2738, 2.6936, 2.5781, 3.0723, 2.8066, 2.7232, 2.7082, 2.2495, 2.2532, 2.2392, 2.2303, 
    2.2003, 2.2002, 2.1973, 2.1966, 2.1476, 2.1498, 2.1498, 2.1488, 2.1412, 2.1501, 2.155, 2.1594, 
    2.1205, 2.1242, 2.1194, 2.1143, 2.1825, 2.129, 2.1506, 2.1396, 2.3236, 2.3225, 2.245, 2.1961, 
    2.9436, 2.8358, 2.8386, 2.4732, 3.0713, 3.1557, 2.9779, 2.561, 3.1197, 2.8455, 2.2388, 2.1886, 
    2.1461, 2.1194, 2.0951, 2.0684, 2.0837, 2.0859, 2.0757, 1.9661, 2.0423, 2.0347, 1.9933, 1.8764
]

def main():
    print("🔍 Verifying Discrepancy...")
    
    try:
        engine = get_learning_engine("config.yaml")
        
        with sqlite3.connect(engine.db_path) as conn:
            # 1. Check Consumption (Nov 24-30)
            print("\n📅 Consumption Check (Nov 24-30):")
            query_cons = """
                SELECT 
                    SUM(import_kwh) as total_import,
                    SUM(load_kwh) as total_load,
                    COUNT(*) as slots
                FROM slot_observations
                WHERE DATE(slot_start) BETWEEN '2025-11-24' AND '2025-11-30'
            """
            res_cons = conn.execute(query_cons).fetchone()
            ds_import = res_cons[0] or 0.0
            ds_load = res_cons[1] or 0.0
            slots = res_cons[2]
            
            print(f"   Slots Found: {slots} (Expected ~{7*24*4} = 672)")
            
            print(f"{'Metric':<15} | {'User (HA)':<15} | {'Darkstar':<15} | {'Diff':<10}")
            print("-" * 60)
            print(f"{'Import (kWh)':<15} | {USER_IMPORT_NOV_24_30:<15.2f} | {ds_import:<15.2f} | {ds_import - USER_IMPORT_NOV_24_30:+.2f}")
            print(f"{'Load (kWh)':<15} | {USER_LOAD_NOV_24_30:<15.2f} | {ds_load:<15.2f} | {ds_load - USER_LOAD_NOV_24_30:+.2f}")
            
            if abs(ds_import - USER_IMPORT_NOV_24_30) > 10:
                print("\n⚠️  MAJOR IMPORT DISCREPANCY!")
                print("   Darkstar is recording significantly different import values.")
            
            # 2. Check Prices (Today - Dec 3)
            print("\n💰 Price Check (Today - Dec 3):")
            query_price = """
                SELECT import_price_sek_kwh
                FROM slot_observations
                WHERE DATE(slot_start) = '2025-12-03'
                ORDER BY slot_start ASC
            """
            ds_prices = [r[0] for r in conn.execute(query_price).fetchall()]
            
            # Compare lengths
            len_user = len(USER_PRICES_IMPORT_TODAY)
            len_ds = len(ds_prices)
            print(f"   User Price Points: {len_user}")
            print(f"   Darkstar Price Points: {len_ds}")
            
            # Compare values (first 10)
            print("\n   Sample Comparison (First 10 slots):")
            print(f"   {'Slot':<5} | {'User':<10} | {'Darkstar':<10} | {'Diff':<10}")
            print("-" * 45)
            for i in range(min(10, len_user, len_ds)):
                u = USER_PRICES_IMPORT_TODAY[i]
                d = ds_prices[i]
                print(f"   {i:<5} | {u:<10.4f} | {d:<10.4f} | {d-u:+.4f}")
                
            # Calculate MAE
            if len_ds == len_user:
                mae = np.mean(np.abs(np.array(ds_prices) - np.array(USER_PRICES_IMPORT_TODAY)))
                print(f"\n   Mean Absolute Error: {mae:.4f} SEK")
                if mae < 0.01:
                    print("✅ Prices match perfectly!")
                else:
                    print("⚠️  Prices differ!")
            else:
                print("\n⚠️  Length mismatch, cannot calculate full MAE.")

    except Exception as e:
        print(f"❌ Verification failed: {e}")

if __name__ == "__main__":
    main()
