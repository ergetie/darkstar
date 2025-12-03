from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytz
import requests
from flask import Blueprint, jsonify, request

from inputs import _load_yaml
from backend.learning import get_learning_engine
from ml.api import get_forecast_slots
from ml.weather import get_weather_volatility

logger = logging.getLogger("darkstar.aurora")

aurora_bp = Blueprint("aurora", __name__, url_prefix="/api/aurora")


def _get_timezone() -> pytz.BaseTzInfo:
    """
    Resolve the planner timezone from the learning engine or config.
    """
    try:
        engine = get_learning_engine()
        tz = getattr(engine, "timezone", None)
        if tz is not None:
            return tz
    except Exception:
        pass

    try:
        config = _load_yaml("config.yaml")
        tz_name = config.get("timezone", "Europe/Stockholm")
    except Exception:
        tz_name = "Europe/Stockholm"
    return pytz.timezone(tz_name)


def _get_engine_and_config() -> tuple[Any, Dict[str, Any]]:
    """
    Helper to get learning engine and config with safe fallbacks.
    """
    engine = None
    try:
        engine = get_learning_engine()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to get learning engine: %s", exc)

    try:
        config = _load_yaml("config.yaml")
    except Exception:
        config = {}

    return engine, config


def _compute_graduation_level(engine: Any) -> Dict[str, Any]:
    """
    Compute graduation level from learning_runs count.
    """
    level_label = "infant"
    total_runs = 0
    db_path = getattr(engine, "db_path", None) if engine is not None else None

    if db_path and os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path, timeout=30.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM learning_runs")
                row = cursor.fetchone()
                if row:
                    total_runs = int(row[0] or 0)
        except sqlite3.Error as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to count learning_runs: %s", exc)

    if total_runs < 14:
        level_label = "infant"
    elif total_runs < 60:
        level_label = "statistician"
    else:
        level_label = "graduate"

    return {
        "label": level_label,
        "runs": total_runs,
    }


def _compute_risk_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Derive human-readable risk persona from s_index configuration.
    """
    s_cfg = config.get("s_index") or {}
    base_factor_raw = s_cfg.get("base_factor", 1.0)

    try:
        base_factor = float(base_factor_raw)
    except (TypeError, ValueError):
        base_factor = 1.0

    if base_factor < 1.0:
        persona = "Gambler"
    elif base_factor > 1.2:
        persona = "Paranoid"
    else:
        persona = "Balanced"

    return {
        "persona": persona,
        "base_factor": base_factor,
        "mode": s_cfg.get("mode", "static"),
        "max_factor": s_cfg.get("max_factor"),
        "static_factor": s_cfg.get("static_factor"),
        "raw": s_cfg,
    }


def _fetch_weather_volatility(
    start_time: datetime,
    end_time: datetime,
    config: Dict[str, Any],
) -> Dict[str, float]:
    """
    Wrap get_weather_volatility with safe fallbacks.
    """
    try:
        vol = get_weather_volatility(start_time, end_time, config=config)
        cloud = float(vol.get("cloud_volatility", 0.0))
        temp = float(vol.get("temp_volatility", 0.0))
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to compute weather volatility: %s", exc)
        cloud = 0.0
        temp = 0.0

    overall = max(cloud, temp)
    return {
        "cloud_volatility": cloud,
        "temp_volatility": temp,
        "overall": overall,
    }


def _fetch_horizon_series(
    engine: Any, config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Fetch aligned 48h horizon series of base, correction, and final forecasts.
    """
    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)

    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)
    horizon_end = slot_start + timedelta(hours=48)

    forecasting_cfg = config.get("forecasting") or {}
    active_version = forecasting_cfg.get("active_forecast_version", "aurora")

    slots: List[Dict[str, Any]] = []
    try:
        records = get_forecast_slots(slot_start, horizon_end, active_version)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to fetch forecast slots: %s", exc)
        records = []

    for rec in records:
        ts = rec.get("slot_start")
        if hasattr(ts, "isoformat"):
            ts_iso = ts.isoformat()
        else:
            ts_iso = str(ts)

        # Planner stores base forecast with corrections already applied in the DB;
        # for this dashboard we consider:
        #   final = stored forecast (pv/load)
        #   base = final - correction
        pv_corr = float(rec.get("pv_correction_kwh", 0.0) or 0.0)
        load_corr = float(rec.get("load_correction_kwh", 0.0) or 0.0)

        final_pv = float(rec.get("pv_forecast_kwh", 0.0) or 0.0)
        final_load = float(rec.get("load_forecast_kwh", 0.0) or 0.0)

        base_pv = final_pv - pv_corr
        base_load = final_load - load_corr

        slots.append(
            {
                "slot_start": ts_iso,
                "base": {"pv_kwh": base_pv, "load_kwh": base_load},
                "correction": {"pv_kwh": pv_corr, "load_kwh": load_corr},
                "final": {"pv_kwh": final_pv, "load_kwh": final_load},
            }
        )

    return {
        "start": slot_start.isoformat(),
        "end": horizon_end.isoformat(),
        "forecast_version": active_version,
        "slots": slots,
    }


