import os
import sqlite3

DB_PATH = "data/planner_learning.db"


def check_forecasts():
    print(f"🔍 Checking forecast horizon in {DB_PATH}...")

    if not os.path.exists(DB_PATH):
        print("❌ Database not found.")
        return

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Check the furthest future timestamp
        cursor.execute("SELECT MAX(slot_start) FROM slot_forecasts")
        max_date = cursor.fetchone()[0]
        print(f"🚀 Furthest Forecast Available: {max_date}")

        # Count slots per day for the next 5 days
        print("\n📊 Slots per day (Future):")
        query = """
        SELECT date(slot_start) as day, count(*) 
        FROM slot_forecasts 
        WHERE slot_start >= date('now') 
        GROUP BY day 
        ORDER BY day ASC
        LIMIT 7
        """
        for row in cursor.execute(query):
            print(f"   {row[0]}: {row[1]} slots")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    check_forecasts()
