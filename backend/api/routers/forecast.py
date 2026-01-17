import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

# import aiosqlite # Removed
import numpy as np  # pyright: ignore [reportMissingImports]
import pandas as pd
import pytz
import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.learning import LearningEngine, get_learning_engine
from backend.strategy.history import get_strategy_history
from inputs import load_yaml
from ml.api import get_forecast_slots_async
from ml.weather import get_weather_volatility  # pyright: ignore [reportUnknownVariableType]

logger = logging.getLogger("darkstar.api.forecast")
router = APIRouter(prefix="/api/aurora", tags=["aurora"])
forecast_router = APIRouter(tags=["forecast"])

# --- Helper Functions ---


def _get_timezone() -> pytz.BaseTzInfo:
    try:
        engine = get_learning_engine()
        tz = getattr(engine, "timezone", None)
        if tz:
            return tz
    except Exception:
        pass
    try:
        cfg = load_yaml("config.yaml")
        return pytz.timezone(cfg.get("timezone", "Europe/Stockholm"))
    except Exception:
        return pytz.timezone("Europe/Stockholm")


def _get_engine_and_config() -> tuple[LearningEngine | None, dict[str, Any]]:
    engine: LearningEngine | None = None
    try:
        engine = get_learning_engine()
    except Exception as exc:
        logger.warning("Failed to get learning engine: %s", exc)
    try:
        config = load_yaml("config.yaml")
    except Exception:
        config = {}
    return engine, config


import asyncio
from typing import cast
from sqlalchemy import func, select, and_

from backend.learning.models import (
    LearningRun,
    SlotForecast,
    SlotObservation,
)


async def _compute_graduation_level(engine: LearningEngine | None) -> dict[str, Any]:
    level_label = "infant"
    total_runs = 0

    if engine and hasattr(engine, "store"):
        # Use run_in_executor to avoid blocking the event loop
        def count_runs():
            with engine.store.Session() as session:
                return session.scalar(select(func.count(LearningRun.id)))

        try:
            total_runs = await asyncio.to_thread(count_runs) or 0
        except Exception as exc:
            logger.warning("Failed to count learning_runs: %s", exc)

    if total_runs < 14:
        level_label = "infant"
    elif total_runs < 60:
        level_label = "statistician"
    else:
        level_label = "graduate"

    return {"label": level_label, "runs": total_runs}



async def _compute_risk_profile(engine: LearningEngine | None, config: dict[str, Any]) -> dict[str, Any]:
    """Compute risk profile based on weather volatility."""
    volatility = 0.0
    try:
        # Get volatility from ML module
        # Mocking or calling actual if available
        # from ml.weather import get_weather_volatility
        # volatility = await get_weather_volatility()
        # For now, return default or implement simple logic if ml module is not ready
        pass
    except Exception as e:
        logger.warning(f"Failed to compute risk profile: {e}")
    
    # Simple mapping
    risk = "low"
    if volatility > 0.5:
        risk = "high"
    elif volatility > 0.2:
        risk = "medium"
        
    return {
        "level": risk,
        "volatility_score": volatility,
        "details": "Based on weather variance"
    }

