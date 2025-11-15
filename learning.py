"""
Learning Engine for Darkstar Energy Manager
Phase 9a: Schema + ETL + status endpoint
"""

import copy
import errno
import json
import os
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import pytz
import yaml


class LearningEngine:
    """Learning engine for auto-tuning and forecast calibration"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.learning_config = self.config.get("learning", {})
        self.db_path = self.learning_config.get("sqlite_path", "data/planner_learning.db")
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))
        raw_map = self.learning_config.get("sensor_map", {}) or {}
        self.sensor_map = {str(v).lower(): str(k).lower() for k, v in raw_map.items()}

        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database schema
        self._init_schema()

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Fallback to default config
            with open("config.default.yaml", "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

    def _init_schema(self) -> None:
        """Initialize SQLite database schema"""
        with sqlite3.connect(self.db_path) as conn:
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

            # Slot forecasts table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_forecasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_start TEXT NOT NULL,
                    pv_forecast_kwh REAL DEFAULT 0.0,
                    load_forecast_kwh REAL DEFAULT 0.0,
                    temp_c REAL,
                    forecast_version TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(slot_start, forecast_version)
                )
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
                (
                    "CREATE INDEX IF NOT EXISTS idx_slot_observations_start "
                    "ON slot_observations(slot_start)"
                )
            )
            cursor.execute(
                (
                    "CREATE INDEX IF NOT EXISTS idx_slot_forecasts_start "
                    "ON slot_forecasts(slot_start)"
                )
            )
            cursor.execute(
                (
                    "CREATE INDEX IF NOT EXISTS idx_learning_runs_started "
                    "ON learning_runs(started_at)"
                )
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

            conn.commit()

    def store_slot_prices(self, price_rows: Iterable[Dict[str, Any]]) -> None:
        """Store slot price data (import/export SEK per kWh)."""
        rows = list(price_rows or [])
        if not rows:
            return

        with sqlite3.connect(self.db_path) as conn:
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
                            slot_observations.import_price_sek_kwh,
                        ),
                        export_price_sek_kwh = COALESCE(
                            excluded.export_price_sek_kwh,
                            slot_observations.export_price_sek_kwh,
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

    def _canonical_sensor_name(self, name: str) -> str:
        """Map incoming sensor names to canonical identifiers."""
        key = str(name).lower()
        if key in self.sensor_map:
            return self.sensor_map[key]

        stripped = key.replace("sensor.", "")
        for token in ("energy", "power", "total", "_cumulative", "_kw", "_kwh"):
            stripped = stripped.replace(token, "")
        stripped = stripped.strip("_")

        aliases = {
            "import": {"grid_import", "gridin", "import", "grid"},
            "export": {"grid_export", "gridout", "export"},
            "pv": {"pv", "solar", "pvproduction"},
            "load": {"load", "consumption", "house", "usage"},
            "water": {"water", "vvb", "waterheater"},
            "soc": {"soc", "battery_soc", "socpercent"},
        }
        for canonical, names in aliases.items():
            if stripped in names:
                return canonical
        return stripped or key

    def etl_cumulative_to_slots(
        self,
        cumulative_data: Dict[str, List[Tuple[datetime, float]]],
        resolution_minutes: int = 15,
    ) -> pd.DataFrame:
        """
        Convert cumulative sensor data to 15-minute slot deltas

        Args:
            cumulative_data: Dict mapping sensor names to list of (timestamp, cumulative_value)
            resolution_minutes: Slot resolution in minutes (default 15)

        Returns:
            DataFrame with slot-level observations
        """
        slot_records: Dict[str, pd.DataFrame] = {}
        for sensor_name, data in cumulative_data.items():
            if data:
                df = pd.DataFrame(data, columns=["timestamp", "cumulative_value"])
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                # Handle both naive and timezone-aware timestamps
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize(self.timezone)
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(self.timezone)
                df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
                slot_records[sensor_name] = df

        if not slot_records:
            return pd.DataFrame()

        # Create time slots
        all_timestamps = []
        for df in slot_records.values():
            all_timestamps.extend(df["timestamp"].tolist())

        if not all_timestamps:
            return pd.DataFrame()

        start_time = min(all_timestamps)
        end_time = max(all_timestamps)

        # Generate regular slots
        slots = pd.date_range(
            start=start_time, end=end_time, freq=f"{resolution_minutes}min", tz=self.timezone
        )

        slot_df = pd.DataFrame({"slot_start": slots[:-1], "slot_end": slots[1:]})
        quality_flags: List[defaultdict[str, List[str]]] = [
            defaultdict(list) for _ in range(len(slot_df))
        ]

        for sensor_name, df in slot_records.items():
            canonical = self._canonical_sensor_name(sensor_name)
            base_series = df.set_index("timestamp")["cumulative_value"]
            reindexed = base_series.reindex(slots)
            gaps = reindexed.isna()
            reindexed = reindexed.ffill()

            raw_diff = reindexed.diff().fillna(0)
            deltas = raw_diff.clip(lower=0)

            # Track resets (negative raw deltas before clipping)
            reset_mask = raw_diff < 0
            if reset_mask.any():
                for idx, is_reset in enumerate(reset_mask.iloc[1:]):
                    if is_reset and idx < len(quality_flags):
                        quality_flags[idx]["resets"].append(canonical)

            # Track forward-fill gaps (where value regenerated due to missing sample)
            if gaps.any():
                for idx, has_gap in enumerate(gaps.iloc[:-1]):
                    if bool(has_gap) and idx < len(quality_flags):
                        quality_flags[idx]["gaps"].append(canonical)

            slot_df[f"{canonical}_kwh"] = deltas.iloc[1:].values

        # Derive SoC from canonical 'soc'
        if any(self._canonical_sensor_name(name) == "soc" for name in slot_records):
            soc_name = next(
                name for name in slot_records if self._canonical_sensor_name(name) == "soc"
            )
            soc_series = (
                slot_records[soc_name]
                .set_index("timestamp")["cumulative_value"]
                .reindex(slots)
                .ffill()
            )
            slot_df["soc_start_percent"] = soc_series.iloc[:-1].values
            slot_df["soc_end_percent"] = soc_series.iloc[1:].values

        slot_df["duration_minutes"] = resolution_minutes
        slot_df["quality_flags"] = [
            json.dumps({k: sorted(set(v)) for k, v in entry.items()}) if entry else "{}"
            for entry in quality_flags
        ]

        return slot_df

    def store_slot_observations(self, observations_df: pd.DataFrame) -> None:
        """Store slot observations in database"""
        if observations_df.empty:
            return

        with sqlite3.connect(self.db_path) as conn:
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

                # Use a portable update-then-insert pattern instead of
                # SQLite's ON CONFLICT upsert clause to avoid syntax
                # issues across different SQLite versions/builds.
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

    def store_forecasts(self, forecasts: List[Dict], forecast_version: str) -> None:
        """Store forecast data"""
        if not forecasts:
            return

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            for forecast in forecasts:
                slot_start = forecast.get("slot_start")
                if slot_start is None:
                    continue

                pv_forecast = forecast.get("pv_forecast_kwh", 0.0)
                load_forecast = forecast.get("load_forecast_kwh", 0.0)
                temp_c = forecast.get("temp_c")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO slot_forecasts (
                        slot_start, pv_forecast_kwh, load_forecast_kwh, temp_c, forecast_version
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        slot_start,
                        float(pv_forecast or 0.0),
                        float(load_forecast or 0.0),
                        None if temp_c is None else float(temp_c),
                        forecast_version,
                    ),
                )

            conn.commit()

    def calculate_metrics(self, days_back: int = 7) -> Dict[str, Any]:
        """Calculate learning metrics for the last N days"""
        with sqlite3.connect(self.db_path) as conn:
            cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date()

            metrics = {}

            # PV forecast accuracy
            pv_query = """
                SELECT
                    AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)) as mae_pv,
                    COUNT(*) as sample_count
                FROM slot_observations o
                JOIN slot_forecasts f ON o.slot_start = f.slot_start
                WHERE DATE(o.slot_start) >= ?
                  AND o.pv_kwh IS NOT NULL AND f.pv_forecast_kwh IS NOT NULL
            """
            pv_result = conn.execute(pv_query, (cutoff_date.isoformat(),)).fetchone()
            if pv_result and pv_result[1] > 0:
                metrics["mae_pv"] = round(pv_result[0], 4)
                metrics["pv_sample_count"] = pv_result[1]

            # Load forecast accuracy
            load_query = """
                SELECT
                    AVG(ABS(o.load_kwh - f.load_forecast_kwh)) as mae_load,
                    COUNT(*) as sample_count
                FROM slot_observations o
                JOIN slot_forecasts f ON o.slot_start = f.slot_start
                WHERE DATE(o.slot_start) >= ?
                  AND o.load_kwh IS NOT NULL AND f.load_forecast_kwh IS NOT NULL
            """
            load_result = conn.execute(load_query, (cutoff_date.isoformat(),)).fetchone()
            if load_result and load_result[1] > 0:
                metrics["mae_load"] = round(load_result[0], 4)
                metrics["load_sample_count"] = load_result[1]

            # Total observations
            obs_query = """
                SELECT COUNT(*) as total_slots,
                       SUM(import_kwh) as total_import,
                       SUM(export_kwh) as total_export,
                       SUM(pv_kwh) as total_pv,
                       SUM(load_kwh) as total_load
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
            """
            obs_result = conn.execute(obs_query, (cutoff_date.isoformat(),)).fetchone()
            if obs_result:
                metrics["total_slots"] = obs_result[0] or 0
                metrics["total_import_kwh"] = round(obs_result[1] or 0, 2)
                metrics["total_export_kwh"] = round(obs_result[2] or 0, 2)
                metrics["total_pv_kwh"] = round(obs_result[3] or 0, 2)
                metrics["total_load_kwh"] = round(obs_result[4] or 0, 2)

            # Data coverage and quality diagnostics
            days_result = conn.execute(
                (
                    "SELECT COUNT(DISTINCT DATE(slot_start)) "
                    "FROM slot_observations "
                    "WHERE DATE(slot_start) >= ?"
                ),
                (cutoff_date.isoformat(),),
            ).fetchone()
            metrics["days_with_data"] = int(days_result[0]) if days_result else 0

            price_cov = conn.execute(
                """
                SELECT COUNT(*) as total_slots,
                       SUM(
                           CASE
                               WHEN import_price_sek_kwh IS NOT NULL THEN 1
                               ELSE 0
                           END
                       ) as priced_slots
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
                """,
                (cutoff_date.isoformat(),),
            ).fetchone()
            if price_cov and price_cov[0]:
                metrics["price_coverage_ratio"] = round((price_cov[1] or 0) / price_cov[0], 4)

            quality_reset_events = 0
            quality_gap_events = 0
            flags_query = """
                SELECT quality_flags
                FROM slot_observations
                WHERE DATE(slot_start) >= ?
                AND quality_flags IS NOT NULL
                AND quality_flags != '{}'
            """
            for (flags_json,) in conn.execute(flags_query, (cutoff_date.isoformat(),)):
                try:
                    parsed = json.loads(flags_json)
                    quality_reset_events += len(parsed.get("resets", []))
                    quality_gap_events += len(parsed.get("gaps", []))
                except (json.JSONDecodeError, TypeError):
                    continue
            metrics["quality_reset_events"] = quality_reset_events
            metrics["quality_gap_events"] = quality_gap_events

            last_slot = conn.execute("SELECT MAX(slot_start) FROM slot_observations").fetchone()
            if last_slot and last_slot[0]:
                metrics["last_observation"] = last_slot[0]

            try:
                metrics["db_size_bytes"] = os.path.getsize(self.db_path)
            except OSError:
                metrics["db_size_bytes"] = None

            # Learning runs status
            runs_query = """
                SELECT COUNT(*) as total_runs,
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
                       MAX(started_at) as last_run
                FROM learning_runs
                WHERE DATE(started_at) >= ?
            """
            runs_result = conn.execute(runs_query, (cutoff_date.isoformat(),)).fetchone()
            if runs_result:
                metrics["total_learning_runs"] = runs_result[0] or 0
                metrics["completed_learning_runs"] = runs_result[1] or 0
                metrics["failed_learning_runs"] = runs_result[2] or 0
                metrics["last_learning_run"] = runs_result[3]

            return metrics

    def compute_hourly_forecast_errors(self, days_back: int = 7) -> Optional[dict]:
        """
        Compute average PV and load forecast error per hour of day over the last N days.

        Returns a dict with two 24-element lists (one per hour, 0–23) for PV and load
        errors in kWh (actual - forecast).
        """
        cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date()
        sql = """
            SELECT o.slot_start,
                   o.pv_kwh,
                   o.load_kwh,
                   f.pv_forecast_kwh,
                   f.load_forecast_kwh
            FROM slot_observations o
            JOIN slot_forecasts f ON o.slot_start = f.slot_start
            WHERE DATE(o.slot_start) >= ?
              AND o.pv_kwh IS NOT NULL
              AND o.load_kwh IS NOT NULL
              AND f.pv_forecast_kwh IS NOT NULL
              AND f.load_forecast_kwh IS NOT NULL
        """
        records: list[tuple] = []
        with sqlite3.connect(self.db_path) as conn:
            for row in conn.execute(sql, (cutoff_date.isoformat(),)):
                records.append(row)

        if not records:
            return None

        pv_errors_by_hour = [[] for _ in range(24)]
        load_errors_by_hour = [[] for _ in range(24)]

        for slot_start, pv_kwh, load_kwh, pv_forecast, load_forecast in records:
            try:
                ts = pd.Timestamp(slot_start)
                if ts.tzinfo is None:
                    ts = ts.tz_localize(self.timezone)
                else:
                    ts = ts.tz_convert(self.timezone)
                hour = ts.hour
            except Exception:
                continue

            try:
                pv_err = float(pv_kwh or 0.0) - float(pv_forecast or 0.0)
                load_err = float(load_kwh or 0.0) - float(load_forecast or 0.0)
            except (TypeError, ValueError):
                continue

            pv_errors_by_hour[hour].append(pv_err)
            load_errors_by_hour[hour].append(load_err)

        def _avg(values: list[float]) -> float:
            if not values:
                return 0.0
            return sum(values) / float(len(values))

        pv_series = [round(_avg(vals), 4) for vals in pv_errors_by_hour]
        load_series = [round(_avg(vals), 4) for vals in load_errors_by_hour]

        return {
            "pv_error_by_hour_kwh": pv_series,
            "load_error_by_hour_kwh": load_series,
        }

    def store_hourly_forecast_errors(self, days_back: int = 7) -> None:
        """
        Compute and persist hourly forecast error arrays into learning_daily_series.

        Uses today's date as the key and overwrites any existing series for that date.
        """
        series = self.compute_hourly_forecast_errors(days_back=days_back)
        if not series:
            return

        today = datetime.now(self.timezone).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Persist raw error series
            for metric, values in series.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO learning_daily_series (date, metric, values_json)
                    VALUES (?, ?, ?)
                    """,
                    (today, metric, json.dumps(values)),
                )

        # Derive simple adjustment arrays (negated errors) for potential use
        # in forecast biasing: if actual > forecast, adjustment is positive.
        pv_errors = series.get("pv_error_by_hour_kwh") or [0.0] * 24
        load_errors = series.get("load_error_by_hour_kwh") or [0.0] * 24
        pv_adjust = [round(-(v or 0.0), 4) for v in pv_errors]
        load_adjust = [round(-(v or 0.0), 4) for v in load_errors]

        def _mean_abs(values: list[float]) -> float:
            vals = [abs(v or 0.0) for v in values]
            return sum(vals) / float(len(vals)) if vals else 0.0

        pv_mae_daily = _mean_abs(pv_errors)
        load_mae_daily = _mean_abs(load_errors)

        # Mirror arrays and daily aggregates into the consolidated
        # learning_daily_metrics table so there is exactly one row per
        # date with the key scalars and arrays.
        self.upsert_daily_metrics(
            datetime.now(self.timezone).date(),
            {
                "pv_error_by_hour_kwh": pv_errors,
                "load_error_by_hour_kwh": load_errors,
                "pv_adjustment_by_hour_kwh": pv_adjust,
                "load_adjustment_by_hour_kwh": load_adjust,
                "pv_error_mean_abs_kwh": pv_mae_daily,
                "load_error_mean_abs_kwh": load_mae_daily,
            },
        )

    def get_status(self) -> Dict[str, Any]:
        """Get learning engine status and metrics"""
        if not self.learning_config.get("enable", False):
            return {"enabled": False, "message": "Learning engine is disabled"}

        try:
            # Calculate metrics
            metrics = self.calculate_metrics()

            # Get configuration
            status = {
                "enabled": True,
                "sqlite_path": self.db_path,
                "sync_interval_minutes": self.learning_config.get("sync_interval_minutes", 5),
                "metrics": metrics,
                "last_updated": datetime.now(self.timezone).isoformat(),
            }

            return status

        except Exception as e:
            return {
                "enabled": True,
                "error": str(e),
                "last_updated": datetime.now(self.timezone).isoformat(),
            }

    def upsert_daily_metrics(self, date: datetime.date, payload: Dict[str, Any]) -> None:
        """
        Upsert a single consolidated daily metrics row for the given date.

        This is the new, one-row-per-day surface for learning outputs that the
        planner can consume. Arrays are stored as JSON strings; scalars as
        numeric columns. Only fields present in `payload` are updated, so this
        can be called multiple times for the same date without clobbering
        previously written values.
        """
        date_key = date.isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Ensure row exists
            cursor.execute(
                "INSERT OR IGNORE INTO learning_daily_metrics (date) VALUES (?)", (date_key,)
            )

            # Build dynamic UPDATE for provided fields only
            sets = []
            values = []

            if "pv_error_by_hour_kwh" in payload:
                sets.append("pv_error_by_hour_kwh = ?")
                values.append(
                    json.dumps(payload["pv_error_by_hour_kwh"])
                    if payload["pv_error_by_hour_kwh"] is not None
                    else None
                )
            if "load_error_by_hour_kwh" in payload:
                sets.append("load_error_by_hour_kwh = ?")
                values.append(
                    json.dumps(payload["load_error_by_hour_kwh"])
                    if payload["load_error_by_hour_kwh"] is not None
                    else None
                )
            if "pv_adjustment_by_hour_kwh" in payload:
                sets.append("pv_adjustment_by_hour_kwh = ?")
                values.append(
                    json.dumps(payload["pv_adjustment_by_hour_kwh"])
                    if payload["pv_adjustment_by_hour_kwh"] is not None
                    else None
                )
            if "load_adjustment_by_hour_kwh" in payload:
                sets.append("load_adjustment_by_hour_kwh = ?")
                values.append(
                    json.dumps(payload["load_adjustment_by_hour_kwh"])
                    if payload["load_adjustment_by_hour_kwh"] is not None
                    else None
                )
            if "soc_error_mean_pct" in payload:
                sets.append("soc_error_mean_pct = ?")
                val = payload["soc_error_mean_pct"]
                values.append(None if val is None else float(val))
            if "soc_error_stddev_pct" in payload:
                sets.append("soc_error_stddev_pct = ?")
                val = payload["soc_error_stddev_pct"]
                values.append(None if val is None else float(val))
            if "pv_error_mean_abs_kwh" in payload:
                sets.append("pv_error_mean_abs_kwh = ?")
                val = payload["pv_error_mean_abs_kwh"]
                values.append(None if val is None else float(val))
            if "load_error_mean_abs_kwh" in payload:
                sets.append("load_error_mean_abs_kwh = ?")
                val = payload["load_error_mean_abs_kwh"]
                values.append(None if val is None else float(val))
            if "s_index_base_factor" in payload:
                sets.append("s_index_base_factor = ?")
                val = payload["s_index_base_factor"]
                values.append(None if val is None else float(val))

            if sets:
                sql = f"UPDATE learning_daily_metrics SET {', '.join(sets)} WHERE date = ?"
                values.append(date_key)
                cursor.execute(sql, tuple(values))

            conn.commit()

    def get_latest_daily_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Fetch the most recent consolidated daily metrics row.

        Returns a dict with parsed arrays for PV/load error/adjustment and
        scalar fields (MAE, S-index, SoC error) where available.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date,
                       pv_error_by_hour_kwh,
                       load_error_by_hour_kwh,
                       pv_adjustment_by_hour_kwh,
                       load_adjustment_by_hour_kwh,
                       soc_error_mean_pct,
                       soc_error_stddev_pct,
                       pv_error_mean_abs_kwh,
                       load_error_mean_abs_kwh,
                       s_index_base_factor
                FROM learning_daily_metrics
                ORDER BY date DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()

        if not row:
            return None

        (
            date_str,
            pv_err_json,
            load_err_json,
            pv_adj_json,
            load_adj_json,
            soc_mean,
            soc_std,
            pv_mae,
            load_mae,
            s_index_base,
        ) = row

        def _parse_series(raw: Optional[str]) -> Optional[list[float]]:
            if raw is None:
                return None
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    return [float(v) for v in data]
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
            return None

        return {
            "date": date_str,
            "pv_error_by_hour_kwh": _parse_series(pv_err_json),
            "load_error_by_hour_kwh": _parse_series(load_err_json),
            "pv_adjustment_by_hour_kwh": _parse_series(pv_adj_json),
            "load_adjustment_by_hour_kwh": _parse_series(load_adj_json),
            "soc_error_mean_pct": soc_mean,
            "soc_error_stddev_pct": soc_std,
            "pv_error_mean_abs_kwh": pv_mae,
            "load_error_mean_abs_kwh": load_mae,
            "s_index_base_factor": s_index_base,
        }

