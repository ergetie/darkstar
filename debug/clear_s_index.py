import os
import sqlite3

DB_PATH = "data/planner_learning.db"


def clear_s_index():
    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    print(f"🧹 Removing stored S-index from {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Set s_index_base_factor to NULL for the latest entry
        # This forces the planner to use config.yaml
        cursor.execute(
            """
            UPDATE learning_daily_metrics 
            SET s_index_base_factor = NULL 
            WHERE date = date('now') OR date = '2025-11-20'
        """
        )

        if cursor.rowcount > 0:
            print(f"✅ Successfully cleared S-index from {cursor.rowcount} row(s).")
            print("🚀 The planner will now respect your config.yaml value (1.5).")
        else:
            print("⚠️ No rows updated. Maybe the date didn't match?")

        conn.commit()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    clear_s_index()
