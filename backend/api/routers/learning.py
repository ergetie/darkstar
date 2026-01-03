"""
Learning API Router - Rev ARC1

Provides endpoints for the learning engine (auto-tuning, forecast calibration).
"""

import asyncio
import json
import logging
import sqlite3
from typing import Any, cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("darkstar.api.learning")

router = APIRouter(tags=["learning"])


def _get_learning_engine() -> Any:
    """Get the learning engine instance."""
    from backend.learning import get_learning_engine

    return get_learning_engine()


@router.get(
    "/api/learning/status",
    summary="Get Learning Status",
    description="Return learning engine status and metrics.",
)
async def learning_status() -> dict[str, Any]:
    """Return learning engine status and metrics."""
    try:
        engine = _get_learning_engine()
        status = engine.get_status()
        return cast("dict[str, Any]", status)
    except Exception as e:
        logger.exception("Failed to get learning status")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/history",
    summary="Get Learning History",
    description="Return learning engine run history.",
)
async def learning_history(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """Return learning engine run history."""
    try:
        engine = _get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        async with (
            aiosqlite.connect(db_path) as conn,
            conn.execute(
                """
                SELECT id, started_at, status, result_metrics_json, params_json
                FROM learning_runs
                ORDER BY started_at DESC
                LIMIT ?
            """,
                (limit,),
            ) as cursor,
        ):
            runs: list[dict[str, Any]] = []
            for row in await cursor.fetchall():
                run = {
                    "id": row[0],
                    "run_date": row[1],
                    "status": row[2],
                    "metrics": json.loads(row[3]) if row[3] else None,
                    "config_changes": json.loads(row[4]) if row[4] else None,
                }
                runs.append(run)

        return {"runs": runs, "count": len(runs)}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return {"runs": [], "count": 0, "message": "Learning history table not yet created"}
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get learning history")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/api/learning/run",
    summary="Trigger Learning Run",
    description="Trigger learning orchestration manually.",
)
async def learning_run() -> dict[str, Any]:
    """Trigger learning orchestration manually."""
    try:
        from backend.learning.reflex import AuroraReflex
        from ml.train import train_models

        def _run_heavy_tasks():
            # Run Reflex
            reflex = AuroraReflex()
            report = reflex.run(dry_run=False)

            # Run Training
            train_models(days_back=90, min_samples=100)
            return report

        # Offload to thread to avoid blocking event loop
        reflex_report = await asyncio.to_thread(_run_heavy_tasks)

        return {
            "status": "success",
            "reflex_report": reflex_report,
            "message": "Learning run completed (Reflex + Train)",
        }
    except ImportError:
        return {"status": "error", "message": "Reflex or ML module not available"}
    except Exception as e:
        logger.exception("Failed to run learning")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/loops",
    summary="Get Learning Loops",
    description="Get status of individual learning loops.",
)
async def learning_loops() -> dict[str, Any]:
    """Get status of individual learning loops."""
    try:
        engine = _get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        # Get loop statuses from database
        loops_status = {}
        async with (
            aiosqlite.connect(db_path) as conn,
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_loops'"
            ) as cursor,
        ):
            if await cursor.fetchone():
                async with conn.execute("""
                        SELECT loop_name, last_run, status, error_message
                        FROM learning_loops
                    """) as loops_cursor:
                    for row in await loops_cursor.fetchall():
                        loops_status[row[0]] = {
                            "last_run": row[1],
                            "status": row[2],
                            "error": row[3],
                        }

        # Define known loops with their statuses
        known_loops = ["pv_forecast", "load_forecast", "s_index", "arbitrage"]
        result = {}
        for loop in known_loops:
            if loop in loops_status:
                result[loop] = loops_status[loop]
            else:
                result[loop] = {"status": "not_run", "last_run": None, "error": None}

        return {"loops": result}
    except Exception as e:
        logger.exception("Failed to get learning loops")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/daily_metrics",
    summary="Get Daily Metrics",
    description="Get latest daily metrics from learning engine.",
)
async def learning_daily_metrics():
    """Get latest daily metrics from learning engine."""
    try:
        engine = _get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        async with aiosqlite.connect(db_path) as conn:
            # Check if table exists
            async with conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='daily_metrics'
            """) as cursor:
                if not await cursor.fetchone():
                    return {"message": "Daily metrics table not yet created"}

            async with conn.execute("""
                SELECT date, pv_error_mean_abs_kwh, load_error_mean_abs_kwh, s_index_base_factor
                FROM daily_metrics
                ORDER BY date DESC
                LIMIT 1
            """) as cursor:
                row = await cursor.fetchone()

            if not row:
                return {"message": "No daily metrics yet"}

            return {
                "date": row[0],
                "pv_error_mean_abs_kwh": float(row[1]) if row[1] is not None else None,
                "load_error_mean_abs_kwh": float(row[2]) if row[2] is not None else None,
                "s_index_base_factor": float(row[3]) if row[3] is not None else None,
            }
    except Exception as e:
        logger.exception("Failed to get daily metrics")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/changes",
    summary="Get Learning Changes",
    description="Return recent learning configuration changes.",
)
async def learning_changes(limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """Return recent learning configuration changes."""
    try:
        engine = _get_learning_engine()
        db_path = str(getattr(engine, "db_path", ""))

        async with aiosqlite.connect(db_path) as conn:
            # Check if table exists
            async with conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='config_versions'
            """) as cursor:
                if not await cursor.fetchone():
                    return {"changes": [], "message": "Config versions table not yet created"}

            async with conn.execute(
                """
                SELECT id, created_at, reason, applied, metrics_json
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            ) as cursor:
                changes: list[dict[str, Any]] = []
                for row in await cursor.fetchall():
                    change = {
                        "id": row[0],
                        "created_at": row[1],
                        "reason": row[2],
                        "applied": bool(row[3]),
                        "metrics": json.loads(row[4]) if row[4] else None,
                    }
                    changes.append(change)

        return {"changes": changes}
    except Exception as e:
        logger.exception("Failed to get learning changes")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/api/learning/record_observation",
    summary="Record Observation",
    description="Trigger observation recording from current system state.",
)
async def record_observation() -> dict[str, str]:
    """Trigger observation recording from current system state."""
    try:
        # Import the recording function
        from backend.recorder import record_observation_from_current_state

        record_observation_from_current_state()
        return {"status": "success", "message": "Observation recorded"}
    except ImportError:
        return {"status": "error", "message": "Recorder module not available"}
    except Exception as e:
        logger.exception("Failed to record observation")
        raise HTTPException(status_code=500, detail=str(e)) from e
