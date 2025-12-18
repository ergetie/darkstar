#!/usr/bin/env python3
"""Check last slot SOC values."""
import json

with open("schedule.json") as f:
    d = json.load(f)
    slots = d.get("schedule", [])

    # Find last slot and midnight slots
    if slots:
        last = slots[-1]
        print("Last slot:")
        print(f'  start_time: {last.get("start_time")}')
        print(f'  projected_soc_percent: {last.get("projected_soc_percent")}')
        print(f'  soc_target_percent: {last.get("soc_target_percent")}')

        # Find 23:45 slot (end of day)
        for slot in reversed(slots):
            if "23:45" in str(slot.get("start_time", "")):
                print("\n23:45 slot:")
                print(f'  start_time: {slot.get("start_time")}')
                print(f'  projected_soc_percent: {slot.get("projected_soc_percent")}')
                break
