import logging

import pandas as pd
from typing import Any, cast


logger = logging.getLogger("darkstar.analyst")


class EnergyAnalyst:
    """
    Scans the planner schedule to find optimal time windows for manual loads
    defined in config.yaml (appliances).
    """

    def __init__(self, schedule_json: dict[str, Any], config: dict[str, Any]):
        self.schedule: list[dict[str, Any]] = schedule_json.get("schedule", [])
        self.meta = schedule_json.get("meta", {})
        self.appliances: dict[str, Any] = config.get("appliances", {})
        self._df = self._to_dataframe(self.schedule)

    def _to_dataframe(self, schedule: list[dict[str, Any]]) -> pd.DataFrame:
        if not schedule:
            return pd.DataFrame()
        df = pd.DataFrame(schedule)

        try:
            if "start_time" in df.columns:
                df["start_time"] = pd.to_datetime(df["start_time"], format="mixed", utc=True)
            if "end_time" in df.columns:
                df["end_time"] = pd.to_datetime(df["end_time"], format="mixed", utc=True)
        except Exception as e:
            logger.error(f"Timestamp parsing failed: {e}")
            if "start_time" in df.columns:
                df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce", utc=True)

        if "start_time" in df.columns:
            df.set_index("start_time", inplace=True)
            df.sort_index(inplace=True)

        return df

    def analyze(self) -> dict[str, Any]:
        """
        Find best windows for all configured appliances.
        """
        if self._df.empty:
            return {"error": "No schedule data available"}

        if not self.appliances:
            return {"error": "No appliances defined in config.yaml"}

        now = pd.Timestamp.now(tz="UTC")
        future_df = self._df[self._df.index >= now].copy()

        if future_df.empty:
            future_df = self._df

        results: dict[str, Any] = {}
        for key, app in self.appliances.items():
            if not isinstance(app, dict):
                continue
            app_dict = cast(dict[str, Any], app)
            duration = float(str(app_dict.get("duration_hours", 1.0)))
            label = str(app_dict.get("label", key))

            recommendation = self._find_windows_for_duration(future_df, duration)
            recommendation["label"] = label
            results[key] = recommendation

        return {"analyzed_at": now.isoformat(), "recommendations": results}

    def _find_windows_for_duration(self, df: pd.DataFrame, duration_hours: float) -> dict[str, Any]:
        slots_needed = int(duration_hours * 4)

        if len(df) < slots_needed:
            return {"error": "Horizon too short"}

        best_grid: dict[str, Any] = {"start": None, "avg_price": float("inf"), "end": None}
        best_solar: dict[str, Any] = {"start": None, "avg_pv_surplus": float("-inf"), "end": None}

        for i in range(len(df) - slots_needed):
            window = df.iloc[i : i + slots_needed]
            start_time = window.index[0]
            end_time = window.index[-1]

            avg_price = window["import_price_sek_kwh"].mean()
            pv = window["pv_forecast_kwh"].mean()
            load = window["load_forecast_kwh"].mean()
            surplus = pv - load

            if avg_price < best_grid["avg_price"]:
                best_grid = {
                    "start": start_time.isoformat(),
                    "avg_price": round(avg_price, 3),
                    "end": end_time.isoformat(),
                }

            if surplus > best_solar["avg_pv_surplus"]:
                best_solar = {
                    "start": start_time.isoformat(),
                    "avg_pv_surplus": round(surplus, 3),
                    "end": end_time.isoformat(),
                }

        return {"best_grid_window": best_grid, "best_solar_window": best_solar}
