import json


def check_pv():
    print("🔍 Checking PV values in schedule.json...")
    with open("schedule.json", "r") as f:
        data = json.load(f)

    min_pv = 0.0
    bad_count = 0

    for i, slot in enumerate(data["schedule"]):
        pv = slot.get("pv_forecast_kwh", 0.0)
        if pv < 0:
            print(f"❌ Slot {i}: PV = {pv} (Negative!)")
            if pv < min_pv:
                min_pv = pv
            bad_count += 1

    if bad_count == 0:
        print("✅ All PV values are positive.")
    else:
        print(f"⚠️ Found {bad_count} negative PV values. Lowest: {min_pv}")
        print("   This causes the DB 'Out of range' crash.")


if __name__ == "__main__":
    check_pv()