# Global instance for webapp
_learning_engine = None


def get_learning_engine() -> LearningEngine:
    """Get or create learning engine instance"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine


class DeterministicSimulator:
    """Deterministic simulator that replays historical days through the planner."""

    def __init__(self, learning_engine: LearningEngine):
        self.engine = learning_engine
        self.config = learning_engine.config
        system_battery = self.config.get("system", {}).get("battery", {})
        fallback_battery = self.config.get("battery", {})
        self.capacity_kwh = (
            system_battery.get("capacity_kwh") or fallback_battery.get("capacity_kwh") or 10.0
        )
        self.min_soc_percent = (
            system_battery.get("min_soc_percent") or fallback_battery.get("min_soc_percent") or 15.0
        )
        self.cycle_cost = self.config.get("battery_economics", {}).get(
            "battery_cycle_cost_kwh", 0.20
        )

    def simulate_with_params(
        self,
        start_date: datetime,
        end_date: datetime,
        param_changes: Dict[str, Any],
    ) -> Dict[str, float]:
        """Re-run the planner for each day with modified parameters and evaluate objective."""
        modified_config = copy.deepcopy(self.config)
        for key_path, value in param_changes.items():
            current = modified_config
            keys = key_path.split(".")
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = value

        fd, temp_path = tempfile.mkstemp(prefix="learning_cfg_", suffix=".yaml")
        os.close(fd)
        with open(temp_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(modified_config, handle)

        totals = {
            "total_cost_sek": 0.0,
            "total_revenue_sek": 0.0,
            "total_wear_sek": 0.0,
            "min_soc_breaches": 0,
            "unmet_water_kwh": 0.0,
        }
        days_simulated = 0

        try:
            from planner import HeliosPlanner

            for day in self._days_in_range(start_date, end_date):
                input_data = self._build_input_data_for_day(day)
                if not input_data:
                    continue

                planner = HeliosPlanner(temp_path)
                schedule_df = planner.generate_schedule(input_data)
                metrics = self._evaluate_schedule(schedule_df)

                totals["total_cost_sek"] += metrics["cost_sek"]
                totals["total_revenue_sek"] += metrics["revenue_sek"]
                totals["total_wear_sek"] += metrics["wear_sek"]
                totals["min_soc_breaches"] += metrics["min_soc_breaches"]
                totals["unmet_water_kwh"] += metrics["unmet_water_kwh"]
                days_simulated += 1

            if days_simulated == 0:
                return {
                    "total_cost_sek": float("inf"),
                    "total_revenue_sek": 0.0,
                    "total_wear_sek": float("inf"),
                    "min_soc_breaches": 999,
                    "unmet_water_kwh": 999.0,
                    "objective_value": float("inf"),
                }

            objective = (
                totals["total_cost_sek"]
                - totals["total_revenue_sek"]
                + totals["total_wear_sek"]
                + totals["min_soc_breaches"] * 10.0
                + totals["unmet_water_kwh"] * 5.0
            )

            totals["objective_value"] = objective
            return totals

        except Exception as exc:
            print(f"Simulation error: {exc}")
            return {
                "total_cost_sek": float("inf"),
                "total_revenue_sek": 0.0,
                "total_wear_sek": float("inf"),
                "min_soc_breaches": 999,
                "unmet_water_kwh": 999.0,
                "objective_value": float("inf"),
            }
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def _days_in_range(self, start_date: datetime, end_date: datetime) -> Iterable[datetime.date]:
        current = start_date.date()
        target = end_date.date()
        while current <= target:
            yield current
            current += timedelta(days=1)

    def _build_input_data_for_day(self, day: datetime.date) -> Optional[Dict[str, Any]]:
        price_rows = self._fetch_price_rows(day)
        forecast_rows = self._fetch_forecast_rows(day)
        if not price_rows or not forecast_rows:
            return None

        price_data = [
            {
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "import_price_sek_kwh": row["import_price"],
                "export_price_sek_kwh": row["export_price"],
            }
            for start, end, row in price_rows
        ]

        forecast_data = [
            {
                "start_time": start.isoformat(),
                "pv_forecast_kwh": row["pv_forecast_kwh"],
                "load_forecast_kwh": row["load_forecast_kwh"],
                "temp_c": row.get("temp_c"),
            }
            for start, row in forecast_rows
        ]

        initial_state = self._initial_state_for_day(day)
        if not initial_state:
            return None

        day_key = day.isoformat()
        daily_pv = sum(row["pv_forecast_kwh"] for _, row in forecast_rows)
        daily_load = sum(row["load_forecast_kwh"] for _, row in forecast_rows)

        return {
            "price_data": price_data,
            "forecast_data": forecast_data,
            "initial_state": initial_state,
            "daily_pv_forecast": {day_key: daily_pv},
            "daily_load_forecast": {day_key: daily_load},
        }

    def _fetch_price_rows(
        self, day: datetime.date
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, Dict[str, float]]]:
        sql = """
            SELECT slot_start, slot_end, import_price_sek_kwh, export_price_sek_kwh
            FROM slot_observations
            WHERE DATE(slot_start) = ?
            ORDER BY slot_start
        """
        rows: List[Tuple[pd.Timestamp, pd.Timestamp, Dict[str, float]]] = []
        with sqlite3.connect(self.engine.db_path) as conn:
            for slot_start, slot_end, import_price, export_price in conn.execute(
                sql, (day.isoformat(),)
            ):
                if import_price is None and export_price is None:
                    continue
                start_ts = pd.Timestamp(slot_start)
                end_ts = pd.Timestamp(slot_end) if slot_end else pd.NaT
                if start_ts.tzinfo is None:
                    start_ts = start_ts.tz_localize(self.engine.timezone)
                else:
                    start_ts = start_ts.tz_convert(self.engine.timezone)
                if end_ts is pd.NaT:
                    end_ts = start_ts + pd.Timedelta(minutes=15)
                else:
                    if end_ts.tzinfo is None:
                        end_ts = end_ts.tz_localize(self.engine.timezone)
                    else:
                        end_ts = end_ts.tz_convert(self.engine.timezone)
                rows.append(
                    (
                        start_ts,
                        end_ts,
                        {
                            "import_price": (
                                float(import_price) if import_price is not None else 0.0
                            ),
                            "export_price": (
                                float(export_price)
                                if export_price is not None
                                else float(import_price or 0.0)
                            ),
                        },
                    )
                )
        return rows

    def _fetch_forecast_rows(
        self, day: datetime.date
    ) -> List[Tuple[pd.Timestamp, Dict[str, float]]]:
        sql = """
            SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, temp_c, id
            FROM slot_forecasts
            WHERE DATE(slot_start) = ?
            ORDER BY slot_start, id DESC
        """
        data: Dict[str, Tuple[pd.Timestamp, Dict[str, float]]] = {}
        with sqlite3.connect(self.engine.db_path) as conn:
            for slot_start, pv_kwh, load_kwh, temp_c, row_id in conn.execute(
                sql, (day.isoformat(),)
            ):
                if slot_start not in data:
                    ts = pd.Timestamp(slot_start)
                    if ts.tzinfo is None:
                        ts = ts.tz_localize(self.engine.timezone)
                    else:
                        ts = ts.tz_convert(self.engine.timezone)
                    data[slot_start] = (
                        ts,
                        {
                            "pv_forecast_kwh": float(pv_kwh or 0.0),
                            "load_forecast_kwh": float(load_kwh or 0.0),
                            "temp_c": None if temp_c is None else float(temp_c),
                        },
                    )
        return list(data.values())

    # Backwards compatibility for tests that inspect stored data directly
    def _get_stored_historical_data(
        self, start_date: datetime, end_date: datetime
    ) -> Dict[str, list]:
        with sqlite3.connect(self.engine.db_path) as conn:
            obs_query = """
                SELECT slot_start, slot_end, import_kwh, export_kwh, pv_kwh,
                       load_kwh, water_kwh, soc_start_percent, soc_end_percent,
                       import_price_sek_kwh, export_price_sek_kwh, executed_action
                FROM slot_observations
                WHERE DATE(slot_start) >= ? AND DATE(slot_start) <= ?
                ORDER BY slot_start
            """
            observations = conn.execute(
                obs_query, (start_date.date().isoformat(), end_date.date().isoformat())
            ).fetchall()

            forecast_query = """
                SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, temp_c, forecast_version
                FROM slot_forecasts
                WHERE DATE(slot_start) >= ? AND DATE(slot_start) <= ?
                ORDER BY slot_start, forecast_version
            """
            forecasts = conn.execute(
                forecast_query, (start_date.date().isoformat(), end_date.date().isoformat())
            ).fetchall()

        return {"observations": observations, "forecasts": forecasts}

    def _initial_state_for_day(self, day: datetime.date) -> Optional[Dict[str, float]]:
        sql = """
            SELECT soc_start_percent
            FROM slot_observations
            WHERE DATE(slot_start) = ?
            ORDER BY slot_start ASC
            LIMIT 1
        """
        soc_percent = None
        with sqlite3.connect(self.engine.db_path) as conn:
            row = conn.execute(sql, (day.isoformat(),)).fetchone()
            if row and row[0] is not None:
                soc_percent = float(row[0])

        if soc_percent is None:
            return None

        soc_percent = max(0.0, min(100.0, soc_percent))
        battery_kwh = self.capacity_kwh * soc_percent / 100.0
        battery_cost = self.engine.config.get("learning", {}).get(
            "default_battery_cost_sek_per_kwh",
            self.engine.config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.20),
        )

        return {
            "battery_soc_percent": soc_percent,
            "battery_kwh": battery_kwh,
            "battery_cost_sek_per_kwh": float(battery_cost),
        }

    def _evaluate_schedule(self, schedule_df: pd.DataFrame) -> Dict[str, float]:
        if schedule_df.index.name == "start_time" and "start_time" not in schedule_df.columns:
            schedule_df = schedule_df.reset_index()
        if "end_time" not in schedule_df.columns and "end_time" in schedule_df.index.names:
            schedule_df = schedule_df.reset_index()

        cost = 0.0
        revenue = 0.0
        wear = 0.0
        min_soc_breaches = 0
        unmet_water = 0.0

        for _, row in schedule_df.iterrows():
            try:
                start_ts = pd.Timestamp(row["start_time"])
                end_ts = pd.Timestamp(row["end_time"])
            except Exception:
                continue
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize(self.engine.timezone)
            if end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize(self.engine.timezone)

            slot_hours = max(0.25, (end_ts - start_ts).total_seconds() / 3600.0)

            charge_kw = max(0.0, row.get("battery_charge_kw", row.get("charge_kw", 0.0)))
            discharge_kw = max(0.0, row.get("battery_discharge_kw", 0.0))
            charge_kwh = charge_kw * slot_hours
            discharge_kwh = discharge_kw * slot_hours

            adjusted_load = float(row.get("adjusted_load_kwh", 0.0))
            adjusted_pv = float(row.get("adjusted_pv_kwh", 0.0))
            water_grid = float(row.get("water_from_grid_kwh", 0.0))
            water_batt = float(row.get("water_from_battery_kwh", 0.0))
            water_pv = float(row.get("water_from_pv_kwh", 0.0))
            export_kwh = float(row.get("export_kwh", 0.0))
            water_required = float(row.get("water_heating_kw", 0.0)) * slot_hours

            grid_import_kwh = max(
                0.0,
                adjusted_load + water_grid + charge_kwh - adjusted_pv - discharge_kwh - water_pv,
            )

            import_price = float(row.get("import_price_sek_kwh", 0.0))
            export_price = float(row.get("export_price_sek_kwh", import_price))

            cost += grid_import_kwh * import_price
            revenue += export_kwh * export_price
            wear += (charge_kwh + discharge_kwh) * self.cycle_cost

            supplied_water = water_grid + water_batt + water_pv
            if water_required > supplied_water + 1e-3:
                unmet_water += water_required - supplied_water

            projected_soc = row.get("projected_soc_percent")
            if projected_soc is not None and projected_soc < (self.min_soc_percent - 1e-3):
                min_soc_breaches += 1

        return {
            "cost_sek": cost,
            "revenue_sek": revenue,
            "wear_sek": wear,
            "min_soc_breaches": min_soc_breaches,
            "unmet_water_kwh": unmet_water,
        }


class LearningLoops:
    """Learning loops for auto-tuning parameters"""

    def __init__(self, learning_engine: LearningEngine):
        self.engine = learning_engine
        self.simulator = DeterministicSimulator(learning_engine)
        self.config = learning_engine.config
        self.learning_config = learning_engine.learning_config

    def forecast_calibrator(self) -> Optional[Dict[str, Any]]:
        """
        Loop 1: Forecast Calibrator (daily)
        Adjust PV confidence and load safety margins based on forecast errors
        """
        try:
            # Get recent forecast accuracy
            with sqlite3.connect(self.engine.db_path) as conn:
                # Calculate PV bias by hour of day
                pv_query = """
                    SELECT
                        strftime('%H', o.slot_start) as hour,
                        AVG(o.pv_kwh - f.pv_forecast_kwh) as bias,
                        AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)) as mae,
                        AVG(o.pv_kwh) as avg_actual,
                        COUNT(*) as sample_count
                    FROM slot_observations o
                    JOIN slot_forecasts f ON o.slot_start = f.slot_start
                    WHERE DATE(o.slot_start) >= DATE('now', '-14 days')
                    AND o.pv_kwh IS NOT NULL AND f.pv_forecast_kwh IS NOT NULL
                    GROUP BY strftime('%H', o.slot_start)
                    HAVING sample_count >= 3
                """
                pv_results = conn.execute(pv_query).fetchall()

                # Calculate load bias by hour of day
                load_query = """
                    SELECT
                        strftime('%H', o.slot_start) as hour,
                        AVG(o.load_kwh - f.load_forecast_kwh) as bias,
                        AVG(ABS(o.load_kwh - f.load_forecast_kwh)) as mae,
                        AVG(o.load_kwh) as avg_actual,
                        COUNT(*) as sample_count
                    FROM slot_observations o
                    JOIN slot_forecasts f ON o.slot_start = f.slot_start
                    WHERE DATE(o.slot_start) >= DATE('now', '-14 days')
                    AND o.load_kwh IS NOT NULL AND f.load_forecast_kwh IS NOT NULL
                    GROUP BY strftime('%H', o.slot_start)
                    HAVING sample_count >= 3
                """
                load_results = conn.execute(load_query).fetchall()

            # Calculate recommended adjustments
            current_pv_conf = self.config.get("forecasting", {}).get("pv_confidence_percent", 90.0)
            current_load_margin = self.config.get("forecasting", {}).get(
                "load_safety_margin_percent", 110.0
            )

            pv_sample_count = sum(row[4] for row in pv_results) if pv_results else 0
            pv_mae_avg = (
                sum((row[2] or 0) * row[4] for row in pv_results) / pv_sample_count
                if pv_sample_count
                else 0
            )
            pv_bias_avg = (
                sum((row[1] or 0) * row[4] for row in pv_results) / pv_sample_count
                if pv_sample_count
                else 0
            )
            pv_mean_actual = (
                sum((row[3] or 0) * row[4] for row in pv_results) / pv_sample_count
                if pv_sample_count
                else 0
            )
            pv_error_ratio = pv_mae_avg / max(pv_mean_actual, 1e-6)

            hysteresis = 0.05
            pv_high = 0.30
            pv_low = 0.10

            new_pv_conf = current_pv_conf
            if pv_error_ratio > (pv_high + hysteresis):
                new_pv_conf = max(75.0, current_pv_conf - 1.0)
            elif pv_error_ratio < max(0.0, pv_low - hysteresis):
                new_pv_conf = min(98.0, current_pv_conf + 1.0)

            load_sample_count = sum(row[4] for row in load_results) if load_results else 0
            load_mae_avg = (
                sum((row[2] or 0) * row[4] for row in load_results) / load_sample_count
                if load_sample_count
                else 0
            )
            load_mean_actual = (
                sum((row[3] or 0) * row[4] for row in load_results) / load_sample_count
                if load_sample_count
                else 0
            )
            load_error_ratio = load_mae_avg / max(load_mean_actual, 1e-6)

            load_high = 0.20
            load_low = 0.05

            new_load_margin = current_load_margin
            if load_error_ratio > (load_high + hysteresis):
                new_load_margin = min(118.0, current_load_margin + 1.0)
            elif load_error_ratio < max(0.0, load_low - hysteresis):
                new_load_margin = max(100.0, current_load_margin - 1.0)

            max_change = self.learning_config.get("max_daily_param_change", {})
            pv_change_cap = max_change.get("pv_confidence_percent", 1.0)
            load_change_cap = max_change.get("load_safety_margin_percent", 1.0)

            pv_change = abs(new_pv_conf - current_pv_conf)
            load_change = abs(new_load_margin - current_load_margin)

            if pv_change > pv_change_cap:
                delta = pv_change_cap if new_pv_conf > current_pv_conf else -pv_change_cap
                new_pv_conf = current_pv_conf + delta
            if load_change > load_change_cap:
                delta = (
                    load_change_cap if new_load_margin > current_load_margin else -load_change_cap
                )
                new_load_margin = current_load_margin + delta

            changes = {}
            if abs(new_pv_conf - current_pv_conf) >= 0.1:
                changes["forecasting.pv_confidence_percent"] = round(new_pv_conf, 1)
            if abs(new_load_margin - current_load_margin) >= 0.1:
                changes["forecasting.load_safety_margin_percent"] = round(new_load_margin, 1)

            min_samples = self.learning_config.get("min_sample_threshold", 36)
            sufficient_samples = pv_sample_count >= min_samples and load_sample_count >= min_samples

            if changes and sufficient_samples:
                return {
                    "loop": "forecast_calibrator",
                    "changes": changes,
                    "metrics": {
                        "pv_mae_avg": round(pv_mae_avg, 4),
                        "pv_mean": round(pv_mean_actual, 4),
                        "load_mae_avg": round(load_mae_avg, 4),
                        "load_mean": round(load_mean_actual, 4),
                        "pv_error_ratio": round(pv_error_ratio, 4),
                        "load_error_ratio": round(load_error_ratio, 4),
                        "pv_samples": pv_sample_count,
                        "load_samples": load_sample_count,
                        "pv_bias_avg": round(pv_bias_avg, 4),
                    },
                    "reason": (
                        f"PV error ratio {pv_error_ratio:.3f}, "
                        f"Load error ratio {load_error_ratio:.3f}"
                    ),
                }

            return None

        except Exception as e:
            print(f"Forecast calibrator error: {e}")
            return None

    def threshold_tuner(self) -> Optional[Dict[str, Any]]:
        """
        Loop 2: Threshold Tuner (every 1-2 days)
        Optimize battery_use_margin_sek and export_profit_margin_sek
        """
        try:
            horizon_days = self.learning_config.get("horizon_days", 7)
            end_date = datetime.now(self.engine.timezone)
            start_date = end_date - timedelta(days=horizon_days)

            # Current values
            current_battery_margin = self.config.get("decision_thresholds", {}).get(
                "battery_use_margin_sek", 0.10
            )
            current_export_margin = self.config.get("decision_thresholds", {}).get(
                "export_profit_margin_sek", 0.05
            )

            # Search grid around current values
            search_space = []
            for battery_margin in [
                current_battery_margin - 0.02,
                current_battery_margin,
                current_battery_margin + 0.02,
            ]:
                for export_margin in [
                    current_export_margin - 0.02,
                    current_export_margin,
                    current_export_margin + 0.02,
                ]:
                    # Apply bounds
                    battery_margin = max(0.00, min(0.30, battery_margin))
                    export_margin = max(0.00, min(0.30, export_margin))
                    search_space.append(
                        {
                            "decision_thresholds.battery_use_margin_sek": battery_margin,
                            "decision_thresholds.export_profit_margin_sek": export_margin,
                        }
                    )

            # Evaluate each candidate
            best_candidate = None
            best_objective = float("inf")

            for candidate in search_space:
                result = self.simulator.simulate_with_params(start_date, end_date, candidate)
                objective = result.get("objective_value", float("inf"))

                if objective < best_objective:
                    best_objective = objective
                    best_candidate = candidate

            # Get baseline (current config) performance
            baseline_result = self.simulator.simulate_with_params(start_date, end_date, {})
            baseline_objective = baseline_result.get("objective_value", float("inf"))

            # Check improvement
            improvement = (
                (baseline_objective - best_objective) / baseline_objective
                if baseline_objective > 0
                else 0
            )
            min_improvement = self.learning_config.get("min_improvement_threshold", 0.015)

            if improvement >= min_improvement and best_candidate:
                # Check daily change caps
                max_change = self.learning_config.get("max_daily_param_change", {})
                battery_change_cap = max_change.get("battery_use_margin_sek", 0.02)
                export_change_cap = max_change.get("export_profit_margin_sek", 0.02)

                battery_change = abs(
                    best_candidate["decision_thresholds.battery_use_margin_sek"]
                    - current_battery_margin
                )
                export_change = abs(
                    best_candidate["decision_thresholds.export_profit_margin_sek"]
                    - current_export_margin
                )

                if battery_change <= battery_change_cap and export_change <= export_change_cap:
                    return {
                        "loop": "threshold_tuner",
                        "changes": best_candidate,
                        "metrics": {
                            "baseline_objective": round(baseline_objective, 2),
                            "best_objective": round(best_objective, 2),
                            "improvement_percent": round(improvement * 100, 2),
                        },
                        "reason": f"Objective improvement: {improvement:.1%}",
                    }

            return None

        except Exception as e:
            print(f"Threshold tuner error: {e}")
            return None

    def s_index_tuner(self) -> Optional[Dict[str, Any]]:
        """
        Loop 3: S-index Tuner (weekly or on drift)
        Optimize base_factor, pv_deficit_weight, temp_weight
        """
        try:
            horizon_days = self.learning_config.get("horizon_days", 7)
            end_date = datetime.now(self.engine.timezone)
            start_date = end_date - timedelta(days=horizon_days)

            # Current values
            s_index_config = self.config.get("s_index", {})
            current_base = s_index_config.get("base_factor", 1.05)
            current_pv_weight = s_index_config.get("pv_deficit_weight", 0.30)
            current_temp_weight = s_index_config.get("temp_weight", 0.20)
            max_factor = s_index_config.get("max_factor", 1.5)

            # Search grid around current values
            search_space = []
            for base_delta in [-0.05, 0, 0.05]:
                for pv_delta in [-0.05, 0, 0.05]:
                    for temp_delta in [-0.05, 0, 0.05]:
                        new_base = max(0.9, min(max_factor, current_base + base_delta))
                        new_pv = max(0.0, min(0.6, current_pv_weight + pv_delta))
                        new_temp = max(0.0, min(0.5, current_temp_weight + temp_delta))

                        search_space.append(
                            {
                                "s_index.base_factor": new_base,
                                "s_index.pv_deficit_weight": new_pv,
                                "s_index.temp_weight": new_temp,
                            }
                        )

            # Evaluate each candidate
            best_candidate = None
            best_objective = float("inf")

            for candidate in search_space:
                result = self.simulator.simulate_with_params(start_date, end_date, candidate)
                objective = result.get("objective_value", float("inf"))

                if objective < best_objective:
                    best_objective = objective
                    best_candidate = candidate

            # Get baseline performance
            baseline_result = self.simulator.simulate_with_params(start_date, end_date, {})
            baseline_objective = baseline_result.get("objective_value", float("inf"))

            # Check improvement
            improvement = (
                (baseline_objective - best_objective) / baseline_objective
                if baseline_objective > 0
                else 0
            )
            min_improvement = self.learning_config.get("min_improvement_threshold", 0.015)

            if improvement >= min_improvement and best_candidate:
                # Check daily change caps
                max_change = self.learning_config.get("max_daily_param_change", {})
                base_change_cap = max_change.get("s_index_base_factor", 0.05)
                pv_change_cap = max_change.get("s_index_pv_deficit_weight", 0.05)
                temp_change_cap = max_change.get("s_index_temp_weight", 0.05)

                base_change = abs(best_candidate["s_index.base_factor"] - current_base)
                pv_change = abs(best_candidate["s_index.pv_deficit_weight"] - current_pv_weight)
                temp_change = abs(best_candidate["s_index.temp_weight"] - current_temp_weight)

                if (
                    base_change <= base_change_cap
                    and pv_change <= pv_change_cap
                    and temp_change <= temp_change_cap
                ):

                    return {
                        "loop": "s_index_tuner",
                        "changes": best_candidate,
                        "metrics": {
                            "baseline_objective": round(baseline_objective, 2),
                            "best_objective": round(best_objective, 2),
                            "improvement_percent": round(improvement * 100, 2),
                        },
                        "reason": f"S-index objective improvement: {improvement:.1%}",
                    }

            return None

        except Exception as e:
            print(f"S-index tuner error: {e}")
            return None

    def export_guard_tuner(self) -> Optional[Dict[str, Any]]:
        """
        Loop 4: Export Guard Tuner (weekly)
        Optimize future_price_guard_buffer_sek to reduce premature exports
        """
        try:
            horizon_days = self.learning_config.get("horizon_days", 7)
            end_date = datetime.now(self.engine.timezone)
            start_date = end_date - timedelta(days=horizon_days)

            # Current value
            current_buffer = self.config.get("arbitrage", {}).get(
                "future_price_guard_buffer_sek", 0.00
            )

            # Analyze export patterns to identify premature exports
            with sqlite3.connect(self.engine.db_path) as conn:
                # Get export events with price information
                export_query = """
                    SELECT o.slot_start, o.export_kwh, o.export_price_sek_kwh,
                           f.pv_forecast_kwh, f.load_forecast_kwh
                    FROM slot_observations o
                    LEFT JOIN slot_forecasts f ON o.slot_start = f.slot_start
                    WHERE DATE(o.slot_start) >= ? AND DATE(o.slot_start) <= ?
                    AND o.export_kwh > 0.1
                    ORDER BY o.slot_start
                """
                export_events = conn.execute(
                    export_query, (start_date.date().isoformat(), end_date.date().isoformat())
                ).fetchall()

                # Get future prices for each export slot to identify if it was premature
                premature_exports = 0
                total_exports = len(export_events)
                missed_profit = 0.0

                for (
                    slot_start,
                    export_kwh,
                    export_price,
                    pv_forecast,
                    load_forecast,
                ) in export_events:
                    if export_price is None:
                        continue
                    slot_ts = pd.Timestamp(slot_start)
                    if slot_ts.tzinfo is None:
                        slot_ts = slot_ts.tz_localize(self.engine.timezone)
                    else:
                        slot_ts = slot_ts.tz_convert(self.engine.timezone)

                    future_window_end = slot_ts + timedelta(hours=6)
                    future_query = """
                        SELECT MAX(import_price_sek_kwh) as max_future_price
                        FROM slot_observations
                        WHERE slot_start > ?
                        AND slot_start <= ?
                        AND import_price_sek_kwh IS NOT NULL
                    """
                    future_result = conn.execute(
                        future_query,
                        (slot_ts.isoformat(), future_window_end.isoformat()),
                    ).fetchone()

                    if future_result and future_result[0] is not None:
                        future_price = float(future_result[0])
                        dynamic_threshold = max(current_buffer, 0.05)
                        if future_price > float(export_price) + dynamic_threshold:
                            premature_exports += 1
                            missed_profit += float(export_kwh) * max(
                                0.0, future_price - float(export_price)
                            )

                # Calculate metrics
                premature_rate = premature_exports / total_exports if total_exports > 0 else 0
                avg_missed_profit = missed_profit / total_exports if total_exports > 0 else 0

            # Search space around current buffer
            search_space = []
            for buffer_delta in [-0.05, 0, 0.05]:
                new_buffer = max(0.00, min(0.50, current_buffer + buffer_delta))
                search_space.append({"arbitrage.future_price_guard_buffer_sek": new_buffer})

            # Evaluate each candidate
            best_candidate = None
            best_objective = float("inf")

            for candidate in search_space:
                result = self.simulator.simulate_with_params(start_date, end_date, candidate)
                objective = result.get("objective_value", float("inf"))

                if objective < best_objective:
                    best_objective = objective
                    best_candidate = candidate

            # Get baseline performance
            baseline_result = self.simulator.simulate_with_params(start_date, end_date, {})
            baseline_objective = baseline_result.get("objective_value", float("inf"))

            # Check improvement
            improvement = (
                (baseline_objective - best_objective) / baseline_objective
                if baseline_objective > 0
                else 0
            )
            min_improvement = self.learning_config.get("min_improvement_threshold", 0.015)

            # Heuristic: if premature export rate is high, be more aggressive with buffer
            if premature_rate > 0.3 and current_buffer < 0.20:
                # Force increase buffer even if improvement threshold not met
                recommended_buffer = min(0.50, current_buffer + 0.05)
                best_candidate = {"arbitrage.future_price_guard_buffer_sek": recommended_buffer}
                improvement = 0.02  # Small improvement to justify change

            elif premature_rate < 0.1 and current_buffer > 0.10:
                # Can reduce buffer if premature exports are rare
                recommended_buffer = max(0.00, current_buffer - 0.05)
                best_candidate = {"arbitrage.future_price_guard_buffer_sek": recommended_buffer}
                improvement = 0.01

            if improvement >= min_improvement and best_candidate:
                # Check daily change caps
                max_change = self.learning_config.get("max_daily_param_change", {})
                buffer_change_cap = max_change.get("future_price_guard_buffer_sek", 0.05)

                buffer_change = abs(
                    best_candidate["arbitrage.future_price_guard_buffer_sek"] - current_buffer
                )

                if buffer_change <= buffer_change_cap:
                    return {
                        "loop": "export_guard_tuner",
                        "changes": best_candidate,
                        "metrics": {
                            "baseline_objective": round(baseline_objective, 2),
                            "best_objective": round(best_objective, 2),
                            "improvement_percent": round(improvement * 100, 2),
                            "premature_export_rate": round(premature_rate, 3),
                            "total_exports": total_exports,
                            "avg_missed_profit_sek": round(avg_missed_profit, 3),
                        },
                        "reason": (
                            "Export guard optimization: "
                            f"{premature_rate:.1%} premature exports, "
                            f"{improvement:.1%} improvement"
                        ),
                    }

            return None

        except Exception as e:
            print(f"Export guard tuner error: {e}")
            return None


class NightlyOrchestrator:
    """Nightly orchestration for learning loops"""

    def __init__(self, learning_engine: LearningEngine):
        self.engine = learning_engine
        self.loops = LearningLoops(learning_engine)
        self.config = learning_engine.config
        self.learning_config = learning_engine.learning_config

    def run_nightly_job(self) -> Dict[str, Any]:
        """Run the complete nightly learning job"""
        if not self.learning_config.get("enable", False):
            return {"status": "skipped", "reason": "Learning disabled"}

        job_start = datetime.now(self.engine.timezone)

        run_id = None
        try:
            # Record learning run start
            with sqlite3.connect(self.engine.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO learning_runs (started_at, horizon_days, status)
                    VALUES (?, ?, ?)
                """,
                    (job_start.isoformat(), self.learning_config.get("horizon_days", 7), "started"),
                )
                run_id = cursor.lastrowid
                conn.commit()

            # Run learning loops in sequence
            all_changes = {}
            loop_results = []

            # Loop 1: Forecast Calibrator
            result = self.loops.forecast_calibrator()
            if result:
                all_changes.update(result["changes"])
                loop_results.append(result)

            # Loop 2: Threshold Tuner (run every other day)
            if job_start.day % 2 == 0:  # Every other day
                result = self.loops.threshold_tuner()
                if result:
                    all_changes.update(result["changes"])
                    loop_results.append(result)

            # Loop 3: S-index Tuner (weekly)
            if job_start.weekday() == 0:  # Monday
                result = self.loops.s_index_tuner()
                if result:
                    all_changes.update(result["changes"])
                    loop_results.append(result)

            # Loop 4: Export Guard Tuner (weekly)
            if job_start.weekday() == 0:  # Monday
                result = self.loops.export_guard_tuner()
                if result:
                    all_changes.update(result["changes"])
                    loop_results.append(result)

            # Apply changes if auto_apply is enabled
            applied_changes = {}
            if all_changes and self.learning_config.get("auto_apply", True):
                applied_changes = self._apply_changes(all_changes, loop_results, run_id=run_id)

            # Record completion
            job_end = datetime.now(self.engine.timezone)
            with sqlite3.connect(self.engine.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE learning_runs
                    SET completed_at = ?, status = ?, result_metrics_json = ?
                    WHERE id = ?
                """,
                    (
                        job_end.isoformat(),
                        "completed",
                        json.dumps(
                            {
                                "loops_run": len(loop_results),
                                "changes_proposed": len(all_changes),
                                "changes_applied": len(applied_changes),
                                "loop_results": loop_results,
                            }
                        ),
                        run_id,
                    ),
                )

                # Persist current S-index base factor for this run's day so
                # we can visualise its evolution over time, even if no
                # changes were applied.
                try:
                    with open("config.yaml", "r", encoding="utf-8") as handle:
                        cfg = yaml.safe_load(handle) or {}
                except FileNotFoundError:
                    cfg = {}

                s_index_cfg = (cfg.get("s_index") or {}) if isinstance(cfg, dict) else {}
                base_factor = s_index_cfg.get("base_factor") or s_index_cfg.get("static_factor")
                if base_factor is not None:
                    # Mirror into consolidated daily metrics so the planner has
                    # a single place to read the learned S-index factor.
                    self.engine.upsert_daily_metrics(
                        job_start.date(), {"s_index_base_factor": float(base_factor)}
                    )

                conn.commit()

            # Compute and persist hourly forecast error arrays for diagnostics and
            # future learning use (e.g. Helios-style load/PV adjustment per hour).
            try:
                self.engine.store_hourly_forecast_errors(days_back=self.learning_config.get("horizon_days", 7))
            except Exception as exc:
                print(f"Failed to store hourly forecast errors: {exc}")

            return {
                "status": "completed",
                "run_id": run_id,
                "duration_minutes": (job_end - job_start).total_seconds() / 60,
                "loops_run": len(loop_results),
                "changes_proposed": len(all_changes),
                "changes_applied": len(applied_changes),
                "loop_results": loop_results,
            }

        except Exception as e:
            # Record failure
            if run_id is not None:
                with sqlite3.connect(self.engine.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        UPDATE learning_runs
                        SET completed_at = ?, status = 'failed', error_message = ?
                        WHERE id = ?
                    """,
                        (datetime.now(self.engine.timezone).isoformat(), str(e), run_id),
                    )
                    conn.commit()

            return {"status": "failed", "error": str(e), "run_id": run_id}

    def _apply_changes(
        self,
        changes: Dict[str, Any],
        loop_results: List[Dict],
        run_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Record proposed parameter changes in the learning history without
        mutating config.yaml.

        The current design keeps config.yaml static; learning outputs used
        by the planner live in SQLite (e.g. learning_daily_metrics). This
        method now only records parameter-level history for observability.
        """
        if not changes:
            return {}

        try:
            diff_summary: Dict[str, Dict[str, Any]] = {}

            # We no longer mutate config.yaml; instead we record the
            # proposed new values as a virtual diff (old is unknown here).
            for key_path, new_value in changes.items():
                diff_summary[key_path] = {"old": None, "new": new_value}

            version_payload = {
                "loops": {r["loop"]: r["metrics"] for r in loop_results},
                "diff": diff_summary,
            }

            with sqlite3.connect(self.engine.db_path) as conn:
                cursor = conn.cursor()

                # Persist the virtual config version for traceability
                cursor.execute(
                    """
                    INSERT INTO config_versions (yaml_blob, reason, metrics_json, applied)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        "",  # yaml_blob left empty because we no longer write config.yaml
                        "; ".join(filter(None, [r.get("reason", "") for r in loop_results])),
                        json.dumps(version_payload),
                        False,
                    ),
                )

                # Record parameter-level history for each proposed change
                def _infer_loop(path: str) -> str:
                    if path.startswith("forecasting."):
                        return "forecast_calibrator"
                    if path.startswith("decision_thresholds."):
                        return "threshold_tuner"
                    if path.startswith("s_index."):
                        return "s_index_tuner"
                    if path.startswith("arbitrage.future_price_guard_buffer_sek"):
                        return "export_guard_tuner"
                    return ""

                reason_text = "; ".join(
                    filter(None, [r.get("reason", "") for r in loop_results])
                ) or None

                for key_path, change in diff_summary.items():
                    new_val = change.get("new")
                    loop_name = _infer_loop(key_path)
                    cursor.execute(
                        """
                        INSERT INTO learning_param_history (
                            run_id, param_path, old_value, new_value, loop, reason
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            key_path,
                            None,
                            None if new_val is None else str(new_val),
                            loop_name or None,
                            reason_text,
                        ),
                    )

                conn.commit()

            return changes

        except Exception as e:
            print(f"Failed to record parameter changes: {e}")
            return {}


if __name__ == "__main__":
    # Test basic functionality
    engine = LearningEngine()
    status = engine.get_status()
    print("Learning Engine Status:")
    print(json.dumps(status, indent=2))

    # Test learning loops
    if status.get("enabled", False):
        loops = LearningLoops(engine)
        orchestrator = NightlyOrchestrator(engine)

        print("\nTesting learning loops:")

        # Test forecast calibrator
        fc_result = loops.forecast_calibrator()
        print(f"Forecast Calibrator: {fc_result}")

        # Test threshold tuner
        tt_result = loops.threshold_tuner()
        print(f"Threshold Tuner: {tt_result}")

        # Test S-index tuner
        si_result = loops.s_index_tuner()
        print(f"S-index Tuner: {si_result}")

        # Test Export guard tuner
        eg_result = loops.export_guard_tuner()
        print(f"Export Guard Tuner: {eg_result}")

        # Test nightly orchestration (dry run)
        print("\nTesting nightly orchestration...")
        orch_result = orchestrator.run_nightly_job()
        print(f"Orchestration result: {json.dumps(orch_result, indent=2)}")
