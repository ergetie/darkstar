import pandas as pd
import json

with open("schedule.json", "r") as f:
    data = json.load(f)

print(f"{'Time':<20} | {'Price':<6} | {'Cheap?'}")
print("-" * 40)
for slot in data["schedule"]:
    # Just show tomorrow
    if "2025-11-21" in slot["start_time"]:
        is_cheap = (
            "YES" if slot.get("import_price_sek_kwh") < 2.2 else "NO"
        )  # adjusting guess based on previous logs
        print(f"{slot['start_time']:<20} | {slot['import_price_sek_kwh']:<6.2f} | {is_cheap}")
