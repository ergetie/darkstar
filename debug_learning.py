import sqlite3
import pandas as pd
import json
import os

DB_PATH = "data/planner_learning.db"

def check_learning():
    print(f"🔍 Inspecting {DB_PATH} for learned biases...")
    
    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        
        # Get the latest learning metrics applied to the plan
        query = """
        SELECT date, load_adjustment_by_hour_kwh, pv_adjustment_by_hour_kwh 
        FROM learning_daily_metrics 
        ORDER BY date DESC LIMIT 1
        """
        df = pd.read_sql_query(query, conn)
        
        if not df.empty:
            row = df.iloc[0]
            print(f"📅 Latest Learning Date: {row['date']}")
            
            load_adj = json.loads(row['load_adjustment_by_hour_kwh']) if row['load_adjustment_by_hour_kwh'] else []
            
            print("\n📉 Hourly Load Adjustments (kWh):")
            print("(Negative values mean the AI reduces your forecast)")
            for h, val in enumerate(load_adj):
                flag = "⚠️ PROBLEM" if val < -0.2 else ""
                print(f"  Hour {h:02d}: {val:.4f} {flag}")
                
        else:
            print("⚠️ No learning metrics found in DB.")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    check_learning()