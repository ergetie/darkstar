from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
import pytz

from learning import LearningEngine, get_learning_engine
from ml.corrector import predict_corrections
from ml.forward import generate_forward_slots


def _get_engine() -> LearningEngine:
    engine = get_learning_engine()
    if not isinstance(engine, LearningEngine):
        raise TypeError("get_learning_engine() did not return a LearningEngine instance")
    return engine


def _apply_corrections_to_db(
    engine: LearningEngine,
    corrections: List[Dict[str, Any]],
    forecast_version: str,
) -> None:
    if not corrections:
        return

    import sqlite3

    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        cursor = conn.cursor()
        for row in corrections:
            slot_start = row.get("slot_start")
            if slot_start is None:
                continue

            # Normalize timestamp exactly like learning.py (store_forecasts)
            if hasattr(slot_start, "astimezone"):
                ts_str = slot_start.astimezone(engine.timezone).isoformat()
            else:
                ts_str = (
                    pd.to_datetime(slot_start)
                    .astimezone(engine.timezone)
                    .isoformat()
                )

            pv_corr = float(row.get("pv_correction_kwh") or 0.0)
            load_corr = float(row.get("load_correction_kwh") or 0.0)
            source = row.get("correction_source") or "none"

            cursor.execute(
                """
                UPDATE slot_forecasts
                SET
                    pv_correction_kwh = ?,
                    load_correction_kwh = ?,
                    correction_source = ?
                WHERE slot_start = ?
                  AND forecast_version = ?
                """,
                (pv_corr, load_corr, source, ts_str, forecast_version),
            )

        conn.commit()


def run_inference(
    horizon_hours: int = 168,
    forecast_version: str = "aurora",
) -> Dict[str, Any]:
    """
    Orchestrate Aurora base forecast + correction models and persist results.

    Steps:
        1. Model 1 (Forward): generate base forecasts into slot_forecasts.
        2. Model 2 (Corrector): compute per-slot corrections for the near-term horizon.
        3. Persist: write correction values and source tags into slot_forecasts.
    """
    engine = _get_engine()
    tz = engine.timezone

    # Step 1: Base AURORA forecast for full horizon (S-index compatible).
    generate_forward_slots(horizon_hours=horizon_hours, forecast_version=forecast_version)

    # Step 2: Correction for the upcoming 48h (planner horizon).
    # The corrector itself applies the Graduation Path and safety clamping.
    corrections, source = predict_corrections(
        horizon_hours=min(48, horizon_hours),
        forecast_version=forecast_version,
    )

    # Step 3: Persist corrections into DB
    _apply_corrections_to_db(engine, corrections, forecast_version=forecast_version)

    return {
        "status": "ok",
        "forecast_version": forecast_version,
        "horizon_hours": horizon_hours,
        "correction_source": source,
        "num_slots_corrected": len(corrections),
        "timestamp": datetime.now(tz).isoformat(),
    }


if __name__ == "__main__":
    result = run_inference()
    print(result)
