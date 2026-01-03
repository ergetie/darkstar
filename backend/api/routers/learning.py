"""
Learning API Router - Rev ARC1

Provides endpoints for the learning engine (auto-tuning, forecast calibration).
"""

import json
import logging
import sqlite3

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("darkstar.api.learning")

router = APIRouter(tags=["learning"])


def _get_learning_engine():
    """Get the learning engine instance."""
    from backend.learning import get_learning_engine

    return get_learning_engine()


@router.get("/api/learning/status")
async def learning_status():
    """Return learning engine status and metrics."""
    try:
        engine = _get_learning_engine()
        status = engine.get_status()
        return status
    except Exception as e:
        logger.exception("Failed to get learning status")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/learning/history")
async def learning_history(limit: int = Query(20, ge=1, le=100)):
    """Return learning engine run history."""
    try:
        engine = _get_learning_engine()

        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, run_date, status, metrics_json, config_changes_json
                FROM learning_runs
                ORDER BY run_date DESC
                LIMIT ?
            """,
                (limit,),
            )

            runs = []
            for row in cursor.fetchall():
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
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("Failed to get learning history")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/learning/run")
async def learning_run():
    """Trigger learning orchestration manually."""
    try:
        engine = _get_learning_engine()
        from backend.learning import NightlyOrchestrator

        orchestrator = NightlyOrchestrator(engine)
        result = orchestrator.run_nightly_job()

        return result
    except ImportError:
        return {"status": "error", "message": "NightlyOrchestrator not available"}
    except Exception as e:
        logger.exception("Failed to run learning")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/learning/loops")
async def learning_loops():
    """Get status of individual learning loops."""
    try:
        engine = _get_learning_engine()

        # Get loop statuses from database
        loops_status = {}
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # Check for learning_loops table
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='learning_loops'
            """)
            if cursor.fetchone():
                cursor.execute("""
                    SELECT loop_name, last_run, status, error_message
                    FROM learning_loops
                """)
                for row in cursor.fetchall():
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/learning/daily_metrics")
async def learning_daily_metrics():
    """Get latest daily metrics from learning engine."""
    try:
        engine = _get_learning_engine()

        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='daily_metrics'
            """)
            if not cursor.fetchone():
                return {"message": "Daily metrics table not yet created"}

            cursor.execute("""
                SELECT date, pv_error_mean_abs_kwh, load_error_mean_abs_kwh, s_index_base_factor
                FROM daily_metrics
                ORDER BY date DESC
                LIMIT 1
            """)
            row = cursor.fetchone()

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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/learning/changes")
async def learning_changes(limit: int = Query(10, ge=1, le=50)):
    """Return recent learning configuration changes."""
    try:
        engine = _get_learning_engine()

        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # Check if table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='config_versions'
            """)
            if not cursor.fetchone():
                return {"changes": [], "message": "Config versions table not yet created"}

            cursor.execute(
                """
                SELECT id, created_at, reason, applied, metrics_json
                FROM config_versions
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

            changes = []
            for row in cursor.fetchall():
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
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/learning/record_observation")
async def record_observation():
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
        raise HTTPException(status_code=500, detail=str(e))
