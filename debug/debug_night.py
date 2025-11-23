import pandas as pd
from datetime import datetime, timedelta
import pytz
import sqlite3
from ml.data_activator import fetch_entity_history
from inputs import load_home_assistant_config
from learning import get_learning_engine


def debug_night():
    print("🕵️‍♂️ INVESTIGATING NIGHT DATA LOSS")

    # 1. Define "Last Night" (22:00 to 06:00)
    engine = get_learning_engine()
    tz = engine.timezone
    now = datetime.now(tz)

    # Find the previous night window
    end_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if end_time > now:
        end_time -= timedelta(days=1)
    start_time = end_time - timedelta(hours=8)  # 22:00 previous day

    print(f"📅 Inspecting window: {start_time} to {end_time}")

    # 2. Check Config
    config = load_home_assistant_config()
    # We use the consumption entity defined in secrets/config
    # Try to find the load sensor mapping
    mappings = engine.config.get("input_sensors", {})
    entity_id = mappings.get("total_load_consumption")

    if not entity_id:
        print("❌ Could not find 'total_load_consumption' in input_sensors.")
        return

    print(f"🔌 Sensor: {entity_id}")

    # 3. FETCH RAW HA DATA
    print("\n--- STEP 1: Raw Home Assistant Data ---")
    history = fetch_entity_history(entity_id, start_time, end_time)

    if not history:
        print("❌ HA returned NO data for this period.")
    else:
        print(f"✅ HA returned {len(history)} data points.")
        print("First 3:", history[:3])
        print("Last 3:", history[-3:])

        # Check if values are actually changing
        first_val = history[0][1]
        last_val = history[-1][1]
        diff = last_val - first_val
        print(f"Total consumption seen by HA in this window: {diff:.4f} kWh")

    # 4. CHECK DATABASE
    print("\n--- STEP 2: Database Content ---")
    conn = sqlite3.connect(engine.db_path)
    query = """
        SELECT slot_start, load_kwh
        FROM slot_observations
        WHERE slot_start >= ? AND slot_start < ?
        ORDER BY slot_start
    """
    df = pd.read_sql_query(query, conn, params=(start_time.isoformat(), end_time.isoformat()))
    conn.close()

    if df.empty:
        print("❌ Database has NO ROWS for this window.")
    else:
        print(f"✅ Database has {len(df)} rows.")
        print(df.head(10).to_string(index=False))

        non_zeros = df[df["load_kwh"] > 0.001]
        print(f"\nValid (>0.001) rows: {len(non_zeros)} / {len(df)}")

    # 5. DRY RUN ETL (Simulation)
    if history:
        print("\n--- STEP 3: ETL Simulation ---")
        # Mimic data_activator logic
        data_map = {"total_load_consumption": history}
        try:
            slot_df = engine.etl_cumulative_to_slots(data_map)
            # Filter for our specific night window
            # (ETL might produce slightly wider range, we just want to see if it generated valid load)
            print("ETL generated dataframe:")
            if not slot_df.empty and "load_kwh" in slot_df.columns:
                # Filter roughly to window
                mask = (slot_df["slot_start"] >= start_time) & (slot_df["slot_start"] < end_time)
                night_slots = slot_df[mask]
                print(night_slots[["slot_start", "load_kwh"]].head(10).to_string())
                print(f"\nSum of ETL load: {night_slots['load_kwh'].sum():.4f} kWh")
            else:
                print("ETL returned empty or missing load_kwh.")
        except Exception as e:
            print(f"ETL Failed: {e}")


if __name__ == "__main__":
    debug_night()
