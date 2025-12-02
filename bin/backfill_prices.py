import argparse
from datetime import date, timedelta, datetime
import sys
import os
sys.path.append(os.getcwd())

import yaml
from nordpool.elspot import Prices
from learning import LearningEngine
import pytz

def load_config(path="config.yaml"):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def backfill_prices(days, config_path="config.yaml"):
    config = load_config(config_path)
    engine = LearningEngine(config_path)
    
    nordpool_config = config.get("nordpool", {})
    price_area = nordpool_config.get("price_area", "SE4")
    currency = nordpool_config.get("currency", "SEK")
    resolution_minutes = nordpool_config.get("resolution_minutes", 60)
    
    prices_client = Prices(currency)
    
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    
    print(f"Fetching prices from {start_date} to {end_date} for {price_area}...")
    
    # Nordpool library fetches by day. We iterate.
    current_date = start_date
    all_entries = []
    
    while current_date <= end_date:
        try:
            print(f"  Fetching {current_date}...")
            data = prices_client.fetch(end_date=current_date, areas=[price_area], resolution=resolution_minutes)
            if data and data.get("areas") and data["areas"].get(price_area):
                values = data["areas"][price_area].get("values", [])
                all_entries.extend(values)
        except Exception as e:
            print(f"  Failed to fetch {current_date}: {e}")
            
        current_date += timedelta(days=1)
        
    if not all_entries:
        print("No data fetched.")
        return

    # Process and Store
    # Re-use logic from inputs.py _process_nordpool_data but simplified for storage
    pricing_config = config.get("pricing", {})
    vat_percent = pricing_config.get("vat_percent", 25.0)
    grid_transfer_fee_sek = pricing_config.get("grid_transfer_fee_sek", 0.2456)
    energy_tax_sek = pricing_config.get("energy_tax_sek", 0.439)
    local_tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))

    records = []
    for entry in all_entries:
        start_time = entry["start"].astimezone(local_tz)
        end_time = entry["end"].astimezone(local_tz)
        
        spot_price_sek_kwh = entry["value"] / 1000.0
        export_price_sek_kwh = spot_price_sek_kwh
        import_price_sek_kwh = (spot_price_sek_kwh + grid_transfer_fee_sek + energy_tax_sek) * (1 + vat_percent / 100.0)
        
        records.append({
            "start_time": start_time,
            "end_time": end_time,
            "import_price_sek_kwh": import_price_sek_kwh,
            "export_price_sek_kwh": export_price_sek_kwh
        })
        
    print(f"Storing {len(records)} price slots...")
    engine.store_slot_prices(records)
    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill Nordpool prices")
    parser.add_argument("--days", type=int, default=7, help="Number of days to backfill")
    args = parser.parse_args()
    
    backfill_prices(args.days)
