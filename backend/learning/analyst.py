import sqlite3
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from backend.learning.store import LearningStore

class Analyst:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.learning_config = config.get("learning", {})
        self.store = LearningStore(
            self.learning_config.get("sqlite_path", "data/planner_learning.db"),
            config.get("timezone", "Europe/Stockholm")
        )

    def analyze_forecast_accuracy(self, days: int = 7) -> Dict[str, Any]:
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
        end_date = datetime.now(timezone.utc)
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
        df = pd.merge(obs_df, plans_df, on="slot_start", how="inner", suffixes=("_actual", "_forecast"))
        
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
                "pv_kwh": float(df["pv_bias"].mean())
            }
        }
        
        return results

    def update_learning_overlays(self) -> None:
        """
        Calculate new adjustment factors and write to learning_daily_metrics.
        Only runs if auto_tune_enabled is True.
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

        # Write to DB
        # We write this for "today" so it's picked up immediately.
        today_str = datetime.now().date().isoformat()
        
        # We also need s_index_base_factor. For now, keep it static or read existing?
        # Let's read the *last* one or default to 1.05.
        # For K9, we only tune Load/PV bias.
        
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                # Check existing to preserve s_index
                cursor = conn.execute(
                    "SELECT s_index_base_factor FROM learning_daily_metrics WHERE date = ?", 
                    (today_str,)
                )
                row = cursor.fetchone()
                s_index = row[0] if row else 1.05
                
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
                        s_index,
                        datetime.now(timezone.utc).isoformat()
                    )
                )
                conn.commit()
            print(f"Analyst: Updated learning overlays for {today_str}.")
            
        except Exception as e:
            print(f"Analyst: Failed to write overlays: {e}")

    def _fetch_observations(self, start: datetime, end: datetime) -> pd.DataFrame:
        # Fetch all observations (or filter by date string if optimization needed later)
        # We filter strictly in Python to avoid SQLite timestamp string comparison issues.
        query = "SELECT slot_start, load_kwh, pv_kwh FROM slot_observations"
        
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                df = pd.read_sql_query(query, conn)
                
                if not df.empty:
                    df["slot_start"] = pd.to_datetime(df["slot_start"])
                    if df["slot_start"].dt.tz is None:
                         df["slot_start"] = df["slot_start"].dt.tz_localize("UTC")
                    
                    # Filter strictly in Pandas
                    df = df[(df["slot_start"] >= start) & (df["slot_start"] <= end)]
                return df
        except Exception:
            return pd.DataFrame()

    def _fetch_plans(self, start: datetime, end: datetime) -> pd.DataFrame:
        query = "SELECT slot_start, load_forecast_kwh, pv_forecast_kwh FROM slot_plans"
        try:
            with sqlite3.connect(self.store.db_path) as conn:
                df = pd.read_sql_query(query, conn)
                if not df.empty:
                    df["slot_start"] = pd.to_datetime(df["slot_start"])
                    if df["slot_start"].dt.tz is None:
                         df["slot_start"] = df["slot_start"].dt.tz_localize("UTC")
                    
                    # Filter strictly in Pandas
                    df = df[(df["slot_start"] >= start) & (df["slot_start"] <= end)]
                return df
        except Exception:
            return pd.DataFrame()
