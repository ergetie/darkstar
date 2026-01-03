import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from backend.learning.store import LearningStore


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
        Analyze forecast accuracy over the last N days.
        Returns bias metrics for Load and PV.
        """
        if not self.learning_config.get("enable", False):
            return {}

        # 1. Fetch Data
        # We need joined observations (actuals) and plans (forecasts)
        # Since we don't have a direct join table, we fetch both and merge in pandas.

        # Fetch Observations (Actuals)
        end_date = datetime.now(UTC)
        start_date = end_date - timedelta(days=days)

        obs_df = self._fetch_observations(start_date, end_date)
        if obs_df.empty:
            return {"status": "no_data", "reason": "No observations found"}

        # Fetch Plans (Forecasts)
        plans_df = self._fetch_plans(start_date, end_date)
        if plans_df.empty:
            return {"status": "no_data", "reason": "No plans found"}

        # Merge
        # Ensure timestamps are timezone-aware and aligned
        df = pd.merge(
            obs_df, plans_df, on="slot_start", how="inner", suffixes=("_actual", "_forecast")
        )

        if df.empty:
            return {"status": "no_data", "reason": "No overlapping data"}

        # 2. Calculate Bias
        # Bias = Actual - Forecast
        # Positive Bias = Actual > Forecast (Under-forecasted)
        # Negative Bias = Actual < Forecast (Over-forecasted)

        # Bias = Actual - Forecast
        # Note: obs_df has 'load_kwh', plans_df has 'load_forecast_kwh'.
        # Merge won't rename them unless they collide.

        load_actual = df["load_kwh"] if "load_kwh" in df.columns else df.get("load_kwh_actual", 0.0)
        pv_actual = df["pv_kwh"] if "pv_kwh" in df.columns else df.get("pv_kwh_actual", 0.0)

        df["load_bias"] = load_actual - df["load_forecast_kwh"]
        df["pv_bias"] = pv_actual - df["pv_forecast_kwh"]

        # Extract Hour of Day
        df["hour"] = df["slot_start"].dt.hour

        # Aggregate by Hour
        hourly_stats = df.groupby("hour")[["load_bias", "pv_bias"]].mean()

        # 3. Format Results

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
        Calculate new adjustment factors and write to learning_daily_metrics.
        Only runs if auto_tune_enabled is True.

        Updates:
        - pv_adjustment_by_hour_kwh: Hourly PV bias corrections
        - load_adjustment_by_hour_kwh: Hourly load bias corrections
        - s_index_base_factor: Base safety factor (increases if consistently under-forecasting)
        """
        if not self.learning_config.get("auto_tune_enabled", False):
            print("Analyst: Auto-tune disabled. Skipping update.")
            return

        print("Analyst: Running forecast analysis...")
        analysis = self.analyze_forecast_accuracy(days=7)

        if analysis.get("status") != "success":
            print(f"Analyst: Analysis failed or no data: {analysis.get('reason')}")
            return

        hourly_bias = analysis.get("hourly_bias", {})
        global_bias = analysis.get("global_bias", {})

        # Construct Adjustment Arrays (24 hours)
        # We apply the bias directly as the adjustment.
        # If Load Bias is +0.5 (Actual was 0.5 higher), we want to ADD 0.5 to future forecasts.
        # So Adjustment = Bias.

        load_adj = [0.0] * 24
        pv_adj = [0.0] * 24

        for hour, stats in hourly_bias.items():
            if 0 <= hour < 24:
                # Clamp adjustments to avoid wild swings
                # e.g. Max +/- 2.0 kWh per hour
                load_adj[hour] = max(-2.0, min(2.0, stats.get("load_bias", 0.0)))
                pv_adj[hour] = max(-2.0, min(2.0, stats.get("pv_bias", 0.0)))

        # Calculate new s_index_base_factor based on forecast accuracy
        # If load was consistently under-forecasted (positive bias), increase base_factor
        # If load was over-forecasted (negative bias), decrease base_factor
        s_index_base_factor = self._calculate_new_s_index_base_factor(global_bias)

        # Write to DB for "today" so it's picked up immediately
        today_str = datetime.now().date().isoformat()

        try:
            with sqlite3.connect(self.store.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO learning_daily_metrics 
                    (date, pv_adjustment_by_hour_kwh, load_adjustment_by_hour_kwh, s_index_base_factor, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        today_str,
                        json.dumps(pv_adj),
                        json.dumps(load_adj),
                        s_index_base_factor,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                conn.commit()
            print(
                f"Analyst: Updated learning overlays for {today_str} (s_index_base_factor={s_index_base_factor:.4f})."
            )

        except Exception as e:
            print(f"Analyst: Failed to write overlays: {e}")

    def _calculate_new_s_index_base_factor(self, global_bias: dict[str, float]) -> float:
        """
        Calculate updated s_index_base_factor based on forecast bias.

        Logic:
        - Start from config base_factor (or last learned value)
        - If load was under-forecasted (positive bias), increase factor
        - If load was over-forecasted (negative bias), decrease factor
        - Apply max daily change limit from config
        - Clamp to [min_factor, max_factor] range
        """
        s_index_cfg = self.config.get("s_index", {})
        config_base = float(s_index_cfg.get("base_factor", 1.05))
        max_factor = float(s_index_cfg.get("max_factor", 1.5))
        min_factor = float(s_index_cfg.get("min_factor", 0.8))

        # Get the max daily change allowed
        max_change = float(
            self.learning_config.get("max_daily_param_change", {}).get("s_index_base_factor", 0.05)
        )

        # Get last learned value (or use config default)
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT s_index_base_factor FROM learning_daily_metrics 
                    WHERE s_index_base_factor IS NOT NULL 
                    ORDER BY date DESC LIMIT 1
                    """
                )
                row = cursor.fetchone()
                current_base = row[0] if row and row[0] is not None else config_base
        except Exception:
            current_base = config_base

        # Calculate adjustment based on load bias
        # Positive bias = actual > forecast = under-forecasted = need more buffer
        load_bias_kwh = global_bias.get("load_kwh", 0.0)

        # Scale: +1 kWh bias per slot on average → +0.02 to base factor
        # This is fairly conservative; adjust as needed
        bias_adjustment = load_bias_kwh * 0.02

        # Clamp to max daily change
        bias_adjustment = max(-max_change, min(max_change, bias_adjustment))

        # Calculate new factor
        new_factor = current_base + bias_adjustment

        # Clamp to valid range
        new_factor = max(min_factor, min(max_factor, new_factor))

        print(
            f"Analyst: s_index_base_factor: {current_base:.4f} -> {new_factor:.4f} (bias_adj={bias_adjustment:.4f})"
        )

        return round(new_factor, 4)

    def _fetch_observations(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch observations within date range."""
        query = "SELECT slot_start, load_kwh, pv_kwh FROM slot_observations"

        try:
            with sqlite3.connect(self.store.db_path) as conn:
                df = pd.read_sql_query(query, conn)

                if not df.empty:
                    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True)
                    # Convert start/end to UTC for comparison
                    start_utc = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
                    end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)

                    df = df[(df["slot_start"] >= start_utc) & (df["slot_start"] <= end_utc)]
                return df
        except Exception as e:
            print(f"Analyst: _fetch_observations error: {e}")
            return pd.DataFrame()

    def _fetch_plans(self, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch forecasts within date range."""
        query = "SELECT slot_start, load_forecast_kwh, pv_forecast_kwh FROM slot_forecasts"
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                df = pd.read_sql_query(query, conn)
                if not df.empty:
                    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True)
                    # Convert start/end to UTC for comparison
                    start_utc = start.astimezone(UTC) if start.tzinfo else start.replace(tzinfo=UTC)
                    end_utc = end.astimezone(UTC) if end.tzinfo else end.replace(tzinfo=UTC)

                    df = df[(df["slot_start"] >= start_utc) & (df["slot_start"] <= end_utc)]
                return df
        except Exception as e:
            print(f"Analyst: _fetch_plans error: {e}")
            return pd.DataFrame()
