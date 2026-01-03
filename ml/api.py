from __future__ import annotations

import sqlite3
import aiosqlite
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from backend.learning import LearningEngine, get_learning_engine

# Lazy import for experimental simulation module (not included in production Docker)
if TYPE_CHECKING:
    from ml.simulation.dataset import AntaresSlotRecord


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
) -> list[dict[str, Any]]:
    """
    Return forecast slots for the given time window and version.

    The result is a list of dicts with keys:
        - slot_start (datetime, timezone-aware in planner timezone)
        - pv_forecast_kwh (float)
        - load_forecast_kwh (float)
        - temp_c (float | None)
        - forecast_version (str)
        - pv_correction_kwh (float)
        - load_correction_kwh (float)
        - correction_source (str)
    """
    engine = _get_engine()

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        query = """
            SELECT
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

    records: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        records.append(
            {
                "slot_start": row["slot_start"],
                "pv_forecast_kwh": float(row.get("pv_forecast_kwh") or 0.0),
                "load_forecast_kwh": float(row.get("load_forecast_kwh") or 0.0),
                "pv_p10": (
                    float(row.get("pv_p10") or 0.0) if row.get("pv_p10") is not None else None
                ),
                "pv_p90": (
                    float(row.get("pv_p90") or 0.0) if row.get("pv_p90") is not None else None
                ),
                "load_p10": (
                    float(row.get("load_p10") or 0.0) if row.get("load_p10") is not None else None
                ),
                "load_p90": (
                    float(row.get("load_p90") or 0.0) if row.get("load_p90") is not None else None
                ),
                "temp_c": row.get("temp_c"),
                "forecast_version": row.get("forecast_version"),
                "pv_correction_kwh": float(row.get("pv_correction_kwh") or 0.0),
                "load_correction_kwh": float(row.get("load_correction_kwh") or 0.0),
                "correction_source": row.get("correction_source") or "none",
            },
        )
    return records


async def get_forecast_slots_async(
    start_time: datetime,
    end_time: datetime,
    forecast_version: str,
) -> list[dict[str, Any]]:
    """
    Async return forecast slots for the given time window and version.
    Uses aiosqlite for non-blocking I/O.
    """
    engine = _get_engine()

    query = """
        SELECT
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
        FROM slot_forecasts
        WHERE slot_start >= ?
          AND slot_start < ?
          AND forecast_version = ?
        ORDER BY slot_start ASC
    """

    async with aiosqlite.connect(engine.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            query, (start_time.isoformat(), end_time.isoformat(), forecast_version)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return []

    # Convert to DataFrame for consistent processing
    data = [dict(row) for row in rows]
    df = pd.DataFrame(data)

    if df.empty:
        return []

    # Parse timestamps and normalise to the planner timezone
    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
    df = df.dropna(subset=["slot_start"])
    df["slot_start"] = df["slot_start"].dt.tz_convert(engine.timezone)

    records: list[dict[str, Any]] = []
    for row in df.to_dict("records"):
        records.append(
            {
                "slot_start": row["slot_start"],
                "pv_forecast_kwh": float(row.get("pv_forecast_kwh") or 0.0),
                "load_forecast_kwh": float(row.get("load_forecast_kwh") or 0.0),
                "pv_p10": (
                    float(row.get("pv_p10") or 0.0) if row.get("pv_p10") is not None else None
                ),
                "pv_p90": (
                    float(row.get("pv_p90") or 0.0) if row.get("pv_p90") is not None else None
                ),
                "load_p10": (
                    float(row.get("load_p10") or 0.0) if row.get("load_p10") is not None else None
                ),
                "load_p90": (
                    float(row.get("load_p90") or 0.0) if row.get("load_p90") is not None else None
                ),
                "temp_c": row.get("temp_c"),
                "forecast_version": row.get("forecast_version"),
                "pv_correction_kwh": float(row.get("pv_correction_kwh") or 0.0),
                "load_correction_kwh": float(row.get("load_correction_kwh") or 0.0),
                "correction_source": row.get("correction_source") or "none",
            },
        )
    return records


def get_antares_slots(dataset_version: str = "v1") -> pd.DataFrame:
    """
    Return the Antares v1 simulation training dataset as a DataFrame.

    - Currently supports dataset_version=\"v1\" only.
    - Wraps `build_antares_training_dataset` and converts records to a stable
      tabular form for downstream training/analysis.

    Note: This function requires the ml.simulation module which is not
    included in production Docker builds.
    """
    # Lazy import - only available in development environment
    from ml.simulation.dataset import build_antares_training_dataset

    if dataset_version != "v1":
        raise ValueError(f"Unsupported dataset_version: {dataset_version}")

    records: list[AntaresSlotRecord] = build_antares_training_dataset()
    if not records:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for rec in records:
        rows.append(
            {
                "episode_id": rec.episode_id,
                "episode_date": rec.episode_date,
                "system_id": rec.system_id,
                "data_quality_status": rec.data_quality_status,
                "slot_start": rec.slot_start,
                "import_price_sek_kwh": rec.import_price_sek_kwh,
                "export_price_sek_kwh": rec.export_price_sek_kwh,
                "load_kwh": rec.load_kwh,
                "pv_kwh": rec.pv_kwh,
                "import_kwh": rec.import_kwh,
                "export_kwh": rec.export_kwh,
                "batt_charge_kwh": rec.batt_charge_kwh,
                "batt_discharge_kwh": rec.batt_discharge_kwh,
                "soc_start_percent": rec.soc_start_percent,
                "soc_end_percent": rec.soc_end_percent,
                "battery_masked": rec.battery_masked,
                "dataset_version": dataset_version,
            }
        )

    return pd.DataFrame(rows)
