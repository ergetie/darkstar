import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import select, desc, func

from backend.learning.store import LearningStore
from backend.learning.models import LearningDailyMetric, SlotObservation, SlotForecast

logger = logging.getLogger("darkstar.learning.analyst")


class Analyst:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.learning_config = config.get("learning", {})
        self.store = LearningStore(
            self.learning_config.get("sqlite_path", "data/planner_learning.db"),
            config.get("timezone", "Europe/Stockholm"),
        )

    def analyze_forecast_accuracy(self, days: int = 7) -> dict[str, Any]:
        """
        Analyze forecast accuracy over the last N days using SQLAlchemy/Pandas.
        Returns bias metrics for Load and PV.
        """
        if not self.learning_config.get("enable", False):
            return {}

        # 1. Fetch Data
        # We need joined observations (actuals) and plans (forecasts)
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        obs_df = self._fetch_observations(start_date, end_date)
        if obs_df.empty:
            return {"status": "no_data", "reason": "No observations found"}

        plans_df = self._fetch_plans(start_date, end_date)
        if plans_df.empty:
            return {"status": "no_data", "reason": "No plans found"}

        # Merge
        df = pd.merge(
            obs_df, plans_df, on="slot_start", how="inner", suffixes=("_actual", "_forecast")
        )

        if df.empty:
            return {"status": "no_data", "reason": "No overlapping data"}

        # 2. Calculate Bias
        # Bias = Actual - Forecast
        load_actual = df["load_kwh"] if "load_kwh" in df.columns else df.get("load_kwh_actual", 0.0)
        pv_actual = df["pv_kwh"] if "pv_kwh" in df.columns else df.get("pv_kwh_actual", 0.0)

        df["load_bias"] = load_actual - df["load_forecast_kwh"]
        df["pv_bias"] = pv_actual - df["pv_forecast_kwh"]

        # Extract Hour of Day
        df["hour"] = df["slot_start"].dt.hour

        # Aggregate by Hour
        hourly_stats = df.groupby("hour")[["load_bias", "pv_bias"]].mean()

        # 3. Format Results
        results = {
            "status": "success",
            "days_analyzed": days,
            "sample_count": len(df),
            "hourly_bias": hourly_stats.to_dict(orient="index"),
            "global_bias": {
                "load_kwh": float(df["load_bias"].mean()),
                "pv_kwh": float(df["pv_bias"].mean()),
            },
        }

        return results

    def update_learning_overlays(self) -> None:
        """
        Calculate new adjustment factors and write to learning_daily_metrics using SQLAlchemy.
        """
        if not self.learning_config.get("auto_tune_enabled", False):
            logger.info("Analyst: Auto-tune disabled. Skipping update.")
            return

        logger.info("Analyst: Running forecast analysis...")
        analysis = self.analyze_forecast_accuracy(days=7)

        if analysis.get("status") != "success":
            logger.warning(f"Analyst: Analysis failed or no data: {analysis.get('reason')}")
            return

        hourly_bias = analysis.get("hourly_bias", {})
        global_bias = analysis.get("global_bias", {})

        # Construct Adjustment Arrays (24 hours)
        load_adj = [0.0] * 24
        pv_adj = [0.0] * 24

        for hour, stats in hourly_bias.items():
            if 0 <= hour < 24:
                # Clamp adjustments to avoid wild swings
                load_adj[hour] = max(-2.0, min(2.0, stats.get("load_bias", 0.0)))
                pv_adj[hour] = max(-2.0, min(2.0, stats.get("pv_bias", 0.0)))

        # Calculate new s_index_base_factor
        s_index_base_factor = self._calculate_new_s_index_base_factor(global_bias)

        # Write to DB
        today_str = datetime.now().date().isoformat()

        try:
            with self.store.Session() as session:
                metric = session.get(LearningDailyMetric, today_str)
                if not metric:
                    metric = LearningDailyMetric(date=today_str)
                    session.add(metric)
                
                metric.pv_adjustment_by_hour_kwh = json.dumps(pv_adj)
                metric.load_adjustment_by_hour_kwh = json.dumps(load_adj)
                metric.s_index_base_factor = s_index_base_factor
                metric.created_at = datetime.now() # SQLAlchemy DateTime
                session.commit()
                
            logger.info(
                f"Analyst: Updated learning overlays for {today_str} (s_index={s_index_base_factor:.4f})."
            )

        except Exception as e:
            logger.error(f"Analyst: Failed to write overlays: {e}")

    def _calculate_new_s_index_base_factor(self, global_bias: dict[str, float]) -> float:
        """
        Calculate updated s_index_base_factor based on forecast bias using SQLAlchemy.
        """
        s_index_cfg = self.config.get("s_index", {})
        config_base = float(s_index_cfg.get("base_factor", 1.05))
        max_factor = float(s_index_cfg.get("max_factor", 1.5))
        min_factor = float(s_index_cfg.get("min_factor", 0.8))

        # Get the max daily change allowed
        max_change = float(
            self.learning_config.get("max_daily_param_change", {}).get("s_index_base_factor", 0.05)
        )

        # Get last learned value
        try:
            with self.store.Session() as session:
                stmt = select(LearningDailyMetric.s_index_base_factor).where(
                    LearningDailyMetric.s_index_base_factor.is_not(None)
                ).order_by(desc(LearningDailyMetric.date)).limit(1)
                row = session.execute(stmt).scalar_one_or_none()
                current_base = float(row) if row is not None else config_base
        except Exception:
            current_base = config_base

        # Calculate adjustment based on load bias
        load_bias_kwh = global_bias.get("load_kwh", 0.0)
        bias_adjustment = load_bias_kwh * 0.02

        # Clamp to max daily change
        bias_adjustment = max(-max_change, min(max_change, bias_adjustment))

        # Calculate new factor
        new_factor = current_base + bias_adjustment
        new_factor = max(min_factor, min(max_factor, new_factor))

        logger.info(
            f"Analyst: s_index_base_factor: {current_base:.4f} -> {new_factor:.4f} (bias_adj={bias_adjustment:.4f})"
        )

        return round(new_factor, 4)

    def _fetch_observations(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch observations within date range using SQLAlchemy/Pandas."""
        query = "SELECT slot_start, load_kwh, pv_kwh FROM slot_observations"
        try:
            # Using store.engine directly for pandas
            df = pd.read_sql_query(query, self.store.engine)

            if not df.empty:
                df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True)
                start_utc = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
                end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
                df = df[(df["slot_start"] >= start_utc) & (df["slot_start"] <= end_utc)]
            return df
        except Exception as e:
            logger.error(f"Analyst: _fetch_observations error: {e}")
            return pd.DataFrame()

    def _fetch_plans(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch forecasts within date range using SQLAlchemy/Pandas."""
        query = "SELECT slot_start, load_forecast_kwh, pv_forecast_kwh FROM slot_forecasts"
        try:
            df = pd.read_sql_query(query, self.store.engine)
            if not df.empty:
                df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True)
                start_utc = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
                end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)
                df = df[(df["slot_start"] >= start_utc) & (df["slot_start"] <= end_utc)]
            return df
        except Exception as e:
            logger.error(f"Analyst: _fetch_plans error: {e}")
            return pd.DataFrame()
