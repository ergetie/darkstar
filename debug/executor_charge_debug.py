#!/usr/bin/env python3
"""Debug script to analyze executor charge current calculation."""

from datetime import datetime

import pytz

from executor.engine import ExecutorEngine

tz = pytz.timezone("Europe/Stockholm")
now = datetime.now(tz)

e = ExecutorEngine()
slot, slot_start = e._load_current_slot(now)

if slot:
    print(f"Current Slot: {slot_start}")
    print(f"  charge_kw: {slot.charge_kw}")
    print(f"  export_kw: {slot.export_kw}")
    print(f"  water_kw: {slot.water_kw}")
    print(f"  soc_target: {slot.soc_target}")
    print()

    # Calculate expected current
    voltage = 46.0
    raw = (slot.charge_kw * 1000) / voltage
    rounded = round(raw / 5) * 5
    clamped = max(10, min(190, rounded))

    print("Charge current calculation:")
    print(f"  {slot.charge_kw} kW * 1000 / {voltage}V = {raw:.1f} A")
    print(f"  Rounded to 5A step: {rounded} A")
    print(f"  Clamped to [10, 190]: {clamped} A")
else:
    print("No current slot found")
