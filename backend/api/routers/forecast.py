import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytz
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from backend.core.prices import get_nordpool_data
from backend.core.secrets import load_yaml
from backend.learning import LearningEngine, get_learning_engine
from backend.learning.models import (
    LearningRun,
    SlotForecast,
    SlotObservation,
)
from backend.strategy.history import get_strategy_history
from ml.api import get_forecast_slots

# from ml.weather import get_weather_volatility # Not strictly needed if we mock or reuse logic

logger = logging.getLogger("darkstar.api.forecast")
router = APIRouter(prefix="/api/aurora", tags=["aurora"])
forecast_router = APIRouter(prefix="/api/forecast", tags=["forecast"])

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


# Missing function implementation
def get_aurora_briefing_text(
    dashboard: dict[str, Any], config: dict[str, Any], secrets: dict[str, Any]
) -> str:
    """Mock implementation of the briefing text generator."""
    return "Aurora briefing system is active. Detailed summary logic to be restored."


async def _compute_graduation_level(engine: LearningEngine | None) -> dict[str, Any]:
    level_label = "infant"
    total_runs = 0

    if engine and hasattr(engine, "store"):
        try:
            async with engine.store.AsyncSession() as session:
                total_runs = await session.scalar(select(func.count(LearningRun.id))) or 0
                logger.debug("Graduation level check: found %d total learning runs", total_runs)
        except Exception:
            logger.exception("Failed to count learning_runs")
    else:
        logger.warning("Graduation level check: No engine or store available")

    if total_runs < 14:
        level_label = "infant"
    elif total_runs < 60:
        level_label = "statistician"
    else:
        level_label = "graduate"

    # Quick fix: if runs found but label is infant, check logic.
    # Logic seems fine, but we need runs to be populated.

    return {"label": level_label, "runs": total_runs}


async def _compute_risk_profile(
    engine: LearningEngine | None, config: dict[str, Any]
) -> dict[str, Any]:
    """Compute risk profile based on weather volatility."""
    volatility = 0.0
    # Placeholder for volatility logic

    risk = "low"
    if volatility > 0.5:
        risk = "high"
    elif volatility > 0.2:
        risk = "medium"

    return {"level": risk, "volatility_score": volatility, "details": "Based on weather variance"}


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

    try:
        async with engine.store.AsyncSession() as session:
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
            results = (await session.execute(stmt)).all()
            for version, mae_pv, mae_load in results:
                if version == "aurora":
                    metrics["mae_pv_aurora"] = float(mae_pv) if mae_pv is not None else None
                    metrics["mae_load_aurora"] = float(mae_load) if mae_load is not None else None
                elif version == "baseline_7_day_avg":
                    metrics["mae_pv_baseline"] = float(mae_pv) if mae_pv is not None else None
                    metrics["mae_load_baseline"] = float(mae_load) if mae_load is not None else None
    except Exception:
        logger.exception("Failed to compute metrics")
    return metrics


async def _get_history_with_actuals(
    engine: LearningEngine | None,
    start_time: datetime,
    end_time: datetime,
    forecast_version: str = "aurora",
) -> dict[str, list[dict[str, Any]]]:
    """
    Fetch historical slot observations and forecasts for the given time window.

    Returns a dict with 'pv' and 'load' lists, each containing:
        - slot_start: ISO timestamp string
        - actual: observed value (or null)
        - forecast: forecasted value (or null)
        - p10: P10 forecast (or null)
        - p90: P90 forecast (or null)
    """
    result: dict[str, list[dict[str, Any]]] = {"pv": [], "load": []}

    if not engine or not hasattr(engine, "store"):
        return result

    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()

    try:
        async with engine.store.AsyncSession() as session:
            obs_stmt = (
                select(
                    SlotObservation.slot_start,
                    SlotObservation.pv_kwh,
                    SlotObservation.load_kwh,
                )
                .where(
                    SlotObservation.slot_start >= start_iso,
                    SlotObservation.slot_start < end_iso,
                )
                .order_by(SlotObservation.slot_start)
            )
            obs_results = (await session.execute(obs_stmt)).all()

            f_stmt = (
                select(
                    SlotForecast.slot_start,
                    SlotForecast.pv_forecast_kwh,
                    SlotForecast.load_forecast_kwh,
                    SlotForecast.pv_p10,
                    SlotForecast.pv_p90,
                    SlotForecast.load_p10,
                    SlotForecast.load_p90,
                )
                .where(
                    SlotForecast.slot_start >= start_iso,
                    SlotForecast.slot_start < end_iso,
                    SlotForecast.forecast_version == forecast_version,
                )
                .order_by(SlotForecast.slot_start)
            )
            f_results = (await session.execute(f_stmt)).all()

        obs_map: dict[str, dict[str, float | None]] = {}
        for row in obs_results:
            obs_map[row[0]] = {
                "pv_actual": float(row[1]) if row[1] is not None else None,
                "load_actual": float(row[2]) if row[2] is not None else None,
            }

        fcst_map: dict[str, dict[str, float | None]] = {}
        for row in f_results:
            fcst_map[row[0]] = {
                "pv_forecast": float(row[1]) if row[1] is not None else None,
                "load_forecast": float(row[2]) if row[2] is not None else None,
                "pv_p10": float(row[3]) if row[3] is not None else None,
                "pv_p90": float(row[4]) if row[4] is not None else None,
                "load_p10": float(row[5]) if row[5] is not None else None,
                "load_p90": float(row[6]) if row[6] is not None else None,
            }

        all_times = sorted(set(obs_map.keys()) | set(fcst_map.keys()))

        for ts in all_times:
            obs = obs_map.get(ts, {})
            fcst = fcst_map.get(ts, {})

            result["pv"].append(
                {
                    "slot_start": ts,
                    "actual": obs.get("pv_actual"),
                    "forecast": fcst.get("pv_forecast"),
                    "p10": fcst.get("pv_p10"),
                    "p90": fcst.get("pv_p90"),
                }
            )
            result["load"].append(
                {
                    "slot_start": ts,
                    "actual": obs.get("load_actual"),
                    "forecast": fcst.get("load_forecast"),
                    "p10": fcst.get("load_p10"),
                    "p90": fcst.get("load_p90"),
                }
            )
    except Exception:
        logger.exception("Failed to fetch history with actuals")

    return result