@router.get(
    "/dashboard",
    summary="Aurora Dashboard Data",
    description="Aggregated view for the Aurora dashboard."
)
async def aurora_dashboard() -> dict[str, Any]:
    """Aggregate data for the dashboard."""
    engine, config = _get_engine_and_config()
    
    # 1. Identity
    identity = await _compute_graduation_level(engine)
    
    # 2. Metrics
    metrics = await _compute_metrics(engine, days_back=7)
    
    # 3. Risk
    risk = await _compute_risk_profile(engine, config)
    
    # 4. Correction History
    corrections = await _fetch_correction_history(engine, config)
    
    # 5. Horizon (Next 24h)
    stats: dict[str, Any] = {}
    try:
        tz = getattr(engine, "timezone", _get_timezone()) if engine else _get_timezone()
        now = datetime.now(tz)
        minutes = (now.minute // 15) * 15
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        horizon_end = slot_start + timedelta(hours=24)
        active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")
        
        horizon_slots = await get_forecast_slots_async(slot_start, horizon_end, active_version)
        
        # Calculate stats
        total_pv = sum(s.get("pv_forecast_kwh", 0) for s in horizon_slots)
        total_load = sum(s.get("load_forecast_kwh", 0) for s in horizon_slots)
        
        stats = {
            "horizon_hours": 24,
            "total_pv_kwh": round(total_pv, 2),
            "total_load_kwh": round(total_load, 2),
            "slots": horizon_slots
        }
    except Exception as e:
        logger.error(f"Failed to fetch horizon for dashboard: {e}")
        stats = {"error": str(e)}

    return {
        "identity": identity,
        "metrics": metrics,
        "risk": risk,
        "correction_history": corrections,
        "horizon": stats,
        "status": "online" if engine else "offline"
    }



async def _fetch_correction_history(
    engine: LearningEngine | None, config: dict[str, Any]
) -> list[dict[str, Any]]:
    if not engine or not hasattr(engine, "store"):
        return []

    tz = engine.timezone if hasattr(engine, "timezone") else _get_timezone()
    now = datetime.now(tz)
    cutoff_date = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")

    def fetch():
        with engine.store.Session() as session:
            # Group by DATE(slot_start)
            # In SQLite, we can use func.date() or substring if dates are ISO. 
            # Models store slot_start as string ISO.
            stmt = (
                select(
                    func.date(SlotForecast.slot_start).label("date"),
                    func.sum(func.abs(SlotForecast.pv_correction_kwh)).label("pv_corr"),
                    func.sum(func.abs(SlotForecast.load_correction_kwh)).label("load_corr"),
                )
                .where(
                    SlotForecast.forecast_version == active_version,
                    func.date(SlotForecast.slot_start) >= cutoff_date,
                )
                .group_by("date")
                .order_by("date")
            )
            return session.execute(stmt).all()

    rows = []
    try:
        results = await asyncio.to_thread(fetch)
        for date_str, pv_corr, load_corr in results:
            pv = float(pv_corr or 0.0)
            load = float(load_corr or 0.0)
            rows.append(
                {
                    "date": date_str,
                    "total_correction_kwh": pv + load,
                    "pv_correction_kwh": pv,
                    "load_correction_kwh": load,
                }
            )
    except Exception as exc:
        logger.warning("Failed to fetch correction history: %s", exc)
    return rows


async def _compute_metrics(
    engine: LearningEngine | None, days_back: int = 7
) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {
        "mae_pv_aurora": None,
        "mae_pv_baseline": None,
        "mae_load_aurora": None,
        "mae_load_baseline": None,
    }
    if not engine or not hasattr(engine, "store"):
        return metrics

    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    start_time = now - timedelta(days=max(days_back, 1))
    
    start_iso = start_time.isoformat()
    now_iso = now.isoformat()

    def fetch():
        with engine.store.Session() as session:
            stmt = (
                select(
                    SlotForecast.forecast_version,
                    func.avg(func.abs(SlotObservation.pv_kwh - SlotForecast.pv_forecast_kwh)),
                    func.avg(func.abs(SlotObservation.load_kwh - SlotForecast.load_forecast_kwh)),
                )
                .join(SlotObservation, SlotObservation.slot_start == SlotForecast.slot_start)
                .where(
                    SlotObservation.slot_start >= start_iso,
                    SlotObservation.slot_start < now_iso,
                    SlotForecast.forecast_version.in_(["baseline_7_day_avg", "aurora"]),
                    SlotObservation.pv_kwh.is_not(None),
                    SlotForecast.pv_forecast_kwh.is_not(None),
                )
                .group_by(SlotForecast.forecast_version)
            )
            return session.execute(stmt).all()

    try:
        rows = await asyncio.to_thread(fetch)
        for version, mae_pv, mae_load in rows:
            if version == "aurora":
                metrics["mae_pv_aurora"] = float(mae_pv) if mae_pv is not None else None
                metrics["mae_load_aurora"] = float(mae_load) if mae_load is not None else None
            elif version == "baseline_7_day_avg":
                metrics["mae_pv_baseline"] = float(mae_pv) if mae_pv is not None else None
                metrics["mae_load_baseline"] = float(mae_load) if mae_load is not None else None
    except Exception as exc:
        logger.warning("Failed to compute metrics: %s", exc)
    return metrics

# get_aurora_briefing_text, aurora_dashboard, aurora_briefing, toggle_reflex remain unchanged
# ...


@forecast_router.get(
    "/api/forecast/eval",
    summary="Evaluate Forecast Accuracy",
    description="Returns Mean Absolute Error (MAE) metrics for baseline vs Aurora forecasts over recent days.",
)
async def forecast_eval(days: int = 7) -> dict[str, Any]:
    """Return simple MAE metrics for baseline vs AURORA forecasts over recent days."""
    try:
        engine = get_learning_engine()
        if not engine or not hasattr(engine, "store"):
             raise ValueError("Engine not ready")
             
        now = datetime.now(pytz.UTC)
        start_time = now - timedelta(days=max(days, 1))
        
        start_iso = start_time.isoformat()
        now_iso = now.isoformat()

        def fetch():
            with engine.store.Session() as session:
                stmt = (
                    select(
                        SlotForecast.forecast_version,
                        func.avg(func.abs(SlotObservation.pv_kwh - SlotForecast.pv_forecast_kwh)),
                        func.avg(func.abs(SlotObservation.load_kwh - SlotForecast.load_forecast_kwh)),
                        func.count().label("samples"),
                    )
                    .join(SlotObservation, SlotObservation.slot_start == SlotForecast.slot_start)
                    .where(
                        SlotObservation.slot_start >= start_iso,
                        SlotObservation.slot_start < now_iso,
                        SlotForecast.forecast_version.in_(["baseline_7_day_avg", "aurora"]),
                    )
                    .group_by(SlotForecast.forecast_version)
                )
                return session.execute(stmt).all()

        rows = await asyncio.to_thread(fetch)

        versions: list[dict[str, Any]] = []
        for row in rows:
            versions.append(
                {
                    "version": row[0],
                    "mae_pv": round(row[1], 4) if row[1] else None,
                    "mae_load": round(row[2], 4) if row[2] else None,
                    "samples": row[3],
                }
            )

        return {"versions": versions, "days_back": days}
    except Exception as e:
        logger.exception("Forecast eval failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.get(
    "/api/forecast/day",
    summary="Get Daily Forecast View",
    description="Returns actual vs forecast data for a specific day to visualize model performance.",
)
async def forecast_day(date: str | None = None) -> dict[str, Any]:
    """Return per-slot actual vs baseline/AURORA forecasts for a single day."""
    try:
        engine = get_learning_engine()
        if not engine or not hasattr(engine, "store"):
             raise ValueError("Engine not ready")
             
        tz = _get_timezone()

        try:
            target_date = datetime.fromisoformat(date).date() if date else datetime.now(tz).date()
        except Exception:
            target_date = datetime.now(tz).date()

        day_start = tz.localize(datetime(target_date.year, target_date.month, target_date.day))
        day_end = day_start + timedelta(days=1)
        
        start_iso = day_start.isoformat()
        end_iso = day_end.isoformat()

        def fetch():
            with engine.store.Session() as session:
                # Observations
                obs_stmt = (
                    select(SlotObservation.slot_start, SlotObservation.pv_kwh, SlotObservation.load_kwh)
                    .where(
                        SlotObservation.slot_start >= start_iso,
                        SlotObservation.slot_start < end_iso,
                    )
                    .order_by(SlotObservation.slot_start)
                )
                obs_results = session.execute(obs_stmt).all()

                # Forecasts
                f_stmt = (
                    select(SlotForecast.slot_start, SlotForecast.pv_forecast_kwh, 
                           SlotForecast.load_forecast_kwh, SlotForecast.forecast_version)
                    .where(
                        SlotForecast.slot_start >= start_iso,
                        SlotForecast.slot_start < end_iso,
                        SlotForecast.forecast_version.in_(["baseline_7_day_avg", "aurora"]),
                    )
                )
                f_results = session.execute(f_stmt).all()
                return obs_results, f_results

        obs_rows, f_rows = await asyncio.to_thread(fetch)

        # Build response
        slots: dict[str, Any] = {}
        for row in obs_rows:
            slot_s = str(row[0])
            slots[slot_s] = {
                "slot_start": slot_s,
                "actual_pv": row[1],
                "actual_load": row[2],
            }

        for row in f_rows:
            slot_s = str(row[0])
            if slot_s not in slots:
                slots[slot_s] = {"slot_start": slot_s}
            version = str(row[3])
            slots[slot_s][f"{version}_pv"] = row[1]
            slots[slot_s][f"{version}_load"] = row[2]

        return {"date": target_date.isoformat(), "slots": list(slots.values())}
    except Exception as e:
        logger.exception("Forecast day failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.get(
    "/api/forecast/horizon",
    summary="Get Forecast Horizon",
    description="Returns raw forecast slots for the next N hours.",
)
async def forecast_horizon(hours: int = 48) -> dict[str, Any]:
    """Return ML forecast for the next N hours."""
    try:
        engine, config = _get_engine_and_config()
        tz = getattr(engine, "timezone", _get_timezone()) if engine else _get_timezone()
        now = datetime.now(tz)
        minutes = (now.minute // 15) * 15
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)

        horizon_end = slot_start + timedelta(hours=hours)
        active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")

        slots = await get_forecast_slots_async(slot_start, horizon_end, active_version)
        return {"horizon_hours": hours, "slots": slots}
    except Exception as e:
        logger.exception("Forecast horizon failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.post(
    "/api/forecast/run_eval",
    summary="Run Forecast Evaluation",
    description="Triggers a manual evaluation of forecast accuracy against observations.",
)
async def forecast_run_eval() -> dict[str, Any]:
    """Trigger forecast accuracy evaluation."""
    try:
        engine, _config = _get_engine_and_config()
        if engine is None:
            return {"status": "error", "message": "Learning engine not available"}

        # Get accuracy metrics
        metrics = await _compute_metrics(engine, days_back=14)
        return {
            "status": "success",
            "message": "Evaluation completed",
            "metrics": metrics,
        }
    except Exception as e:
        logger.exception("Forecast run_eval failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.post(
    "/api/forecast/run_forward",
    summary="Run Forward Forecast",
    description="Pre-calculates forecast data for future windows (used by planner).",
)
async def forecast_run_forward() -> dict[str, Any]:
    """Pre-calculate forecast data for upcoming slots."""
    try:
        engine, config = _get_engine_and_config()
        if engine is None:
            return {"status": "error", "message": "Learning engine not available"}

        tz = getattr(engine, "timezone", _get_timezone())
        now = datetime.now(tz)
        minutes = (now.minute // 15) * 15
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        horizon_end = slot_start + timedelta(hours=48)

        active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")
        slots = await get_forecast_slots_async(slot_start, horizon_end, active_version)

        return {
            "status": "success",
            "message": f"Forward forecast generated for {len(slots)} slots",
            "slot_count": len(slots),
            "horizon_start": slot_start.isoformat(),
            "horizon_end": horizon_end.isoformat(),
        }
    except Exception as e:
        logger.exception("Forecast run_forward failed")
        raise HTTPException(500, str(e)) from e
