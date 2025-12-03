import sys
import sqlite3
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine

def main():
    print("🔍 Checking for Duplicates in SQLite...")
    
    try:
        engine = get_learning_engine("config.yaml")
        
        with sqlite3.connect(engine.db_path) as conn:
            # Print all timestamps to see formats
            print("\n📅 All Timestamps (Nov 24):")
            query = """
                SELECT slot_start
                FROM slot_observations
                WHERE slot_start LIKE '2025-11-24%'
                ORDER BY slot_start ASC
                LIMIT 20
            """
            rows = conn.execute(query).fetchall()
            for r in rows:
                print(f"   '{r[0]}'")
            
            # Check count of unique timestamps vs total rows
            total_rows = conn.execute("SELECT COUNT(*) FROM slot_observations WHERE DATE(slot_start) = '2025-11-24'").fetchone()[0]
            unique_slots = conn.execute("SELECT COUNT(DISTINCT slot_start) FROM slot_observations WHERE DATE(slot_start) = '2025-11-24'").fetchone()[0]
            
            print(f"\n   Total Rows (Nov 24): {total_rows}")
            print(f"   Unique Slots:        {unique_slots}")
            
            if total_rows > unique_slots:
                print("   ⚠️  DUPLICATES FOUND!")
            else:
                print("   ✅ No duplicates found (based on exact string match).")

    except Exception as e:
        print(f"❌ Check failed: {e}")

if __name__ == "__main__":
    main()