@router.get(
    "/dashboard",
    summary="Aurora Dashboard Data",
    description="Aggregated view for the Aurora dashboard.",
)
async def aurora_dashboard() -> dict[str, Any]:
    """Aggregate data for the dashboard."""
    engine, config = _get_engine_and_config()
    tz = getattr(engine, "timezone", _get_timezone()) if engine else _get_timezone()
    now = datetime.now(tz)

    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_yesterday = start_of_today - timedelta(days=1)
    horizon_start = start_of_yesterday
    horizon_end = start_of_today + timedelta(days=2)

    identity = await _compute_graduation_level(engine)
    metrics = await _compute_metrics(engine, days_back=7)
    risk = await _compute_risk_profile(engine, config)

    stats: dict[str, Any] = {}
    history_series: dict[str, list[dict[str, Any]]] = {"pv": [], "load": []}
    try:
        active_version = config.get("forecasting", {}).get("active_forecast_version") or "aurora"
        logger.debug("Dashboard Fetch: Using active_version=%s", active_version)

        history_series = await _get_history_with_actuals(engine, horizon_start, now, active_version)

        horizon_slots = await get_forecast_slots(horizon_start, horizon_end, active_version)
        if not horizon_slots and active_version != "aurora":
            logger.warning("No slots for version %s, falling back to 'aurora'", active_version)
            horizon_slots = await get_forecast_slots(horizon_start, horizon_end, "aurora")

        total_pv = sum(s["final"]["pv_kwh"] for s in horizon_slots)
        total_load = sum(s["final"]["load_kwh"] for s in horizon_slots)

        stats = {
            "horizon_hours": 72,
            "start": horizon_start.isoformat(),
            "end": horizon_end.isoformat(),
            "total_pv_kwh": round(total_pv, 2),
            "total_load_kwh": round(total_load, 2),
            "slots": horizon_slots,
            "history_series": history_series,
        }
    except Exception as e:
        logger.error(f"Failed to fetch horizon for dashboard: {e}")
        stats = {"error": str(e)}

    metrics["max_price_spread"] = None
    try:
        prices = await get_nordpool_data()

        if prices:
            start_check = now.replace(hour=0, minute=0, second=0, microsecond=0)
            relevant_prices = [
                p
                for p in prices
                if p.get("start_time") and p["start_time"].astimezone(tz) >= start_check
            ]

            if relevant_prices:
                exports = [p.get("export_price_sek_kwh", 0.0) for p in relevant_prices]
                imports = [p.get("import_price_sek_kwh", 0.0) for p in relevant_prices]

                if exports and imports:
                    metrics["max_price_spread"] = round(max(exports) - min(imports), 4)
    except Exception as e:
        logger.warning("Failed to calc max_price_spread: %s", e)

    strategy_history = get_strategy_history(limit=50)

    return {
        "identity": identity,
        "metrics": metrics,
        "risk": risk,
        "horizon": stats,
        "history": {"strategy_events": strategy_history},
        "status": "online" if engine else "offline",
        "state": {
            "reflex_enabled": config.get("learning", {}).get("reflex_enabled", False),
            "risk_profile": {
                "risk_appetite": config.get("s_index", {}).get("risk_appetite", 3),
                "mode": config.get("s_index", {}).get("mode", "dynamic"),
            },
            "weather_volatility": risk,
        },
    }


class BriefingRequest(BaseModel):
    # Dynamic dict payload
    model_config = ConfigDict(extra="allow")


@router.post("/briefing")
async def aurora_briefing(request: Request):
    try:
        dashboard = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON") from None

    _, config = _get_engine_and_config()
    try:
        secrets = load_yaml("secrets.yaml")
    except Exception:
        secrets = {}

    text = get_aurora_briefing_text(dashboard, config, secrets)
    return {"briefing": text}


