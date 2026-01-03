import json
import math


def check_health():
    print("🏥 Checking schedule.json health...")
    try:
        with open("schedule.json") as f:
            # Load as raw string first to check for NaN literal which isn't standard JSON
            raw = f.read()
            if "NaN" in raw:
                print("❌ FAIL: Found 'NaN' in schedule.json! This breaks the DB writer.")
                return

            data = json.loads(raw)

        schedule = data.get("schedule", [])
        print(f"✅ JSON structure is valid. Checking {len(schedule)} slots for bad numbers...")

        bad_slots = 0
        for i, slot in enumerate(schedule):
            for key, val in slot.items():
                if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    print(f"❌ Slot {i} has bad value: {key} = {val}")
                    bad_slots += 1

        if bad_slots == 0:
            print("✅ All numbers look safe.")
        else:
            print(f"⚠️ Found {bad_slots} slots with bad numbers.")

    except Exception as e:
        print(f"❌ Error parsing file: {e}")


if __name__ == "__main__":
    check_health()
