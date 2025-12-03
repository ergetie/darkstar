import sys
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine

def main():
    print("🔍 Verifying Backfill Status...")
    
    try:
        engine = get_learning_engine("config.yaml")
        db_path = engine.db_path
        timezone = engine.timezone
        
        print(f"📂 Database: {db_path}")
        print(f"🌍 Timezone: {timezone}")
        
        with sqlite3.connect(db_path) as conn:
            # Check last 24 hours
            now = datetime.now(timezone)
            start_time = now - timedelta(hours=24)
            
            query = """
                SELECT COUNT(*), MIN(slot_start), MAX(slot_start)
                FROM slot_observations
                WHERE slot_start >= ?
            """
            row = conn.execute(query, (start_time.isoformat(),)).fetchone()
            count, min_ts, max_ts = row
            
            print(f"\n📊 Observations in last 24h: {count}")
            if count > 0:
                print(f"   Earliest: {min_ts}")
                print(f"   Latest:   {max_ts}")
                
                # Check for gaps
                expected_slots = 24 * 4 # 15 min slots
                print(f"   Expected: ~{expected_slots} slots")
                
                if count >= expected_slots * 0.9:
                    print("✅ Backfill appears successful (coverage > 90%)")
                else:
                    print("⚠️  Coverage low. Check logs for backfill errors.")
            else:
                print("❌ No observations found in last 24h!")

    except Exception as e:
        print(f"❌ Verification failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
