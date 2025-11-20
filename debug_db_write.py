import yaml
import os
import sys
# Import internal mapping function to spy on the data
from db_writer import write_schedule_to_db, _load_schedule, _map_row

def try_write():
    print("💾 Attempting to write schedule.json to DB...")
    
    if not os.path.exists("config.yaml"):
        print("❌ config.yaml missing")
        return

    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        
        # 1. Inspect the raw data first
        print("\n🕵️  INSPECTING DATA PREPARATION:")
        rows = _load_schedule("schedule.json")
        if not rows:
            print("❌ Schedule is empty!")
            return

        # Map the first row exactly as the writer does
        first_mapped = _map_row(0, rows[0], tz_name=config.get("timezone", "Europe/Stockholm"))
        
        print(f"Row 0 Raw PV: '{rows[0].get('pv_forecast_kwh')}'")
        print(f"Row 0 Mapped Tuple: {first_mapped}")
        print(f"   -> Planned PV is item #6: {first_mapped[6]}")

        # Check if it looks like a valid number
        pv_val = first_mapped[6]
        if pv_val < 0:
            print("❌ PV is Negative!")
        elif pv_val > 99:
            print("⚠️ PV is unusually large (>99). Schema might be DECIMAL(4,2)?")
        
        # 2. Try the actual write
        print("\n🚀 Sending to MariaDB...")
        with open("secrets.yaml", "r") as f:
            secrets = yaml.safe_load(f)
            
        count = write_schedule_to_db(
            schedule_path="schedule.json", 
            planner_version="debug-run", 
            config=config, 
            secrets=secrets
        )
        print(f"✅ Success! Wrote {count} rows.")
        
    except Exception as e:
        print("\n❌ CRITICAL ERROR CAUGHT:")
        print("-" * 40)
        import traceback
        traceback.print_exc()
        print("-" * 40)

if __name__ == "__main__":
    try_write()