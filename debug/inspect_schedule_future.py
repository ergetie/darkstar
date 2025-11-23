import json
from datetime import datetime
from pathlib import Path


def main() -> None:
    path = Path("schedule.json")
    if not path.exists():
        print("schedule.json not found in current directory.")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read schedule.json: {exc}")
        return

    slots = data.get("schedule") or []
    if not isinstance(slots, list) or not slots:
        print("No slots found in schedule.json.")
        return

    future_slots = [s for s in slots if not s.get("is_historical")]
    if not future_slots:
        print("No future (non-historical) slots found.")
        return

    charge_kwh = sum(max(float(s.get("battery_charge_kw") or 0.0), 0.0) for s in future_slots) / 4.0
    discharge_kwh = (
        sum(max(float(s.get("battery_discharge_kw") or 0.0), 0.0) for s in future_slots) / 4.0
    )

    print(f"Future slots: {len(future_slots)}")
    print(f"  Charge  ≈ {charge_kwh:.2f} kWh")
    print(f"  Discharge ≈ {discharge_kwh:.2f} kWh")

    print("\nFuture cheap slots with non-zero charge:")
    any_rows = False
    for s in future_slots:
        if not s.get("is_cheap"):
            continue
        charge_kw = float(s.get("battery_charge_kw") or 0.0)
        if charge_kw <= 0.01:
            continue
        any_rows = True
        start = s.get("start_time")
        price = s.get("import_price_sek_kwh")
        print(f"  {start}  price={price}  charge_kw={charge_kw}")

    if not any_rows:
        print("  (none)")


if __name__ == "__main__":
    main()
