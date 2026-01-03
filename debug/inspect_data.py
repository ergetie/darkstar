import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine


def main():
    print("🔍 Inspecting Recent Data (Last 7 Days)...")

    try:
        engine = get_learning_engine("config.yaml")

        with sqlite3.connect(engine.db_path) as conn:
            now = datetime.now(engine.timezone)
            start_time = now - timedelta(days=7)

            print(f"📅 Window: {start_time} to {now}")

            # Check NULL SoC in last 7 days
            query = """
                SELECT COUNT(*), COUNT(soc_end_percent)
                FROM slot_observations
                WHERE slot_start >= ?
            """
            row = conn.execute(query, (start_time.isoformat(),)).fetchone()
            total_slots, soc_slots = row

            print("\n📊 Recent Stats:")
            print(f"   Total Slots: {total_slots}")
            print(f"   Slots with SoC: {soc_slots}")
            print(f"   Missing SoC: {total_slots - soc_slots}")

            if total_slots - soc_slots > 0:
                print("\n   Sample Missing SoC Slots:")
                df = pd.read_sql(
                    """
                    SELECT slot_start, soc_end_percent 
                    FROM slot_observations 
                    WHERE slot_start >= ? AND soc_end_percent IS NULL 
                    ORDER BY slot_start DESC
                    LIMIT 10
                """,
                    conn,
                    params=(start_time.isoformat(),),
                )
                print(df)

    except Exception as e:
        print(f"❌ Inspection failed: {e}")


if __name__ == "__main__":
    main()
