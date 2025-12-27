import asyncio
import yaml
import pandas as pd
from datetime import datetime, timedelta
import pytz

# Import existing tools
from inputs import get_forecast_data, get_initial_state
from learning import get_learning_engine


def force_populate():
    print("🚀 Force-populating database with 7-day forecast...")

    # 1. Load Config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    # Temporarily disable 'aurora' in memory so get_forecast_data
    # is forced to fetch fresh data from Open-Meteo/HA instead of reading empty DB
    config["forecasting"]["active_forecast_version"] = "force_fetch"

    # 2. Create Dummy Price Slots for 7 days
    # This tricks inputs.py into fetching a long horizon
    print("📅 Generating 7-day timeline...")
    tz = pytz.timezone(config.get("timezone", "Europe/Stockholm"))
    now = datetime.now(tz).replace(minute=0, second=0, microsecond=0)

    price_slots = []
    for i in range(7 * 24 * 4):  # 7 days * 24 hours * 4 slots/hour
        start = now + timedelta(minutes=15 * i)
        price_slots.append({"start_time": start})

    # 3. Fetch Data (Async)
    # Run forecast logic
    forecast_result = get_forecast_data(price_slots, config)
    forecast_slots = forecast_result.get("slots", [])

    if not slots:
        print("❌ Failed to generate slots.")
        return

    print(f"✅ Generated {len(slots)} forecast slots.")

    # 4. Prepare for DB (Fix Key Mismatch)
    print("🔧 Mapping keys for database...")
    db_records = []
    for s in slots:
        record = s.copy()
        # inputs.py gives 'start_time', learning.py wants 'slot_start'
        if "start_time" in record:
            record["slot_start"] = record.pop("start_time")
            # Ensure timestamps are strings for SQLite
            if hasattr(record["slot_start"], "isoformat"):
                record["slot_start"] = record["slot_start"].isoformat()
        db_records.append(record)

    # 5. Save to Database
    engine = get_learning_engine()
    print("💾 Saving to SQLite (tag: 'aurora')...")

    # We save as 'aurora' so the planner picks it up immediately
    engine.store_forecasts(db_records, forecast_version="aurora")

    print("🎉 Done! Database now has 7 days of data.")


if __name__ == "__main__":
    force_populate()
