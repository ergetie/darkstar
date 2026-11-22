import asyncio
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

import pytz
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select

from backend.core.secrets import load_yaml
from backend.learning import learned_parameters as lp
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
    description="Trigger a full model training run.",
)
async def learning_run() -> dict[str, Any]:
    """Trigger a full learning run (model training)."""
    try:
        from ml.training_orchestrator import train_all_models

        logger.info("Full learning run triggered via API")

        training_result: dict[str, Any] = await train_all_models(training_type="manual")

        return {
            "status": "success",
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


# --- Learned battery and inverter parameters ---------------------------------------------


class LockBody(BaseModel):
    value: float


def _parameter_store() -> lp.LearnedParameterStore:
    return lp.LearnedParameterStore(_get_learning_engine().store)


def _config() -> dict[str, Any]:
    try:
        return load_yaml("config.yaml") or {}
    except Exception:
        logger.warning("Could not read config.yaml for learned parameters", exc_info=True)
        return {}


def _now(config: dict[str, Any]) -> datetime:
    return datetime.now(pytz.timezone(str(config.get("timezone", "Europe/Stockholm"))))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _require_key(key: str) -> lp.ParameterSpec:
    spec = lp.PARAMETERS.get(key)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown learned parameter: {key}")
    return spec


def _parameter_json(resolved: lp.ResolvedParameter) -> dict[str, Any]:
    spec = lp.PARAMETERS[resolved.key]
    return {
        "key": resolved.key,
        "label": spec.label,
        "unit": spec.unit,
        "learnable": spec.learnable,
        "effective_value": resolved.value,
        "source": resolved.source,
        "learned_value": resolved.learned_value,
        "applied_value": resolved.value if resolved.source == lp.SOURCE_LEARNED else None,
        "confidence": resolved.confidence,
        "evidence": resolved.evidence,
        "status_note": resolved.status_note,
        "estimated_at": _iso(resolved.estimated_at),
        "expires_at": _iso(resolved.expires_at),
        "applied_at": _iso(resolved.applied_at),
        "bounds": {"min": resolved.bounds[0], "max": resolved.bounds[1]},
        "config_fallback": resolved.config_fallback,
        "locked": resolved.locked,
        "locked_value": resolved.locked_value,
    }


async def _parameters_payload(config: dict[str, Any], now: datetime) -> dict[str, Any]:
    states = await _parameter_store().get_states()
    resolved = lp.resolve_battery_parameters(config, states, now)
    return {
        "parameters": [_parameter_json(resolved.parameters[key]) for key in lp.PARAMETERS],
        "effective": {
            "charge_efficiency": resolved.charge_efficiency,
            "discharge_efficiency": resolved.discharge_efficiency,
            "basis": "learned" if resolved.learned else "config",
            "missing": resolved.missing,
            "config_charge_efficiency": resolved.config_charge_efficiency,
            "config_discharge_efficiency": resolved.config_discharge_efficiency,
        },
    }


@router.get(
    "/api/learning/parameters",
    summary="Get Learned Parameters",
    description="Effective value, source, learned value, evidence and lock state of each parameter.",
)
async def learning_parameters() -> dict[str, Any]:
    config = _config()
    try:
        return await _parameters_payload(config, _now(config))
    except Exception as e:
        logger.exception("Failed to read learned parameters")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/api/learning/parameters/history",
    summary="Get Learned Parameter History",
    description="Recent applied changes, expiries, recoveries and lock changes.",
)
async def learning_parameter_history(
    limit: int = Query(50, ge=1, le=200), key: str | None = None
) -> dict[str, Any]:
    if key is not None:
        _require_key(key)
    try:
        rows = await _parameter_store().list_history(limit=limit, key=key)
    except Exception as e:
        logger.exception("Failed to read learned parameter history")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "history": [
            {
                "id": row.id,
                "key": row.key,
                "at": _iso(row.at),
                "event": row.event,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "confidence": row.confidence,
                "evidence": row.evidence,
                "notify_state": row.notify_state,
            }
            for row in rows
        ]
    }


@router.put(
    "/api/learning/parameters/{key}/lock",
    summary="Lock Learned Parameter",
    description="Lock a parameter to a user value inside its physical bounds.",
)
async def learning_parameter_lock(key: str, body: LockBody) -> dict[str, Any]:
    _require_key(key)
    config = _config()
    now = _now(config)
    try:
        await _parameter_store().set_lock(key, body.value, now)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to lock learned parameter")
        raise HTTPException(status_code=500, detail=str(e)) from e
    payload = await _parameters_payload(config, now)
    return next(item for item in payload["parameters"] if item["key"] == key)


@router.delete(
    "/api/learning/parameters/{key}/lock",
    summary="Unlock Learned Parameter",
    description="Remove the user lock; the learned value (if valid) or the config applies.",
)
async def learning_parameter_unlock(key: str) -> dict[str, Any]:
    _require_key(key)
    config = _config()
    now = _now(config)
    try:
        await _parameter_store().clear_lock(key, now)
    except Exception as e:
        logger.exception("Failed to unlock learned parameter")
        raise HTTPException(status_code=500, detail=str(e)) from e
    payload = await _parameters_payload(config, now)
    return next(item for item in payload["parameters"] if item["key"] == key)


@router.post(
    "/api/learning/parameters/recompute",
    summary="Recompute Learned Parameters",
    description="Run the daily estimation once and list the changes it applied.",
)
async def learning_parameters_recompute() -> dict[str, Any]:
    from backend.services.learned_parameters_service import learned_parameters_service

    try:
        changes = await learned_parameters_service.run_once(_get_learning_engine().store)
    except Exception as e:
        logger.exception("Learned parameter recompute failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {
        "changes": [
            {
                "key": c.key,
                "event": c.event,
                "old_value": c.old_value,
                "new_value": c.new_value,
                "confidence": c.confidence,
            }
            for c in changes
        ]
    }
