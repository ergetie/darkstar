import logging
import sqlite3
import pymysql
import pandas as pd
from typing import Dict, Any, Optional
from datetime import datetime
import pytz

from backend.learning.store import LearningStore

logger = logging.getLogger(__name__)


class MariaDBSync:
    """
    Synchronizes historical data from MariaDB (execution_history, plan_history)
    to the local SQLite LearningStore.
    """

    def __init__(self, store: LearningStore, secrets: Dict[str, Any]):
        self.store = store
        self.secrets = secrets
        self.db_config = secrets.get("mariadb", {})

    def _connect(self):
        return pymysql.connect(
            host=self.db_config.get("host", "127.0.0.1"),
            port=int(self.db_config.get("port", 3306)),
            user=self.db_config.get("user"),
            password=self.db_config.get("password"),
            database=self.db_config.get("database"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def sync_plans(self, days_back: int = 30) -> int:
        """Sync plan_history from MariaDB to slot_plans in SQLite."""
        if not self.db_config:
            logger.warning("No MariaDB config found, skipping plan sync")
            return 0

        logger.info(f"Syncing plans from MariaDB (last {days_back} days)...")
        count = 0

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    # Fetch plans
                    query = """
                        SELECT 
                            slot_start,
                            charge_kw,
                            export_kw,
                            soc_projected,
                            planned_load_kwh,
                            planned_pv_kwh,
                            planned_cost_sek
                        FROM plan_history
                        WHERE slot_start >= DATE_SUB(NOW(), INTERVAL %s DAY)
                        ORDER BY planned_at DESC
                    """
                    cur.execute(query, (days_back,))
                    rows = cur.fetchall()

            if not rows:
                logger.info("No plans found in MariaDB")
                return 0

            # Process and upsert into SQLite
            # We use a dict to keep only the LATEST plan for each slot (since we ordered by planned_at DESC)
            plans_by_slot = {}
            for row in rows:
                slot_start = row["slot_start"]
                if isinstance(slot_start, datetime):
                    slot_start = slot_start.isoformat()

                if slot_start in plans_by_slot:
                    continue

                # Convert kW to kWh (15 min slots = / 4)
                charge_kwh = float(row["charge_kw"] or 0.0) / 4.0
                export_kwh = float(row["export_kw"] or 0.0) / 4.0

                # Estimate discharge/import from net flow if needed, but we only have charge/export columns in plan_history?
                # plan_history has charge_kw, export_kw.
                # It doesn't seem to have discharge_kw or import_kw explicitly?
                # Let's check schema again...
                # Schema: charge_kw, export_kw, water_kw, planned_load_kwh, planned_pv_kwh, soc_target, soc_projected
                # It seems we only store charge and export?
                # If charge_kw is positive, it's charging. If 0, maybe discharging?
                # Wait, db_writer.py says:
                # battery_charge = max(stored_charge, 0.0)
                # battery_discharge = max(-stored_charge, 0.0)
                # So charge_kw in DB is NET battery flow?
                # Let's verify db_writer.py _map_row:
                # battery_charge_kw = ...
                # battery_discharge_kw = ...
                # net_battery_kw = battery_charge_kw - battery_discharge_kw
                # return (..., net_battery_kw, ...) -> mapped to charge_kw in DB?
                # Yes: "charge_kw" in DB seems to be net flow. Positive = Charge, Negative = Discharge.

                net_batt_kw = float(row["charge_kw"] or 0.0)
                charge_kwh = max(net_batt_kw, 0.0) / 4.0
                discharge_kwh = max(-net_batt_kw, 0.0) / 4.0

                # Import/Export?
                # export_kw is in DB.
                # import_kw is NOT in DB?
                # We can estimate import from balance: Load + Charge + Export - PV - Discharge = Import?
                # Import = Load + Charge + Export - PV - Discharge

                load = float(row["planned_load_kwh"] or 0.0)
                pv = float(row["planned_pv_kwh"] or 0.0)
                export_kwh = float(row["export_kw"] or 0.0) / 4.0

                # Balance check
                # Energy In = Import + PV + Discharge
                # Energy Out = Load + Charge + Export
                # Import = (Load + Charge + Export) - (PV + Discharge)

                needed = (load + charge_kwh + export_kwh) - (pv + discharge_kwh)
                import_kwh = max(needed, 0.0)

                plans_by_slot[slot_start] = {
                    "slot_start": slot_start,
                    "planned_charge_kwh": charge_kwh,
                    "planned_discharge_kwh": discharge_kwh,
                    "planned_soc_percent": float(row["soc_projected"] or 0.0),
                    "planned_import_kwh": import_kwh,
                    "planned_export_kwh": export_kwh,
                    "planned_cost_sek": float(row.get("planned_cost_sek", 0.0) or 0.0),
                }

            # Bulk Insert
            with sqlite3.connect(self.store.db_path) as conn:
                cursor = conn.cursor()
                for p in plans_by_slot.values():
                    # Normalize timestamp
                    slot_start = p["slot_start"]
                    if isinstance(slot_start, str):
                        slot_start = datetime.fromisoformat(slot_start)

                    if slot_start.tzinfo is None:
                        slot_start = self.store.timezone.localize(slot_start)

                    slot_start_iso = slot_start.isoformat()

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO slot_plans (
                            slot_start, planned_charge_kwh, planned_discharge_kwh,
                            planned_soc_percent, planned_import_kwh, planned_export_kwh,
                            planned_cost_sek
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            slot_start_iso,
                            p["planned_charge_kwh"],
                            p["planned_discharge_kwh"],
                            p["planned_soc_percent"],
                            p["planned_import_kwh"],
                            p["planned_export_kwh"],
                            p["planned_cost_sek"],
                        ),
                    )
                    count += 1

            logger.info(f"Synced {count} plans from MariaDB plan_history")
            return count

        except Exception as e:
            logger.error(f"MariaDB Plan Sync failed: {e}")
            return 0

    def sync_plans_from_execution(self, days_back: int = 30) -> int:
        """
        Sync historical plans from execution_history (which has prices!).
        This gives us the 'Planned Cost' for past slots.
        """
        if not self.db_config:
            return 0

        logger.info(f"Syncing historical plans from execution_history (last {days_back} days)...")
        count = 0

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT 
                            slot_start,
                            planned_charge_kw,
                            planned_export_kw,
                            planned_soc_projected,
                            planned_load_kwh,
                            planned_pv_kwh,
                            import_price,
                            export_price
                        FROM execution_history
                        WHERE slot_start >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    """
                    cur.execute(query, (days_back,))
                    rows = cur.fetchall()

            if not rows:
                return 0

            with sqlite3.connect(self.store.db_path) as conn:
                cursor = conn.cursor()
                for row in rows:
                    slot_start = row["slot_start"]
                    # Normalize to timezone-aware ISO string to match slot_observations
                    if isinstance(slot_start, str):
                        slot_start = datetime.fromisoformat(slot_start)

                    if slot_start.tzinfo is None:
                        slot_start = self.store.timezone.localize(slot_start)

                    slot_start_iso = slot_start.isoformat()

                    # kW -> kWh
                    net_batt_kw = float(row["planned_charge_kw"] or 0.0)
                    charge_kwh = max(net_batt_kw, 0.0) / 4.0
                    discharge_kwh = max(-net_batt_kw, 0.0) / 4.0

                    export_kwh = float(row["planned_export_kw"] or 0.0) / 4.0
                    load_kwh = float(row["planned_load_kwh"] or 0.0)
                    pv_kwh = float(row["planned_pv_kwh"] or 0.0)

                    # Calculate Import
                    # Import = (Load + Charge + Export) - (PV + Discharge)
                    needed = (load_kwh + charge_kwh + export_kwh) - (pv_kwh + discharge_kwh)
                    import_kwh = max(needed, 0.0)

                    # Calculate Cost
                    import_price = float(row["import_price"] or 0.0)
                    export_price = float(row["export_price"] or 0.0)

                    cost_sek = (import_kwh * import_price) - (export_kwh * export_price)

                    # Upsert into slot_plans
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO slot_plans (
                            slot_start, planned_charge_kwh, planned_discharge_kwh,
                            planned_soc_percent, planned_import_kwh, planned_export_kwh,
                            planned_cost_sek
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            slot_start_iso,
                            charge_kwh,
                            discharge_kwh,
                            float(row["planned_soc_projected"] or 0.0),
                            import_kwh,
                            export_kwh,
                            cost_sek,
                        ),
                    )
                    count += 1

            logger.info(f"Synced {count} historical plans from execution_history")
            return count

        except Exception as e:
            logger.error(f"MariaDB Execution Plan Sync failed: {e}")
            return 0

    def sync_observations(self, days_back: int = 30) -> int:
        """Sync execution_history from MariaDB to slot_observations in SQLite."""
        if not self.db_config:
            return 0

        logger.info(f"Syncing observations from MariaDB (last {days_back} days)...")
        count = 0

        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT 
                            slot_start,
                            actual_soc,
                            actual_load_kwh,
                            actual_pv_kwh,
                            grid_import_kwh,
                            grid_export_kwh,
                            battery_charge_kwh,
                            battery_discharge_kwh,
                            import_price,
                            export_price
                        FROM execution_history
                        WHERE slot_start >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    """
                    cur.execute(query, (days_back,))
                    rows = cur.fetchall()

            if not rows:
                return 0

            with sqlite3.connect(self.store.db_path) as conn:
                cursor = conn.cursor()
                for row in rows:
                    slot_start = row["slot_start"]
                    if isinstance(slot_start, str):
                        slot_start = datetime.fromisoformat(slot_start)

                    if slot_start.tzinfo is None:
                        slot_start = self.store.timezone.localize(slot_start)

                    slot_start_iso = slot_start.isoformat()

                    # Calculate slot_end (start + 15m)
                    slot_end = (slot_start + pd.Timedelta(minutes=15)).isoformat()

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO slot_observations (
                            slot_start, slot_end,
                            import_kwh, export_kwh, pv_kwh, load_kwh,
                            batt_charge_kwh, batt_discharge_kwh,
                            soc_end_percent,
                            import_price_sek_kwh, export_price_sek_kwh,
                            quality_flags
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            slot_start_iso,
                            slot_end,
                            float(row["grid_import_kwh"] or 0.0),
                            float(row["grid_export_kwh"] or 0.0),
                            float(row["actual_pv_kwh"] or 0.0),
                            float(row["actual_load_kwh"] or 0.0),
                            float(row["battery_charge_kwh"] or 0.0),
                            float(row["battery_discharge_kwh"] or 0.0),
                            float(row["actual_soc"] or 0.0),
                            float(row["import_price"] or 0.0),
                            float(row["export_price"] or 0.0),
                            "mariadb_sync",
                        ),
                    )
                    count += 1

            logger.info(f"Synced {count} observations from MariaDB")
            return count

        except Exception as e:
            logger.error(f"MariaDB Observation Sync failed: {e}")
            return 0
