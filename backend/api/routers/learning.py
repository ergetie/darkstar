import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, select

from backend.learning.models import ConfigVersion, LearningRun

if TYPE_CHECKING:
    from backend.learning.store import LearningStore

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
        # get_status is now async
        status = await engine.get_status()
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
    """Return learning engine run history using Async SQLAlchemy."""
    try:
        engine = _get_learning_engine()
        store: LearningStore = engine.store

        async with store.AsyncSession() as session:
            stmt = select(LearningRun).order_by(desc(LearningRun.started_at)).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            results: list[dict[str, Any]] = []
            for run in rows:
                results.append(
                    {
                        "id": run.id,
                        "run_date": run.started_at.isoformat() if run.started_at else None,
                        "status": run.status,
                        "training_type": run.training_type,
                        "models_trained": json.loads(run.models_trained)
                        if run.models_trained
                        else [],
                        "training_duration_seconds": run.training_duration_seconds,
                        "partial_failure": run.partial_failure,
                        "metrics": json.loads(run.result_metrics_json)
                        if run.result_metrics_json
                        else None,
                        "config_changes": json.loads(run.params_json) if run.params_json else None,
                    }
                )
            return {"runs": results, "count": len(results)}
    except Exception as e:
        logger.warning(f"Failed to get learning history (DB may be uninitialized): {e}")
        return {"runs": [], "count": 0, "message": f"Learning history unavailable: {e!s}"}


@router.post(
    "/api/learning/train",
    summary="Trigger ML Training",
    description="Trigger manual ML model retraining now.",
)
async def learning_train() -> dict[str, Any]:
    """Trigger ML model retraining manually using the unified orchestrator."""
    try:
        from ml.training_orchestrator import train_all_models

        logger.info("Manual training triggered via API")

        # train_all_models is async and handles locking/logging
        raw_result = await train_all_models(training_type="manual")
        result: dict[str, Any] = raw_result

        if result.get("status") == "busy":
            raise HTTPException(status_code=409, detail="Training already in progress")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to train models")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/api/learning/run",
    summary="Trigger Learning Run (Full)",
    description="Trigger full learning suite (Reflex + Training).",
)
async def learning_run() -> dict[str, Any]:
    """Trigger full learning run (Sync Reflex + Async Training)."""
    try:
        from backend.learning.reflex import AuroraReflex
        from ml.training_orchestrator import train_all_models

        logger.info("Full learning run triggered via API")

        reflex_report: Any = await AuroraReflex().run(dry_run=False)

        # Training is async
        training_result: dict[str, Any] = await train_all_models(training_type="manual")

        return {
            "status": "success",
            "reflex_report": reflex_report,
            "training_result": training_result,
            "message": "Full learning run completed ",
        }
    except Exception as e:
        logger.exception("Failed to run full learning cycle")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/changes",
    summary="Get Learning Changes",
    description="Return recent learning configuration changes.",
)
async def learning_changes(limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    """Return recent learning configuration changes using Async SQLAlchemy."""
    try:
        engine = _get_learning_engine()
        store: LearningStore = engine.store

        async with store.AsyncSession() as session:
            stmt = select(ConfigVersion).order_by(desc(ConfigVersion.created_at)).limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            changes: list[dict[str, Any]] = []
            for change in rows:
                changes.append(
                    {
                        "id": change.id,
                        "created_at": change.created_at.isoformat() if change.created_at else None,
                        "reason": change.reason,
                        "applied": change.applied,
                        "metrics": json.loads(change.metrics_json) if change.metrics_json else None,
                    }
                )
            return {"changes": changes}
    except Exception as e:
        logger.warning(f"Failed to get learning changes: {e}")
        return {"changes": [], "message": f"Learning changes unavailable: {e!s}"}


@router.post(
    "/api/learning/record_observation",
    summary="Record Observation",
    description="Trigger observation recording from current system state.",
)
async def record_observation() -> dict[str, str]:
    """Trigger observation recording from current system state."""
    try:
        from backend.recorder import record_observation_from_current_state

        # record_observation_from_current_state is now async
        await record_observation_from_current_state()
        return {"status": "success", "message": "Observation recorded"}
    except Exception as e:
        logger.exception("Failed to record observation")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/training-status",
    summary="Get Training Status",
    description="Get current ML training status and model details.",
)
async def learning_training_status() -> dict[str, Any]:
    """Get current ML training status."""
    try:
        import time
        from pathlib import Path

        from ml.api import get_engine
        from ml.forward import determine_graduation_level
        from ml.training_orchestrator import get_training_status

        LOCK_FILE = Path("data/ml/models/.training.lock")

        def _is_lock_stale() -> bool:
            """Check if training lock is stale (older than 1 hour)."""
            if not LOCK_FILE.exists():
                return False
            return time.time() - LOCK_FILE.stat().st_mtime > 3600

        status: dict[str, Any] = await asyncio.to_thread(get_training_status)

        # ARC11 Fix: Explicitly add lock status structure
        # Even if get_training_status has it, we ensure it matches the requested format
        status["lock_status"] = {
            "locked": LOCK_FILE.exists(),
            "stale": _is_lock_stale() if LOCK_FILE.exists() else False,
            "lock_age_seconds": time.time() - LOCK_FILE.stat().st_mtime
            if LOCK_FILE.exists()
            else None,
        }

        # Add graduation level
        try:
            # We recreate engine here to fetch fresh stats
            # In a long running process `get_learning_engine` is cached lru,
            # but determine_graduation_level queries DB directly so it's fine.
            engine = get_engine()
            level, label, days = determine_graduation_level(engine)
            status["graduation_level"] = {
                "level": level,
                "label": label,
                "days_of_data": days,
            }
        except Exception as e:
            logger.warning(f"Failed to determine graduation level: {e}")
            status["graduation_level"] = {
                "level": 0,
                "label": "unknown",
                "days_of_data": 0,
            }

        return status
    except Exception as e:
        logger.exception("Failed to get training status")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/training-history",
    summary="Get Training History",
    description="Get recent ML training attempts.",
)
async def learning_training_history(limit: int = Query(5, ge=1, le=20)) -> dict[str, Any]:
    """Get recent ML training attempts (specialized view of learning history)."""
    # Reuse learning_history logic but filter/format specifically for training view if needed
    # For now, it's a wrapper with a smaller default limit
    return await learning_history(limit=limit)
