import sys
import sqlite3
import pandas as pd
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.learning import get_learning_engine


def main():
    print("🔍 Inspecting SQLite NULLs & Values...")

    try:
        engine = get_learning_engine("config.yaml")

        with sqlite3.connect(engine.db_path) as conn:
            # 1. Inspect NULL Actual SoC Rows
            print("\n🕵️  NULL Actual SoC Rows (Sample):")
            null_df = pd.read_sql(
                """
                SELECT slot_start, soc_end_percent, quality_flags, created_at
                FROM slot_observations 
                WHERE DATE(slot_start) >= DATE('now', '-7 days') 
                  AND soc_end_percent IS NULL
                ORDER BY slot_start DESC
                LIMIT 5
            """,
                conn,
            )
            print(null_df)

            # 2. Inspect Planned SoC Values
            print("\n📉 Planned SoC Values (Sample):")
            plan_df = pd.read_sql(
                """
                SELECT slot_start, planned_soc_percent
                FROM slot_plans
                WHERE DATE(slot_start) >= DATE('now', '-7 days')
                ORDER BY slot_start DESC
                LIMIT 5
            """,
                conn,
            )
            print(plan_df)

            # Check if all are 0
            zero_plans = conn.execute(
                """
                SELECT COUNT(*) 
                FROM slot_plans 
                WHERE DATE(slot_start) >= DATE('now', '-7 days') 
                  AND planned_soc_percent = 0
            """
            ).fetchone()[0]
            print(f"   Rows with Planned SoC = 0: {zero_plans}")

    except Exception as e:
        print(f"❌ Inspection failed: {e}")


if __name__ == "__main__":
    main()
