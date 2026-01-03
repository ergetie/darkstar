import os
import sqlite3

DB_PATH = "data/planner_learning.db"


def clean_db():
    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    print(f"🧹 Cleaning {DB_PATH}...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Count bad rows first
        cursor.execute("SELECT COUNT(*) FROM slot_observations WHERE load_kwh < 0.01")
        count = cursor.fetchone()[0]

        if count == 0:
            print("✅ Database is already clean! No zero-load records found.")
            return

        print(f"⚠️ Found {count} invalid zero-load records.")

        # Delete them
        cursor.execute("DELETE FROM slot_observations WHERE load_kwh < 0.01")
        conn.commit()

        print(f"✅ Deleted {count} records. The AI will stop learning from these ghosts.")
        print(
            "💡 Note: You may need to wait for the next nightly learning run (or trigger it manually) for the bias to disappear."
        )

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    clean_db()
