import json
import pandas as pd
from datetime import datetime


def diagnose():
    try:
        with open("schedule.json", "r") as f:
            data = json.load(f)

        schedule = data.get("schedule", [])
        debug = data.get("debug", {})
        meta = data.get("meta", {})

        print(f"📅 Planner Run: {meta.get('planned_at')}")

        # 1. Analyze S-Index
        print("\n🛡️  S-Index Diagnosis:")
        s_debug = debug.get("s_index")
        if s_debug:
            print(json.dumps(s_debug, indent=2))
        else:
            print("   (No S-index debug data)")

        # 2. Analyze Windows & Responsibilities (THE KEY PART)
        print("\n🪟 Planning Windows:")
        windows = debug.get("windows", {}).get("list", [])
        if not windows:
            print("   ⚠️ No windows found in debug data.")

        for i, w in enumerate(windows):
            win = w.get("window", {})
            resp = w.get("total_responsibility_kwh", 0)
            start = win.get("start", "N/A")
            end = win.get("end", "N/A")

            # Filter for relevant windows (today/tomorrow)
            if "2025-11-20" in str(start) or "2025-11-21" in str(start):
                print(f"   Window {i}: {start[11:16]} -> {end[11:16]}")
                print(f"      Responsibility: {resp:.2f} kWh")

        # 3. Charging Analysis
        print("\n🔋 Charging Analysis:")
        df = pd.DataFrame(schedule)
        if not df.empty:
            charging = df[df["battery_charge_kw"] > 0]
            if not charging.empty:
                # Filter for the main charge block tonight
                tonight = charging[charging["start_time"].str.contains("2025-11-21T")]
                if not tonight.empty:
                    last_charge = tonight.iloc[-1]
                    print(f"   Stops at: {last_charge['start_time'][11:16]}")
                    print(f"   SoC:      {last_charge['projected_soc_percent']:.1f}%")
                    print(f"   Price:    {last_charge['import_price_sek_kwh']:.2f} SEK")
                else:
                    print("   No charging found for tomorrow morning.")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    diagnose()
