import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz


class LearningStore:
    """
    Handles all database interactions for the Learning Engine.
    """

    def __init__(self, db_path: str, timezone: pytz.timezone):
        self.db_path = db_path
        self.timezone = timezone
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize SQLite database schema"""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # Slot observations table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_observations (
                    slot_start TEXT PRIMARY KEY,
                    slot_end TEXT NOT NULL,
                    import_kwh REAL DEFAULT 0.0,
                    export_kwh REAL DEFAULT 0.0,
                    pv_kwh REAL DEFAULT 0.0,
                    load_kwh REAL DEFAULT 0.0,
                    water_kwh REAL DEFAULT 0.0,
                    batt_charge_kwh REAL,
                    batt_discharge_kwh REAL,
                    soc_start_percent REAL,
                    soc_end_percent REAL,
                    import_price_sek_kwh REAL,
                    export_price_sek_kwh REAL,
                    executed_action TEXT,
                    quality_flags TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Slot forecasts table (base forecasts + optional corrections)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_start TEXT NOT NULL,
                    pv_forecast_kwh REAL DEFAULT 0.0,
                    load_forecast_kwh REAL DEFAULT 0.0,
                    pv_p10 REAL,
                    pv_p90 REAL,
                    load_p10 REAL,
                    load_p90 REAL,
                    temp_c REAL,
                    forecast_version TEXT NOT NULL,
                    pv_correction_kwh REAL DEFAULT 0.0,
                    load_correction_kwh REAL DEFAULT 0.0,
                    correction_source TEXT DEFAULT 'none',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(slot_start, forecast_version)
                )
            """
            )

            # Slot plans table (NEW for K6)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_start TEXT NOT NULL,
                    planned_charge_kwh REAL,
                    planned_discharge_kwh REAL,
                    planned_soc_percent REAL,
                    planned_import_kwh REAL,
                    planned_export_kwh REAL,
                    planned_cost_sek REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(slot_start)
                )
                """
            )

            # Migration: ensure correction columns exist on older databases
            for _column_name, ddl in (
                (
                    "pv_correction_kwh",
                    "ALTER TABLE slot_forecasts ADD COLUMN pv_correction_kwh REAL DEFAULT 0.0",
                ),
                (
                    "load_correction_kwh",
                    "ALTER TABLE slot_forecasts ADD COLUMN load_correction_kwh REAL DEFAULT 0.0",
                ),
                (
                    "correction_source",
                    "ALTER TABLE slot_forecasts ADD COLUMN correction_source TEXT DEFAULT 'none'",
                ),
                ("pv_p10", "ALTER TABLE slot_forecasts ADD COLUMN pv_p10 REAL"),
                ("pv_p90", "ALTER TABLE slot_forecasts ADD COLUMN pv_p90 REAL"),
                ("load_p10", "ALTER TABLE slot_forecasts ADD COLUMN load_p10 REAL"),
                ("load_p90", "ALTER TABLE slot_forecasts ADD COLUMN load_p90 REAL"),
            ):
                try:
                    cursor.execute(ddl)
                except sqlite3.OperationalError as exc:
                    # Ignore duplicate-column errors; the column already exists.
                    if "duplicate column name" not in str(exc).lower():
                        raise

            # Backfill NULLs in correction columns to safe defaults
            cursor.execute(
                """
                UPDATE slot_forecasts
                SET
                    pv_correction_kwh = COALESCE(pv_correction_kwh, 0.0),
                    load_correction_kwh = COALESCE(load_correction_kwh, 0.0),
                    correction_source = COALESCE(correction_source, 'none')
                """
            )

            # Config versions table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS config_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    yaml_blob TEXT NOT NULL,
                    reason TEXT,
                    metrics_json TEXT,
                    applied BOOLEAN DEFAULT FALSE
                )
            """
            )

            # Learning runs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    horizon_days INTEGER DEFAULT 7,
                    params_json TEXT,
                    status TEXT DEFAULT 'started',
                    result_metrics_json TEXT,
                    error_message TEXT
                )
            """
            )

            # Consolidated per-day learning outputs (one row per date/run)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_daily_metrics (
                    date TEXT PRIMARY KEY,
                    pv_error_by_hour_kwh TEXT,
                    load_error_by_hour_kwh TEXT,
                    pv_adjustment_by_hour_kwh TEXT,
                    load_adjustment_by_hour_kwh TEXT,
                    soc_error_mean_pct REAL,
                    soc_error_stddev_pct REAL,
                    pv_error_mean_abs_kwh REAL,
                    load_error_mean_abs_kwh REAL,
                    s_index_base_factor REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Drop legacy metrics tables that are no longer used
            cursor.execute("DROP TABLE IF EXISTS learning_metrics")
            cursor.execute("DROP TABLE IF EXISTS learning_daily_series")

            # Create indexes for performance
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_slot_observations_start "
                "ON slot_observations(slot_start)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_slot_forecasts_start ON slot_forecasts(slot_start)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_runs_started ON learning_runs(started_at)"
            )

            # Parameter change history (per applied change)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_param_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    param_path TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    loop TEXT,
                    reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Sensor totals table for cumulative energy readings
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_totals (
                    name TEXT PRIMARY KEY,
                    last_value REAL,
                    last_timestamp TEXT
                )
                """
            )

            # Unified training episodes table for RL agent
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS training_episodes (
                    episode_id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    inputs_json TEXT NOT NULL,
                    context_json TEXT,
                    schedule_json TEXT NOT NULL,
                    config_overrides_json TEXT
                )
                """
            )

            # Legacy tables from planner.py (moved here for consolidation)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_planned (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    planned_kwh REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_planned_date ON schedule_planned(date)"
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS realized_energy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_start TEXT NOT NULL,
                    slot_end TEXT NOT NULL,
                    action TEXT,
                    energy_kwh REAL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_water (
                    date TEXT PRIMARY KEY,
                    used_kwh REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS planner_debug (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    timestamp TEXT NOT NULL,
                    overrides_json TEXT,
                    reason TEXT
                )
                """
            )

            # Reflex state table for rate limiting parameter updates
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reflex_state (
                    param_path TEXT PRIMARY KEY,
                    last_value REAL,
                    last_updated TEXT,
                    change_count INTEGER DEFAULT 0
                )
                """
            )

            conn.commit()

    def store_slot_prices(self, price_rows: Iterable[dict[str, Any]]) -> None:
        """Store slot price data (import/export SEK per kWh)."""
        rows = list(price_rows or [])
        if not rows:
            return

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            for row in rows:
                slot_start = row.get("slot_start") or row.get("start_time")
                slot_end = row.get("slot_end") or row.get("end_time")
                if slot_start is None:
                    continue

                if isinstance(slot_start, datetime):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                if slot_end is not None:
                    if isinstance(slot_end, datetime):
                        slot_end = slot_end.astimezone(self.timezone).isoformat()
                    else:
                        slot_end = pd.to_datetime(slot_end).astimezone(self.timezone).isoformat()

                import_price = row.get("import_price_sek_kwh")
                export_price = row.get("export_price_sek_kwh")

                cursor.execute(
                    """
                    INSERT INTO slot_observations (
                        slot_start,
                        slot_end,
                        import_price_sek_kwh,
                        export_price_sek_kwh
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(slot_start) DO UPDATE SET
                        slot_end = COALESCE(excluded.slot_end, slot_observations.slot_end),
                        import_price_sek_kwh = COALESCE(
                            excluded.import_price_sek_kwh,
                            slot_observations.import_price_sek_kwh
                        ),
                        export_price_sek_kwh = COALESCE(
                            excluded.export_price_sek_kwh,
                            slot_observations.export_price_sek_kwh
                        )
                    """,
                    (
                        slot_start,
                        slot_end,
                        None if import_price is None else float(import_price),
                        None if export_price is None else float(export_price),
                    ),
                )

            conn.commit()

    def store_slot_observations(self, observations_df: pd.DataFrame) -> None:
        """Store slot observations in database"""
        if observations_df.empty:
            return

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            records = observations_df.to_dict("records")

            for record in records:
                cursor = conn.cursor()

                slot_start = record["slot_start"]
                slot_end = record.get("slot_end")
                if isinstance(slot_start, datetime):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()
                if slot_end is not None:
                    if isinstance(slot_end, datetime):
                        slot_end = slot_end.astimezone(self.timezone).isoformat()
                    else:
                        slot_end = pd.to_datetime(slot_end).astimezone(self.timezone).isoformat()

                import_kwh = float(record.get("import_kwh", 0.0) or 0.0)
                export_kwh = float(record.get("export_kwh", 0.0) or 0.0)
                pv_kwh = float(record.get("pv_kwh", 0.0) or 0.0)
                load_kwh = float(record.get("load_kwh", 0.0) or 0.0)
                water_kwh = float(record.get("water_kwh", 0.0) or 0.0)
                batt_charge = record.get("batt_charge_kwh")
                batt_discharge = record.get("batt_discharge_kwh")
                soc_start = record.get("soc_start_percent")
                soc_end = record.get("soc_end_percent")
                import_price = record.get("import_price_sek_kwh")
                export_price = record.get("export_price_sek_kwh")
                quality_flags = record.get("quality_flags", "{}")

                update_sql = """
                    UPDATE slot_observations
                    SET
                        slot_end = COALESCE(?, slot_end),
                        import_kwh = ?,
                        export_kwh = ?,
                        pv_kwh = ?,
                        load_kwh = ?,
                        water_kwh = ?,
                        batt_charge_kwh = COALESCE(?, batt_charge_kwh),
                        batt_discharge_kwh = COALESCE(?, batt_discharge_kwh),
                        soc_start_percent = COALESCE(?, soc_start_percent),
                        soc_end_percent = COALESCE(?, soc_end_percent),
                        import_price_sek_kwh = COALESCE(?, import_price_sek_kwh),
                        export_price_sek_kwh = COALESCE(?, export_price_sek_kwh),
                        quality_flags = ?
                    WHERE slot_start = ?
                """
                cursor.execute(
                    update_sql,
                    (
                        slot_end,
                        import_kwh,
                        export_kwh,
                        pv_kwh,
                        load_kwh,
                        water_kwh,
                        None if batt_charge is None else float(batt_charge),
                        None if batt_discharge is None else float(batt_discharge),
                        None if soc_start is None else float(soc_start),
                        None if soc_end is None else float(soc_end),
                        None if import_price is None else float(import_price),
                        None if export_price is None else float(export_price),
                        quality_flags,
                        slot_start,
                    ),
                )

                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        INSERT INTO slot_observations (
                            slot_start,
                            slot_end,
                            import_kwh,
                            export_kwh,
                            pv_kwh,
                            load_kwh,
                            water_kwh,
                            batt_charge_kwh,
                            batt_discharge_kwh,
                            soc_start_percent,
                            soc_end_percent,
                            import_price_sek_kwh,
                            export_price_sek_kwh,
                            quality_flags
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            slot_start,
                            slot_end,
                            import_kwh,
                            export_kwh,
                            pv_kwh,
                            load_kwh,
                            water_kwh,
                            None if batt_charge is None else float(batt_charge),
                            None if batt_discharge is None else float(batt_discharge),
                            None if soc_start is None else float(soc_start),
                            None if soc_end is None else float(soc_end),
                            None if import_price is None else float(import_price),
                            None if export_price is None else float(export_price),
                            quality_flags,
                        ),
                    )

            conn.commit()

    def store_forecasts(self, forecasts: list[dict], forecast_version: str) -> None:
        """Store forecast data"""
        if not forecasts:
            return

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            for forecast in forecasts:
                slot_start = forecast.get("slot_start")
                if slot_start is None:
                    continue

                pv_forecast = forecast.get("pv_forecast_kwh", 0.0)
                load_forecast = forecast.get("load_forecast_kwh", 0.0)
                temp_c = forecast.get("temp_c")

                pv_p10 = forecast.get("pv_p10")
                pv_p90 = forecast.get("pv_p90")
                load_p10 = forecast.get("load_p10")
                load_p90 = forecast.get("load_p90")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO slot_forecasts (
                        slot_start,
                        pv_forecast_kwh,
                        load_forecast_kwh,
                        pv_p10,
                        pv_p90,
                        load_p10,
                        load_p90,
                        temp_c,
                        forecast_version,
                        pv_correction_kwh,
                        load_correction_kwh,
                        correction_source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                                (SELECT pv_correction_kwh FROM slot_forecasts
                                 WHERE slot_start = ? AND forecast_version = ?),
                                0.0
                            ),
                            COALESCE(
                                (SELECT load_correction_kwh FROM slot_forecasts
                                 WHERE slot_start = ? AND forecast_version = ?),
                                0.0
                            ),
                            COALESCE(
                                (SELECT correction_source FROM slot_forecasts
                                 WHERE slot_start = ? AND forecast_version = ?),
                                'none'
                            )
                    )
                    """,
                    (
                        slot_start,
                        float(pv_forecast or 0.0),
                        float(load_forecast or 0.0),
                        None if pv_p10 is None else float(pv_p10),
                        None if pv_p90 is None else float(pv_p90),
                        None if load_p10 is None else float(load_p10),
                        None if load_p90 is None else float(load_p90),
                        None if temp_c is None else float(temp_c),
                        forecast_version,
                        slot_start,
                        forecast_version,
                        slot_start,
                        forecast_version,
                        slot_start,
                        forecast_version,
                    ),
                )

            conn.commit()

    def store_plan(self, plan_df: pd.DataFrame) -> None:
        """
        Store the planned schedule for later comparison with actuals.
        """
        if plan_df.empty:
            return

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # We expect the DF to have columns like:
            # slot_start, kepler_charge_kwh, kepler_discharge_kwh, kepler_soc_percent,
            # kepler_import_kwh, kepler_export_kwh, kepler_cost_sek

            # Map DF columns to DB columns
            # Note: We use 'kepler_' prefix from the planner output

            records = plan_df.to_dict("records")
            for row in records:
                slot_start = row.get("start_time") or row.get("slot_start")
                if not slot_start:
                    continue

                if isinstance(slot_start, datetime):
                    slot_start = slot_start.astimezone(self.timezone).isoformat()
                else:
                    slot_start = pd.to_datetime(slot_start).astimezone(self.timezone).isoformat()

                cursor.execute(
                    """
                    INSERT INTO slot_plans (
                        slot_start,
                        planned_charge_kwh,
                        planned_discharge_kwh,
                        planned_soc_percent,
                        planned_import_kwh,
                        planned_export_kwh,
                        planned_cost_sek
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slot_start) DO UPDATE SET
                        planned_charge_kwh = excluded.planned_charge_kwh,
                        planned_discharge_kwh = excluded.planned_discharge_kwh,
                        planned_soc_percent = excluded.planned_soc_percent,
                        planned_import_kwh = excluded.planned_import_kwh,
                        planned_export_kwh = excluded.planned_export_kwh,
                        planned_cost_sek = excluded.planned_cost_sek,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    (
                        slot_start,
                        float(row.get("kepler_charge_kwh", 0.0) or 0.0),
                        float(row.get("kepler_discharge_kwh", 0.0) or 0.0),
                        float(row.get("kepler_soc_percent", 0.0) or 0.0),
                        float(row.get("kepler_import_kwh", 0.0) or 0.0),
                        float(row.get("kepler_export_kwh", 0.0) or 0.0),
                        float(row.get("planned_cost_sek", row.get("kepler_cost_sek", 0.0)) or 0.0),
                    ),
                )
            conn.commit()

    def store_training_episode(
        self,
        episode_id: str,
        inputs_json: str,
        schedule_json: str,
        context_json: str | None = None,
        config_overrides_json: str | None = None,
    ) -> None:
        """Store a training episode for RL."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO training_episodes (
                    episode_id,
                    inputs_json,
                    schedule_json,
                    context_json,
                    config_overrides_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    episode_id,
                    inputs_json,
                    schedule_json,
                    context_json,
                    config_overrides_json,
                ),
            )
            conn.commit()

    def get_last_observation_time(self) -> datetime | None:
        """Get the timestamp of the last recorded observation."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(slot_start) FROM slot_observations")
            row = cursor.fetchone()
            if row and row[0]:
                # Parse ISO string
                dt = datetime.fromisoformat(row[0])
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=self.timezone)
                else:
                    dt = dt.astimezone(self.timezone)
                return dt
            return None

    def get_low_soc_events(
        self,
        days_back: int = 30,
        threshold_percent: float = 5.0,
        peak_hours: tuple[int, int] = (16, 20),
    ) -> list[dict[str, Any]]:
        """
        Query slot_observations for low-SoC events during peak hours.

        Args:
            days_back: How many days to look back
            threshold_percent: SoC below this is considered critical
            peak_hours: Tuple of (start_hour, end_hour) for peak demand window

        Returns:
            List of {date, slot_start, soc_end_percent} for each critical event.
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (
                (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
            )

            start_hour, end_hour = peak_hours

            query = """
                SELECT
                    DATE(slot_start) as date,
                    slot_start,
                    soc_end_percent
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
                  AND soc_end_percent IS NOT NULL
                  AND soc_end_percent < ?
                  AND CAST(strftime('%H', slot_start) AS INTEGER) >= ?
                  AND CAST(strftime('%H', slot_start) AS INTEGER) < ?
                ORDER BY slot_start DESC
            """
            cursor = conn.execute(query, (cutoff_date, threshold_percent, start_hour, end_hour))

            events = []
            for row in cursor:
                events.append(
                    {
                        "date": row[0],
                        "slot_start": row[1],
                        "soc_end_percent": row[2],
                    }
                )
            return events

    def get_reflex_state(self, param_path: str) -> dict[str, Any] | None:
        """
        Get the last update state for a parameter.

        Returns:
            Dict with {last_value, last_updated, change_count} or None if never updated.
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.execute(
                "SELECT last_value, last_updated, change_count FROM reflex_state WHERE param_path = ?",
                (param_path,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "last_value": row[0],
                    "last_updated": row[1],
                    "change_count": row[2],
                }
            return None

    def update_reflex_state(self, param_path: str, new_value: float) -> None:
        """
        Update the reflex state for a parameter after a change.
        """
        now = datetime.now(self.timezone).isoformat()
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute(
                """
                INSERT INTO reflex_state (param_path, last_value, last_updated, change_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(param_path) DO UPDATE SET
                    last_value = excluded.last_value,
                    last_updated = excluded.last_updated,
                    change_count = change_count + 1
                """,
                (param_path, new_value, now),
            )
            conn.commit()

    def get_forecast_vs_actual(
        self,
        days_back: int = 14,
        target: str = "pv",
    ) -> pd.DataFrame:
        """
        Compare forecast vs actual values for PV or load.

        Args:
            days_back: How many days to look back
            target: 'pv' or 'load'

        Returns:
            DataFrame with columns: slot_start, forecast, actual, error (forecast - actual)
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (
                (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
            )

            if target == "pv":
                forecast_col = "f.pv_forecast_kwh"
                actual_col = "o.pv_kwh"
                p10_col = "f.pv_p10"
                p90_col = "f.pv_p90"
            else:
                forecast_col = "f.load_forecast_kwh"
                actual_col = "o.load_kwh"
                p10_col = "f.load_p10"
                p90_col = "f.load_p90"

            query = f"""
                SELECT
                    o.slot_start,
                    {forecast_col} as forecast,
                    {actual_col} as actual,
                    ({forecast_col} - {actual_col}) as error,
                    {p10_col} as p10,
                    {p90_col} as p90
                FROM slot_observations o
                JOIN slot_forecasts f ON o.slot_start = f.slot_start
                WHERE DATE(o.slot_start) >= ?
                  AND {actual_col} IS NOT NULL
                  AND {forecast_col} IS NOT NULL
                ORDER BY o.slot_start ASC
            """

            df = pd.read_sql_query(query, conn, params=(cutoff_date,))
            return df

    def get_arbitrage_stats(self, days_back: int = 30) -> dict[str, Any]:
        """
        Calculate arbitrage statistics for ROI analysis.

        Args:
            days_back: How many days to look back

        Returns:
            Dict with:
                - total_export_revenue: SEK earned from exports
                - total_import_cost: SEK spent on imports (for charging)
                - total_charge_kwh: Total energy charged
                - total_discharge_kwh: Total energy discharged
                - cycles: Estimated battery cycles (charge_kwh / capacity placeholder)
                - profit_per_cycle: Revenue / cycles
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (
                (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
            )

            query = """
                SELECT
                    SUM(export_kwh * export_price_sek_kwh) as export_revenue,
                    SUM(import_kwh * import_price_sek_kwh) as import_cost,
                    SUM(batt_charge_kwh) as total_charge,
                    SUM(batt_discharge_kwh) as total_discharge
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
                  AND export_price_sek_kwh IS NOT NULL
                  AND import_price_sek_kwh IS NOT NULL
            """

            row = conn.execute(query, (cutoff_date,)).fetchone()

            export_revenue = row[0] or 0.0
            import_cost = row[1] or 0.0
            total_charge = row[2] or 0.0
            total_discharge = row[3] or 0.0

            return {
                "total_export_revenue": round(export_revenue, 2),
                "total_import_cost": round(import_cost, 2),
                "total_charge_kwh": round(total_charge, 2),
                "total_discharge_kwh": round(total_discharge, 2),
                "net_profit": round(export_revenue - import_cost, 2),
            }

    def get_capacity_estimate(self, days_back: int = 30) -> float | None:
        """
        Estimate effective battery capacity from discharge observations.

        Looks for large discharge events (SoC drop > 30%) and calculates
        the ratio of energy discharged to SoC percentage dropped.

        Args:
            days_back: How many days to look back

        Returns:
            Estimated capacity in kWh, or None if insufficient data.
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (
                (datetime.now(self.timezone) - timedelta(days=days_back)).date().isoformat()
            )

            # Look for slots with significant discharge
            query = """
                SELECT
                    soc_start_percent,
                    soc_end_percent,
                    batt_discharge_kwh
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
                  AND soc_start_percent IS NOT NULL
                  AND soc_end_percent IS NOT NULL
                  AND batt_discharge_kwh IS NOT NULL
                  AND batt_discharge_kwh > 0.1
                  AND soc_start_percent > soc_end_percent
            """

            rows = conn.execute(query, (cutoff_date,)).fetchall()

            if len(rows) < 10:
                return None

            # Calculate effective capacity from each observation
            estimates = []
            for soc_start, soc_end, discharge_kwh in rows:
                soc_drop = soc_start - soc_end
                if soc_drop > 0.5:  # At least 0.5% drop
                    # effective_capacity = discharge / (soc_drop/100)
                    estimated_cap = discharge_kwh / (soc_drop / 100.0)
                    if 10 < estimated_cap < 100:  # Sanity check
                        estimates.append(estimated_cap)

            if len(estimates) < 5:
                return None

            # Use median to be robust to outliers
            estimates.sort()
            median_idx = len(estimates) // 2
            return round(estimates[median_idx], 1)
