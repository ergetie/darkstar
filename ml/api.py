from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import sqlite3

from learning import LearningEngine, get_learning_engine


def _get_engine() -> LearningEngine:
    """Return the shared LearningEngine instance."""
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):  # defensive guard
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def get_forecast_slots(
    start_time: datetime,
    end_time: datetime,
    forecast_version: str,
) -> List[Dict[str, Any]]:
    """
    Return forecast slots for the given time window and version.

    The result is a list of dicts with keys:
        - slot_start (datetime, timezone-aware in planner timezone)
        - pv_forecast_kwh (float)
        - load_forecast_kwh (float)
        - temp_c (float | None)
        - forecast_version (str)
    """
    engine = _get_engine()

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        query = """
            SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, temp_c, forecast_version
            FROM slot_forecasts
            WHERE slot_start >= ?
              AND slot_start < ?
              AND forecast_version = ?
            ORDER BY slot_start ASC
        """
        df = pd.read_sql_query(
            query,
            conn,
            params=(start_time.isoformat(), end_time.isoformat(), forecast_version),
        )

    if df.empty:
        return []

    # Parse timestamps and normalise to the planner timezone
    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["slot_start"])
    df["slot_start"] = df["slot_start"].dt.tz_convert(engine.timezone)

    records: List[Dict[str, Any]] = []
    for row in df.to_dict("records"):
        records.append(
            {
                "slot_start": row["slot_start"],
                "pv_forecast_kwh": float(row.get("pv_forecast_kwh") or 0.0),
                "load_forecast_kwh": float(row.get("load_forecast_kwh") or 0.0),
                "temp_c": row.get("temp_c"),
                "forecast_version": row.get("forecast_version"),
            },
        )
    return records

