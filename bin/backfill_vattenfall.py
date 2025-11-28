import sys
import yaml
import sqlite3
import requests
import json
from datetime import date, timedelta, datetime
import pytz

# Constants
VATTENFALL_API = "https://www.vattenfall.se/api/price/spot/pricearea/{start}/{end}/{area}"

def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def get_db_path(config):
    return config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")

def calculate_final_prices(spot_ore, config):
    """
    Convert Spot (öre/kWh) to Import/Export (SEK/kWh) using config taxes.
    """
    pricing = config.get("pricing", {})
    vat_percent = pricing.get("vat_percent", 25.0)
    grid_fee = pricing.get("grid_transfer_fee_sek", 0.2456)
    energy_tax = pricing.get("energy_tax_sek", 0.439)

    spot_sek = spot_ore / 100.0

    # Import: (Spot + Grid + Tax) * VAT
    import_price = (spot_sek + grid_fee + energy_tax) * (1.0 + (vat_percent / 100.0))

    # Export: Spot
    export_price = spot_sek

    return round(import_price, 4), round(export_price, 4)

def backfill_vattenfall(start_date_str, end_date_str, area="SN4"):
    config = load_config()
    db_path = get_db_path(config)
    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    print(f"--- Backfilling Vattenfall ({area}) ---")
    print(f"Window: {start_dt} to {end_dt}")

    # Process in 30-day chunks
    current_start = start_dt
    total_slots = 0

    with sqlite3.connect(db_path) as conn:
        while current_start <= end_dt:
            current_end = min(current_start + timedelta(days=30), end_dt)

            # API format YYYY-MM-DD
            s_str = current_start.isoformat()
            e_str = current_end.isoformat()

            url = VATTENFALL_API.format(start=s_str, end=e_str, area=area)
            print(f"Fetching {s_str} to {e_str}...", end="", flush=True)

            try:
                headers = {
                    "User-Agent": "DarkstarEnergyManager/1.0"
                }
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()

                rows_to_insert = []
                for item in data:
                    # Item: {"TimeStamp": "2025-08-01T00:00:00", "Value": 83.64, ...}

                    # Parse Time (Assuming Local Naive -> Localize)
                    ts_str = item.get("TimeStamp")
                    val_ore = item.get("Value")

                    if ts_str and val_ore is not None:
                        # Create naive datetime
                        dt_naive = datetime.fromisoformat(ts_str)
                        # Localize to configured timezone
                        dt_local = tz.localize(dt_naive)

                        # Calculate end time (1 hour later)
                        dt_end_local = dt_local + timedelta(hours=1)

                        # Calculate prices
                        imp, exp = calculate_final_prices(float(val_ore), config)

                        rows_to_insert.append((
                            dt_local.isoformat(),
                            dt_end_local.isoformat(),
                            imp,
                            exp
                        ))

                if rows_to_insert:
                    conn.executemany("""
                        INSERT INTO slot_observations
                        (slot_start, slot_end, import_price_sek_kwh, export_price_sek_kwh)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(slot_start) DO UPDATE SET
                        import_price_sek_kwh=excluded.import_price_sek_kwh,
                        export_price_sek_kwh=excluded.export_price_sek_kwh
                    """, rows_to_insert)
                    conn.commit()
                    count = len(rows_to_insert)
                    total_slots += count
                    print(f" OK ({count} slots)")
                else:
                    print(" No data returned.")

            except Exception as e:
                print(f" Failed: {e}")

            # Move to next chunk
            current_start = current_end + timedelta(days=1)

    print(f"Done. Backfilled {total_slots} price slots.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m bin.backfill_vattenfall YYYY-MM-DD YYYY-MM-DD [AREA]")
        exit(1)

    area_arg = sys.argv[3] if len(sys.argv) > 3 else "SN4"
    backfill_vattenfall(sys.argv[1], sys.argv[2], area_arg)
