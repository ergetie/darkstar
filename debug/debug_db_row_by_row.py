import yaml
import pymysql
import sys
from db_writer import _load_schedule, _map_row


def find_bad_row():
    print("🕵️  Starting Row-by-Row Database Insert Test...")

    try:
        # Load Config & Secrets
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        with open("secrets.yaml", "r") as f:
            secrets = yaml.safe_load(f)

        # Connect
        db = secrets.get("mariadb", {})
        conn = pymysql.connect(
            host=db.get("host", "127.0.0.1"),
            port=int(db.get("port", 3306)),
            user=db.get("user"),
            password=db.get("password"),
            database=db.get("database"),
            charset="utf8mb4",
            autocommit=True,
        )

        # Load Data
        rows = _load_schedule("schedule.json")
        print(f"📦 Loaded {len(rows)} rows from schedule.json")

        planner_version = "debug-row-test"
        tz_name = config.get("timezone", "Europe/Stockholm")

        # Prepare SQL
        columns = [
            "slot_number",
            "slot_start",
            "charge_kw",
            "export_kw",
            "water_kw",
            "planned_load_kwh",
            "planned_pv_kwh",
            "soc_target",
            "soc_projected",
            "planner_version",
        ]
        cols_str = ", ".join(columns)
        vals_str = ", ".join(["%s"] * len(columns))
        sql = f"INSERT INTO current_schedule ({cols_str}) VALUES ({vals_str})"

        # Clean table first (Optional, but keeps it clean)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM current_schedule")

        # Insert One by One
        print("🚀 Inserting...")
        for i, slot in enumerate(rows):
            # Map exactly as the writer does
            mapped = _map_row(i, slot, tz_name=tz_name)
            row_data = mapped + (planner_version,)

            try:
                with conn.cursor() as cur:
                    cur.execute(sql, row_data)
            except Exception as e:
                print(f"\n❌ CRASH ON ROW {i} (Slot {slot.get('slot_number')})!")
                print(f"Error: {e}")
                print(f"Data: {row_data}")
                print(f"      -> Planned PV (Item 6): {row_data[6]}")
                return

        print("\n✅ SUCCESS! All rows inserted individually without error.")
        print(
            "   (This implies the previous error might have been a transient batch issue or the first row was indeed the culprit but works now?)"
        )

    except Exception as e:
        print(f"❌ System Error: {e}")
    finally:
        if "conn" in locals():
            conn.close()


if __name__ == "__main__":
    find_bad_row()
