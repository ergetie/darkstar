import os
import sqlite3
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import pytz
import yaml
from pathlib import Path

from backend.learning.store import LearningStore


class LearningEngine:
    """Learning engine for auto-tuning and forecast calibration"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self.learning_config = self.config.get("learning", {})
        self.db_path = self.learning_config.get("sqlite_path", "data/planner_learning.db")
        self.timezone = pytz.timezone(self.config.get("timezone", "Europe/Stockholm"))

        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize Store
        self.store = LearningStore(self.db_path, self.timezone)

        raw_map = self.learning_config.get("sensor_map", {}) or {}
        self.sensor_map = {str(v).lower(): str(k).lower() for k, v in raw_map.items()}

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            # Fallback to default config
            with open("config.default.yaml", "r", encoding="utf-8") as f:
                return yaml.safe_load(f)

    # Delegate storage methods to store
    def store_slot_prices(self, price_rows: Any) -> None:
        self.store.store_slot_prices(price_rows)

    def store_slot_observations(self, observations_df: pd.DataFrame) -> None:
        self.store.store_slot_observations(observations_df)

    def store_forecasts(self, forecasts: List[Dict], forecast_version: str) -> None:
        self.store.store_forecasts(forecasts, forecast_version)

    def log_training_episode(
        self, input_data: Dict, schedule_df: pd.DataFrame, config_overrides: Optional[Dict] = None
    ) -> None:
        """
        Log a training episode (inputs + outputs) for RL.
        Also logs the planned schedule to slot_plans for metric tracking.
        """
        # 1. Log to training_episodes
        episode_id = str(uuid.uuid4())

        inputs_json = json.dumps(input_data, default=str)
        schedule_json = schedule_df.to_json(orient="records", date_format="iso")
        context_json = None  # TODO: Capture context if available
        config_overrides_json = json.dumps(config_overrides) if config_overrides else None

        self.store.store_training_episode(
            episode_id=episode_id,
            inputs_json=inputs_json,
            schedule_json=schedule_json,
            context_json=context_json,
            config_overrides_json=config_overrides_json,
        )

        # 2. Log to slot_plans
        self.store.store_plan(schedule_df)

    def _canonical_sensor_name(self, name: str) -> str:
        """Map incoming sensor names to canonical identifiers."""
        key = str(name).lower()
        if key in self.sensor_map:
            return self.sensor_map[key]

        stripped = key.replace("sensor.", "")
        for token in ("energy", "power", "total", "_cumulative", "_kw", "_kwh"):
            stripped = stripped.replace(token, "")
        stripped = stripped.strip("_")

        # Explicit handling for compound names often found in HA
        if stripped == "load_consumption":
            return "load"
        if stripped == "pv_production":
            return "pv"
        if stripped == "grid_import":
            return "import"
        if stripped == "grid_export":
            return "export"

        aliases = {
            "import": {"grid_import", "gridin", "import", "grid", "from_grid"},
            "export": {"grid_export", "gridout", "export", "to_grid"},
            "pv": {"pv", "solar", "pvproduction", "production", "yield"},
            "load": {"load", "consumption", "house", "usage", "load_consumption"},
            "water": {"water", "vvb", "waterheater", "heater"},
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
        """
        # (Logic identical to original learning.py, preserved here)
        slot_records: Dict[str, pd.DataFrame] = {}
        for sensor_name, data in cumulative_data.items():
            if data:
                df = pd.DataFrame(data, columns=["timestamp", "cumulative_value"])
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize(self.timezone)
                else:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(self.timezone)
                df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
                slot_records[sensor_name] = df

        if not slot_records:
            return pd.DataFrame()

        all_timestamps = []
        for df in slot_records.values():
            all_timestamps.extend(df["timestamp"].tolist())

        if not all_timestamps:
            return pd.DataFrame()

        min_ts = min(all_timestamps)
        max_ts = max(all_timestamps)

        if min_ts.tzinfo is None:
            min_ts = min_ts.replace(tzinfo=self.timezone)
        else:
            min_ts = min_ts.astimezone(self.timezone)

        floored_minute = (min_ts.minute // resolution_minutes) * resolution_minutes
        start_time = min_ts.replace(minute=floored_minute, second=0, microsecond=0)
        end_time = max_ts

        slots = pd.date_range(
            start=start_time, end=end_time, freq=f"{resolution_minutes}min", tz=self.timezone
        )

        slot_df = pd.DataFrame({"slot_start": slots[:-1], "slot_end": slots[1:]})
        quality_flags: List[Dict] = [{} for _ in range(len(slot_df))]  # Simplified type hint

        for sensor_name, df in slot_records.items():
            canonical = self._canonical_sensor_name(sensor_name)
            base_series = df.set_index("timestamp")["cumulative_value"]
            aligned = base_series.reindex(slots)
            gaps = aligned.isna()
            reindexed = base_series.reindex(slots, method="ffill")
            reindexed = reindexed.ffill().fillna(0)
            raw_diff = reindexed.diff().fillna(0)

            gap_mask = gaps | gaps.shift(1, fill_value=False)
            mask_spike = (raw_diff > 5.0) & ~gap_mask
            raw_diff[mask_spike] = 0.0
            deltas = raw_diff.clip(lower=0)

            slot_df[f"{canonical}_kwh"] = deltas.iloc[1:].values

        if any(self._canonical_sensor_name(name) == "soc" for name in slot_records):
            soc_name = next(
                name for name in slot_records if self._canonical_sensor_name(name) == "soc"
            )
            soc_series = (
                slot_records[soc_name]
                .set_index("timestamp")["cumulative_value"]
                .reindex(slots, method="ffill")
                .ffill()
            )
            slot_df["soc_start_percent"] = soc_series.iloc[:-1].values
            slot_df["soc_end_percent"] = soc_series.iloc[1:].values

        slot_df["duration_minutes"] = resolution_minutes
        return slot_df

    def calculate_metrics(self, days_back: int = 7) -> Dict[str, Any]:
        """Calculate learning metrics for the last N days"""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date()
            metrics = {}

            # 1. Forecast Accuracy (Existing)
            pv_query = """
                SELECT AVG(ABS(o.pv_kwh - f.pv_forecast_kwh))
                FROM slot_observations o
                JOIN slot_forecasts f ON o.slot_start = f.slot_start
                WHERE DATE(o.slot_start) >= ?
            """
            pv_res = conn.execute(pv_query, (cutoff_date.isoformat(),)).fetchone()
            if pv_res and pv_res[0]:
                metrics["mae_pv"] = round(pv_res[0], 4)

            # 2. Plan Deviation (New for K6)
            # MAE of (Planned Charge - Actual Charge)
            plan_query = """
                SELECT 
                    AVG(ABS(o.batt_charge_kwh - p.planned_charge_kwh)) as mae_charge,
                    AVG(ABS(o.batt_discharge_kwh - p.planned_discharge_kwh)) as mae_discharge,
                    AVG(ABS(o.soc_end_percent - p.planned_soc_percent)) as mae_soc
                FROM slot_observations o
                JOIN slot_plans p ON o.slot_start = p.slot_start
                WHERE DATE(o.slot_start) >= ?
            """
            plan_res = conn.execute(plan_query, (cutoff_date.isoformat(),)).fetchone()
            if plan_res:
                metrics["mae_plan_charge"] = round(plan_res[0] or 0.0, 4)
                metrics["mae_plan_discharge"] = round(plan_res[1] or 0.0, 4)
                metrics["mae_plan_soc"] = round(plan_res[2] or 0.0, 4)

            # 3. Cost Deviation (New for K6)
            # We need to calculate Realized Cost first.
            # Realized Cost ~= (Import * Price) - (Export * Price)
            # Compare with Planned Cost.
            cost_query = """
                SELECT 
                    SUM(o.import_kwh * o.import_price_sek_kwh - o.export_kwh * o.export_price_sek_kwh) as realized_cost,
                    SUM(p.planned_cost_sek) as planned_cost
                FROM slot_observations o
                JOIN slot_plans p ON o.slot_start = p.slot_start
                WHERE DATE(o.slot_start) >= ?
                  AND o.import_price_sek_kwh IS NOT NULL
            """
            cost_res = conn.execute(cost_query, (cutoff_date.isoformat(),)).fetchone()
            if cost_res and cost_res[0] is not None and cost_res[1] is not None:
                metrics["total_realized_cost"] = round(cost_res[0], 2)
                metrics["total_planned_cost"] = round(cost_res[1], 2)
                metrics["cost_deviation"] = round(abs(cost_res[0] - cost_res[1]), 2)

            return metrics

            return metrics

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the learning engine."""
        last_obs = self.store.get_last_observation_time()

        # Count training episodes
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            episodes = conn.execute("SELECT COUNT(*) FROM training_episodes").fetchone()[0]

        return {
            "status": "active",
            "last_observation": last_obs.isoformat() if last_obs else None,
            "training_episodes": episodes,
            "db_path": self.db_path,
            "timezone": str(self.timezone),
        }

    def get_performance_series(self, days_back: int = 7) -> Dict[str, List[Dict]]:
        """
        Get time-series data for performance visualization.
        Returns:
            {
                "soc_series": [{"time": iso, "planned": float, "actual": float}, ...],
                "cost_series": [{"date": iso, "planned": float, "realized": float}, ...]
            }
        """
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cutoff_date = (datetime.now(self.timezone) - timedelta(days=days_back)).date()

            # 1. SoC Series (15-min resolution)
            soc_query = """
                SELECT 
                    o.slot_start,
                    p.planned_soc_percent,
                    o.soc_end_percent
                FROM slot_observations o
                LEFT JOIN slot_plans p ON o.slot_start = p.slot_start
                WHERE DATE(o.slot_start) >= ?
                ORDER BY o.slot_start ASC
            """
            cursor = conn.execute(soc_query, (cutoff_date.isoformat(),))
            soc_series = []
            for row in cursor:
                soc_series.append({"time": row[0], "planned": row[1], "actual": row[2]})

            # 2. Cost Series (Daily resolution)
            cost_query = """
                SELECT 
                    DATE(o.slot_start) as day,
                    SUM(p.planned_cost_sek) as planned_cost,
                    SUM(o.import_kwh * o.import_price_sek_kwh - o.export_kwh * o.export_price_sek_kwh) as realized_cost
                FROM slot_observations o
                LEFT JOIN slot_plans p ON o.slot_start = p.slot_start
                WHERE DATE(o.slot_start) >= ?
                  AND o.import_price_sek_kwh IS NOT NULL
                GROUP BY day
                ORDER BY day ASC
            """
            cursor = conn.execute(cost_query, (cutoff_date.isoformat(),))
            cost_series = []
            for row in cursor:
                cost_series.append(
                    {
                        "date": row[0],
                        "planned": row[1] if row[1] is not None else 0.0,
                        "realized": row[2] if row[2] is not None else 0.0,
                    }
                )

            return {"soc_series": soc_series, "cost_series": cost_series}