def _fetch_correction_history(engine: Any, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return last 14 days of total correction volume per day.
    """
    db_path = getattr(engine, "db_path", None)
    if not db_path or not os.path.exists(db_path):
        return []

    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    cutoff_date = (now - timedelta(days=14)).date().isoformat()

    forecasting_cfg = config.get("forecasting") or {}
    active_version = forecasting_cfg.get("active_forecast_version", "aurora")

    rows: List[Dict[str, Any]] = []
    try:
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    DATE(slot_start) AS date,
                    SUM(ABS(pv_correction_kwh)) AS pv_corr,
                    SUM(ABS(load_correction_kwh)) AS load_corr
                FROM slot_forecasts
                WHERE forecast_version = ?
                  AND DATE(slot_start) >= ?
                GROUP BY DATE(slot_start)
                ORDER BY date ASC
                """,
                (active_version, cutoff_date),
            )
            for date_str, pv_corr, load_corr in cursor.fetchall():
                pv_total = float(pv_corr or 0.0)
                load_total = float(load_corr or 0.0)
                rows.append(
                    {
                        "date": date_str,
                        "total_correction_kwh": pv_total + load_total,
                        "pv_correction_kwh": pv_total,
                        "load_correction_kwh": load_total,
                    }
                )
    except sqlite3.Error as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to fetch correction history: %s", exc)

    return rows


def _compute_metrics(engine: Any, days_back: int = 7) -> Dict[str, float | None]:
    """
    Compute simple MAE metrics for baseline vs AURORA over recent days.
    """
    db_path = getattr(engine, "db_path", None) if engine is not None else None
    if not db_path or not os.path.exists(db_path):
        return {
            "mae_pv_aurora": None,
            "mae_pv_baseline": None,
            "mae_load_aurora": None,
            "mae_load_baseline": None,
        }

    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    start_time = now - timedelta(days=max(days_back, 1))

    metrics: Dict[str, float | None] = {
        "mae_pv_aurora": None,
        "mae_pv_baseline": None,
        "mae_load_aurora": None,
        "mae_load_baseline": None,
    }

    try:
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT
                    f.forecast_version,
                    AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)) AS mae_pv,
                    AVG(ABS(o.load_kwh - f.load_forecast_kwh)) AS mae_load
                FROM slot_observations o
                JOIN slot_forecasts f
                  ON o.slot_start = f.slot_start
                WHERE o.slot_start >= ? AND o.slot_start < ?
                  AND f.forecast_version IN ('baseline_7_day_avg', 'aurora')
                  AND o.pv_kwh IS NOT NULL AND f.pv_forecast_kwh IS NOT NULL
                  AND o.load_kwh IS NOT NULL AND f.load_forecast_kwh IS NOT NULL
                GROUP BY f.forecast_version
                """,
                (start_time.isoformat(), now.isoformat()),
            ).fetchall()
    except sqlite3.Error as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to compute Aurora metrics: %s", exc)
        return metrics

    for version, mae_pv, mae_load in rows:
        if version == "aurora":
            metrics["mae_pv_aurora"] = None if mae_pv is None else float(mae_pv)
            metrics["mae_load_aurora"] = None if mae_load is None else float(mae_load)
        elif version == "baseline_7_day_avg":
            metrics["mae_pv_baseline"] = None if mae_pv is None else float(mae_pv)
            metrics["mae_load_baseline"] = None if mae_load is None else float(mae_load)

    return metrics


@aurora_bp.get("/dashboard")
def aurora_dashboard():
    """
    Aurora dashboard endpoint exposing identity, state, horizon, and history.
    """
    engine, config = _get_engine_and_config()

    tz = getattr(engine, "timezone", _get_timezone())

    graduation = _compute_graduation_level(engine)
    risk_profile = _compute_risk_profile(config)

    now = datetime.now(tz)
    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)
    horizon_end = slot_start + timedelta(hours=48)

    weather_volatility = _fetch_weather_volatility(slot_start, horizon_end, config)
    horizon = _fetch_horizon_series(engine, config)
    history = _fetch_correction_history(engine, config)
    metrics = _compute_metrics(engine)

    payload = {
        "identity": {
            "graduation": graduation,
        },
        "state": {
            "risk_profile": risk_profile,
            "weather_volatility": weather_volatility,
        },
        "horizon": horizon,
        "history": {
            "correction_volume_days": history,
        },
        "metrics": metrics,
        "generated_at": datetime.now(tz).isoformat(),
    }
    return jsonify(payload)


def get_aurora_briefing(
    dashboard: Dict[str, Any], config: Dict[str, Any], secrets: Dict[str, Any]
) -> str:
    """
    Generate a short Aurora status summary via OpenRouter.

    This is intentionally self-contained so the Aurora tab can function even
    if other strategy modules are unavailable.
    """
    advisor_cfg = config.get("advisor") or {}
    if not advisor_cfg.get("enable_llm", False):
        return "Aurora briefing is disabled in config."

    api_key = secrets.get("openrouter_api_key")
    if not api_key or "sk-" not in str(api_key):
        return "OpenRouter API Key missing or invalid in secrets.yaml."

    model = advisor_cfg.get("model", "google/gemini-flash-1.5")

    system_prompt = (
        "You are Aurora, an intelligent energy agent managing a home. "
        "You receive a JSON dashboard describing your learning progress, "
        "risk profile, forecast corrections, and weather volatility. "
        "Summarize your current status and risk level in 2 sentences."
    )

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/darkstar",
            },
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(dashboard)},
                    ],
                }
            ),
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Aurora briefing request failed: %s", exc)
        return "Error generating Aurora briefing."

    if response.status_code != 200:
        logger.error("OpenRouter error %s: %s", response.status_code, response.text)
        return "Aurora could not reach the AI cloud for a briefing."

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to parse Aurora briefing response: %s", exc)
        return "Aurora briefing response could not be parsed."


@aurora_bp.post("/briefing")
def aurora_briefing():
    """
    Generate a daily Aurora briefing based on the dashboard JSON.
    """
    if not request.is_json:
        return jsonify({"error": "Expected JSON body"}), 400

    dashboard = request.get_json() or {}

    try:
        config = _load_yaml("config.yaml")
    except Exception:
        config = {}

    try:
        secrets = _load_yaml("secrets.yaml")
    except Exception:
        secrets = {}

    text = get_aurora_briefing(dashboard, config, secrets)
    return jsonify({"briefing": text})
