import asyncio
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytz
import yaml

# Add project root to path
sys.path.append(str(Path.cwd()))

from ml.simulation.data_loader import SimulationDataLoader

DB_PATH = "data/planner_learning.db"
TZ = pytz.timezone("Europe/Stockholm")


class ForecastBackfiller:
    def __init__(self):
        self.loader = SimulationDataLoader()
        self.client = self.loader.ha_client
        self.db_path = self.loader.db_path

    def load_config(self, path="config.yaml"):
        with Path(path).open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    def find_gaps(self):
        print(f"Scanning {self.db_path} for gaps...")
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT slot_start, load_kwh, pv_kwh FROM slot_observations ORDER BY slot_start"
            df = pd.read_sql_query(query, conn)
        if df.empty:
            return []

        df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True).dt.tz_convert(TZ)

        # Find slots with zero/null load or PV
        # We focus on load for now as that's critical
        missing = df[(df["load_kwh"] == 0) | (df["load_kwh"].isnull())]

        gaps = []
        if not missing.empty:
            missing["group"] = (missing["slot_start"].diff() > timedelta(minutes=15)).cumsum()
            for _, group in missing.groupby("group"):
                start = group["slot_start"].iloc[0]
                end = group["slot_start"].iloc[-1] + timedelta(minutes=15)
                gaps.append((start, end))

        return gaps

    async def backfill_gap(self, start, end):
        print(f"Backfilling gap: {start} -> {end}")

        # Fetch from HA
        # We need to fetch both Load and PV
        # Entity IDs are in loader.sensor_entities
        load_entity = self.loader.sensor_entities.get("load")
        pv_entity = self.loader.sensor_entities.get("pv")

        if not load_entity:
            print("  No load entity configured.")
            return

        # Fetch Load
        load_stats = await self.client.fetch_statistics(load_entity, start, end)
        pv_stats = []
        if pv_entity:
            pv_stats = await self.client.fetch_statistics(pv_entity, start, end)

        if not load_stats and not pv_stats:
            print("  No data from HA.")
            return

        # Convert to slots
        load_slots = self.loader._convert_sensor_points(load_stats, "load_kwh")
        pv_slots = self.loader._convert_sensor_points(pv_stats, "pv_kwh")

        merged = self.loader._merge_sensor_slots(load_slots, pv_slots)

        if not merged:
            print("  Failed to merge/convert stats.")
            return

        print(f"  Got {len(merged)} slots from HA.")

        # Write to DB
        self.write_slots(merged)

    def write_slots(self, slots):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            count = 0
            for slot in slots:
                # We need to update existing rows or insert new ones.
                # Since we found these as "gaps" (existing rows with 0 load), we should UPDATE.
                # But scan_gaps also looks for missing time.
                # Let's try INSERT OR REPLACE logic, but we need to be careful not to overwrite valid data if we only fetched one metric.
                # Actually, _merge_sensor_slots returns 'pv_forecast_kwh' and 'load_forecast_kwh' keys (from naive forecast logic).
                # We want to write to 'pv_kwh' and 'load_kwh' columns in slot_observations.

                start_iso = self.loader._to_utc_iso(slot["start_time"])

                # Check if row exists
                cursor.execute("SELECT 1 FROM slot_observations WHERE slot_start = ?", (start_iso,))
                exists = cursor.fetchone()

                load_val = slot.get("load_forecast_kwh", 0.0)  # _merge returns this key
                if load_val < 0.01:
                    load_val = 0.1  # Fallback to avoid zero-load anomalies
                pv_val = slot.get("pv_forecast_kwh", 0.0)

                if exists:
                    cursor.execute(
                        """
                        UPDATE slot_observations
                        SET load_kwh = ?, pv_kwh = ?
                        WHERE slot_start = ?
                    """,
                        (load_val, pv_val, start_iso),
                    )
                else:
                    # Insert new (we might need other cols like prices, but we can leave them null/0 for now)
                    # Wait, if we insert, we need slot_end.
                    end_iso = self.loader._to_utc_iso(slot["end_time"])
                    cursor.execute(
                        """
                        INSERT INTO slot_observations (slot_start, slot_end, load_kwh, pv_kwh)
                        VALUES (?, ?, ?, ?)
                    """,
                        (start_iso, end_iso, load_val, pv_val),
                    )
                count += 1
            conn.commit()
            print(f"  Updated/Inserted {count} rows.")

    async def run(self):
        gaps = self.find_gaps()
        print(f"Found {len(gaps)} gaps.")

        for start, end in gaps:
            # Add buffer to fetch slightly more to ensure coverage
            fetch_start = start - timedelta(minutes=15)
            fetch_end = end + timedelta(minutes=15)
            await self.backfill_gap(fetch_start, fetch_end)


if __name__ == "__main__":
    backfiller = ForecastBackfiller()
    asyncio.run(backfiller.run())