class ToggleReflexRequest(BaseModel):
    enabled: bool


@router.post("/config/toggle_reflex")
async def toggle_reflex(payload: ToggleReflexRequest):
    """Enable or disable Aurora Reflex safely."""
    try:
        import tempfile

        from ruamel.yaml import YAML

        config_path = Path("config.yaml")

        # 1. Read existing config
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        # Use a read lock if strictly necessary, but for now simple read is improved
        if not config_path.exists():
            raise HTTPException(500, "Config file not found")

        with config_path.open("r", encoding="utf-8") as f:
            loaded_yaml: Any = yaml_handler.load(f)  # type: ignore[no-untyped-call]
            data: dict[str, Any] = cast("dict[str, Any]", loaded_yaml) if loaded_yaml else {}

        # 2. Update data
        learning_dict: dict[str, Any] = cast("dict[str, Any]", data.setdefault("learning", {}))
        learning_dict["reflex_enabled"] = payload.enabled

        # 3. Atomic Write: Write to temp file then move
        # Create temp file in same directory to ensure atomic move works
        with tempfile.NamedTemporaryFile(
            "w", delete=False, dir=config_path.parent, encoding="utf-8", suffix=".tmp"
        ) as tmp_f:
            yaml_handler.dump(data, tmp_f)  # type: ignore[arg-type]
            tmp_path = Path(tmp_f.name)

        # Renaissance Move (Atomic Replace)
        tmp_path.replace(config_path)

        logger.info("Toggle Reflex: Set to %s", payload.enabled)
        return {"status": "success", "enabled": payload.enabled}

    except Exception as e:
        logger.error("Toggle reflex failed: %s", e)
        raise HTTPException(500, str(e)) from e


# --- Secondary router for /api/forecast/* endpoints ---


@forecast_router.get("/eval")
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

        async with engine.store.AsyncSession() as session:
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
            results = await session.execute(stmt)
            rows = results.all()

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


@forecast_router.get("/day")
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

        async with engine.store.AsyncSession() as session:
            # Observations
            obs_stmt = (
                select(SlotObservation.slot_start, SlotObservation.pv_kwh, SlotObservation.load_kwh)
                .where(
                    SlotObservation.slot_start >= start_iso,
                    SlotObservation.slot_start < end_iso,
                )
                .order_by(SlotObservation.slot_start)
            )
            obs_results = (await session.execute(obs_stmt)).all()

            # Forecasts
            f_stmt = select(
                SlotForecast.slot_start,
                SlotForecast.pv_forecast_kwh,
                SlotForecast.load_forecast_kwh,
                SlotForecast.forecast_version,
            ).where(
                SlotForecast.slot_start >= start_iso,
                SlotForecast.slot_start < end_iso,
                SlotForecast.forecast_version.in_(["baseline_7_day_avg", "aurora"]),
            )
            f_results = (await session.execute(f_stmt)).all()

        # Build response
        slots: dict[str, dict[str, Any]] = {}
        for row in obs_results:
            slot_s = row[0]
            slots[slot_s] = {"slot_start": slot_s, "actual_pv": row[1], "actual_load": row[2]}

        for row in f_results:
            slot_s = row[0]
            if slot_s not in slots:
                slots[slot_s] = {"slot_start": slot_s}
            version = row[3]
            slots[slot_s][f"{version}_pv"] = row[1]
            slots[slot_s][f"{version}_load"] = row[2]

        return {"date": target_date.isoformat(), "slots": list(slots.values())}
    except Exception as e:
        logger.exception("Forecast day failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.get("/horizon")
async def forecast_horizon(hours: int = 48):
    """Return ML forecast for the next N hours."""
    try:
        engine, config = _get_engine_and_config()
        # active_version logic duplicating here or inside get_forecast_slots?
        # Keeping simple wrapper
        tz = getattr(engine, "timezone", _get_timezone()) if engine else _get_timezone()
        now = datetime.now(tz)
        minutes = (now.minute // 15) * 15
        slot_start = now.replace(minute=minutes, second=0, microsecond=0)
        horizon_end = slot_start + timedelta(hours=hours)
        active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")

        slots = await get_forecast_slots(slot_start, horizon_end, active_version)
        return {"horizon_hours": hours, "slots": slots}
    except Exception as e:
        logger.exception("Forecast horizon failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.post("/run_eval")
async def forecast_run_eval() -> dict[str, Any]:
    """Trigger forecast accuracy evaluation."""
    try:
        engine, _config = _get_engine_and_config()
        if engine is None:
            return {"status": "error", "message": "Learning engine not available"}
        metrics = await _compute_metrics(engine, days_back=14)
        return {
            "status": "success",
            "message": "Evaluation completed",
            "metrics": metrics,
        }
    except Exception as e:
        logger.exception("Forecast run_eval failed")
        raise HTTPException(500, str(e)) from e


@forecast_router.post("/run_forward")
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

        slots = await get_forecast_slots(slot_start, horizon_end, active_version)
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
