import os
import sqlite3

import yaml


def get_db_path():
    try:
        with open("config.yaml") as f:
            config = yaml.safe_load(f)
        return config.get("learning", {}).get("db_path", "data/learning.db")
    except:
        return "data/learning.db"


def inspect_tables():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        if os.path.exists("test.db"):
            db_path = "test.db"
        else:
            print("No DB found.")
            return

    print(f"Inspecting DB: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Check Observations
        cursor.execute("SELECT COUNT(*) FROM slot_observations")
        count_obs = cursor.fetchone()[0]
        print(f"slot_observations count: {count_obs}")

        if count_obs > 0:
            cursor.execute(
                "SELECT slot_start, pv_kwh, load_kwh FROM slot_observations ORDER BY slot_start DESC LIMIT 3"
            )
            print("Recent Observations:", cursor.fetchall())

        # Check Forecasts
        cursor.execute("SELECT COUNT(*) FROM slot_forecasts")
        count_fc = cursor.fetchone()[0]
        print(f"slot_forecasts count: {count_fc}")

        if count_fc > 0:
            cursor.execute(
                "SELECT slot_start, pv_forecast_kwh, date(slot_start) FROM slot_forecasts ORDER BY slot_start DESC LIMIT 3"
            )
            print("Recent Forecasts:", cursor.fetchall())

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    inspect_tables()
