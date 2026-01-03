import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import pytz
import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.learning import get_learning_engine
from backend.strategy.history import get_strategy_history
from inputs import _load_yaml
from ml.api import get_forecast_slots
from ml.weather import get_weather_volatility

logger = logging.getLogger("darkstar.api.forecast")
router = APIRouter(prefix="/api/aurora", tags=["aurora"])

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
        cfg = _load_yaml("config.yaml")
        return pytz.timezone(cfg.get("timezone", "Europe/Stockholm"))
    except Exception:
        return pytz.timezone("Europe/Stockholm")


def _get_engine_and_config():
    engine = None
    try:
        engine = get_learning_engine()
    except Exception as exc:
        logger.warning("Failed to get learning engine: %s", exc)
    try:
        config = _load_yaml("config.yaml")
    except Exception:
        config = {}
    return engine, config


def _compute_graduation_level(engine: Any) -> dict[str, Any]:
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
        except sqlite3.Error as exc:
            logger.warning("Failed to count learning_runs: %s", exc)

    if total_runs < 14:
        level_label = "infant"
    elif total_runs < 60:
        level_label = "statistician"
    else:
        level_label = "graduate"

    return {"label": level_label, "runs": total_runs}


def _compute_risk_profile(config: dict[str, Any]) -> dict[str, Any]:
    s_cfg = config.get("s_index") or {}
    base_factor_raw = s_cfg.get("base_factor", 1.0)
    risk_appetite = int(s_cfg.get("risk_appetite", 3))

    try:
        base_factor = float(base_factor_raw)
    except (TypeError, ValueError):
        base_factor = 1.0

    if risk_appetite <= 1:
        persona = "Safety First"
    elif risk_appetite == 2:
        persona = "Conservative"
    elif risk_appetite == 3:
        persona = "Balanced"
    elif risk_appetite == 4:
        persona = "Aggressive"
    else:
        persona = "Gambler"

    current_factor = None
    raw_factor = None
    try:
        if os.path.exists("schedule.json"):
            with open("schedule.json") as f:
                schedule = json.load(f)
                meta = schedule.get("meta", {})
                s_index_meta = meta.get("s_index", {})
                current_factor = s_index_meta.get("effective_load_margin")
                if current_factor is None:
                    current_factor = s_index_meta.get("factor")
                raw_factor = s_index_meta.get("raw_factor")
                if raw_factor is None:
                    raw_factor = s_index_meta.get("factor_unclamped")
    except Exception as exc:
        logger.warning("Failed to load s-index from schedule.json: %s", exc)

    return {
        "persona": persona,
        "risk_appetite": risk_appetite,
        "base_factor": base_factor,
        "current_factor": float(current_factor) if current_factor is not None else None,
        "raw_factor": float(raw_factor) if raw_factor is not None else None,
        "mode": s_cfg.get("mode", "static"),
        "max_factor": s_cfg.get("max_factor"),
        "static_factor": s_cfg.get("static_factor"),
        "raw": s_cfg,
    }


def _fetch_weather_volatility(
    start_time: datetime, end_time: datetime, config: dict[str, Any]
) -> dict[str, float]:
    try:
        vol = get_weather_volatility(start_time, end_time, config=config)
        cloud = float(vol.get("cloud_volatility", 0.0))
        temp = float(vol.get("temp_volatility", 0.0))
    except Exception as exc:
        logger.warning("Failed to compute weather volatility: %s", exc)
        cloud = 0.0
        temp = 0.0
    return {"cloud_volatility": cloud, "temp_volatility": temp, "overall": max(cloud, temp)}


def _fetch_horizon_series(engine: Any, config: dict[str, Any]) -> dict[str, Any]:
    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    minutes = (now.minute // 15) * 15
    slot_start = now.replace(minute=minutes, second=0, microsecond=0)
    if slot_start < now:
        slot_start += timedelta(minutes=15)
    horizon_end = slot_start + timedelta(hours=48)

    forecasting_cfg = config.get("forecasting") or {}
    active_version = forecasting_cfg.get("active_forecast_version", "aurora")

    slots: list[dict[str, Any]] = []
    try:
        records = get_forecast_slots(slot_start, horizon_end, active_version)
    except Exception as exc:
        logger.warning("Failed to fetch forecast slots: %s", exc)
        records = []

    for rec in records:
        ts = rec.get("slot_start")
        ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

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
                "probabilistic": {
                    "pv_p10": float(rec.get("pv_p10")) if rec.get("pv_p10") is not None else None,
                    "pv_p90": float(rec.get("pv_p90")) if rec.get("pv_p90") is not None else None,
                    "load_p10": float(rec.get("load_p10"))
                    if rec.get("load_p10") is not None
                    else None,
                    "load_p90": float(rec.get("load_p90"))
                    if rec.get("load_p90") is not None
                    else None,
                },
            }
        )

    return {
        "start": slot_start.isoformat(),
        "end": horizon_end.isoformat(),
        "forecast_version": active_version,
        "slots": slots,
    }


def _fetch_correction_history(engine: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    db_path = getattr(engine, "db_path", None)
    if not db_path or not os.path.exists(db_path):
        return []

    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    cutoff_date = (now - timedelta(days=14)).date().isoformat()
    active_version = config.get("forecasting", {}).get("active_forecast_version", "aurora")

    rows = []
    try:
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DATE(slot_start) AS date, SUM(ABS(pv_correction_kwh)), SUM(ABS(load_correction_kwh))
                FROM slot_forecasts
                WHERE forecast_version = ? AND DATE(slot_start) >= ?
                GROUP BY DATE(slot_start) ORDER BY date ASC
            """,
                (active_version, cutoff_date),
            )
            for date_str, pv_corr, load_corr in cursor.fetchall():
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


def _compute_metrics(engine: Any, days_back: int = 7) -> dict[str, float | None]:
    db_path = getattr(engine, "db_path", None) if engine else None
    metrics = {
        "mae_pv_aurora": None,
        "mae_pv_baseline": None,
        "mae_load_aurora": None,
        "mae_load_baseline": None,
    }
    if not db_path or not os.path.exists(db_path):
        return metrics

    tz = getattr(engine, "timezone", _get_timezone())
    now = datetime.now(tz)
    start_time = now - timedelta(days=max(days_back, 1))

    try:
        with sqlite3.connect(db_path, timeout=30.0) as conn:
            rows = conn.execute(
                """
                SELECT f.forecast_version, AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)), AVG(ABS(o.load_kwh - f.load_forecast_kwh))
                FROM slot_observations o 
                JOIN slot_forecasts f ON o.slot_start = f.slot_start
                WHERE o.slot_start >= ? AND o.slot_start < ?
                  AND f.forecast_version IN ('baseline_7_day_avg', 'aurora')
                  AND o.pv_kwh IS NOT NULL AND f.pv_forecast_kwh IS NOT NULL
                GROUP BY f.forecast_version
            """,
                (start_time.isoformat(), now.isoformat()),
            ).fetchall()

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


def get_aurora_briefing_text(
    dashboard: dict[str, Any], config: dict[str, Any], secrets: dict[str, Any]
) -> str:
    advisor_cfg = config.get("advisor") or {}
    if not advisor_cfg.get("enable_llm", False):
        return "Aurora briefing is disabled in config."

    api_key = secrets.get("openrouter_api_key")
    if not api_key:
        return "OpenRouter API Key missing."

    model = advisor_cfg.get("model", "google/gemini-flash-1.5")
    system_prompt = (
        "You are Aurora, an intelligent energy agent. Summarize status and risk in 2 sentences."
    )

    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "https://github.com/darkstar",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(dashboard)},
                ],
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error("Briefing failed: %s", e)
    return "Aurora could not reach the AI cloud."


# --- Routes ---


@router.get("/dashboard")
async def aurora_dashboard():
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

    # History Series (Rev A29)
    try:
        if engine is not None and hasattr(engine, "store"):
            df_pv = engine.store.get_forecast_vs_actual(days_back=2, target="pv")
            df_load = engine.store.get_forecast_vs_actual(days_back=2, target="load")
            hist_start = (slot_start - timedelta(hours=24)).isoformat()

            def proc(df):
                if df.empty:
                    return []
                f = df[df["slot_start"] >= hist_start].copy()
                for c in ["p10", "p90", "forecast", "actual"]:
                    if c in f.columns:
                        f[c] = f[c].astype(object).where(pd.notnull(f[c]), None)
                return f[["slot_start", "actual", "p10", "p90", "forecast"]].to_dict("records")

            horizon["history_series"] = {"pv": proc(df_pv), "load": proc(df_load)}
    except Exception:
        horizon["history_series"] = {"pv": [], "load": []}

    history = _fetch_correction_history(engine, config)
    metrics = _compute_metrics(engine)
    strategy_history = get_strategy_history(limit=50)

    # Max Price Spread
    metrics["max_price_spread"] = None
    try:
        from inputs import get_nordpool_data

        prices = [
            p
            for p in get_nordpool_data()
            if p["start_time"] >= now.replace(hour=0, minute=0, second=0, microsecond=0)
        ]
        if prices:
            spread = max(p["export_price_sek_kwh"] for p in prices) - min(
                p["import_price_sek_kwh"] for p in prices
            )
            metrics["max_price_spread"] = round(spread, 4)
    except:
        pass

    # Forecast Bias
    metrics["forecast_bias"] = None
    try:
        if engine and hasattr(engine, "store"):
            df = engine.store.get_forecast_vs_actual(days_back=14, target="pv")
            if len(df) >= 50:
                metrics["forecast_bias"] = round(df["error"].mean(), 3)
    except:
        pass

    return {
        "identity": {"graduation": graduation},
        "state": {
            "risk_profile": risk_profile,
            "weather_volatility": weather_volatility,
            "auto_tune_enabled": bool(config.get("learning", {}).get("auto_tune_enabled", False)),
            "reflex_enabled": bool(config.get("learning", {}).get("reflex_enabled", False)),
        },
        "horizon": horizon,
        "history": {"correction_volume_days": history, "strategy_events": strategy_history},
        "metrics": metrics,
        "generated_at": datetime.now(tz).isoformat(),
    }


class BriefingRequest(BaseModel):
    # Dynamic dict payload
    pass


@router.post("/briefing")
async def aurora_briefing(request: Request):
    try:
        dashboard = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    _, config = _get_engine_and_config()
    try:
        secrets = _load_yaml("secrets.yaml")
    except Exception:
        secrets = {}

    text = get_aurora_briefing_text(dashboard, config, secrets)
    return {"briefing": text}


class ToggleReflexRequest(BaseModel):
    enabled: bool


@router.post("/config/toggle_reflex")
async def toggle_reflex(payload: ToggleReflexRequest):
    try:
        from ruamel.yaml import YAML

        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True
        with open("config.yaml", encoding="utf-8") as f:
            data = yaml_handler.load(f)
        data.setdefault("learning", {})["reflex_enabled"] = payload.enabled
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml_handler.dump(data, f)
        return {"status": "success", "enabled": payload.enabled}
    except Exception as e:
        logger.error("Toggle reflex failed: %s", e)
        raise HTTPException(500, str(e))


# --- Secondary router for /api/forecast/* endpoints ---
forecast_router = APIRouter(tags=["forecast"])


@forecast_router.get("/api/forecast/eval")
async def forecast_eval(days: int = 7):
    """Return simple MAE metrics for baseline vs AURORA forecasts over recent days."""
    try:
        engine = get_learning_engine()
        now = datetime.now(pytz.UTC)
        start_time = now - timedelta(days=max(days, 1))

        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            rows = cursor.execute(
                """
                SELECT
                    f.forecast_version,
                    AVG(ABS(o.pv_kwh - f.pv_forecast_kwh)) as mae_pv,
                    AVG(ABS(o.load_kwh - f.load_forecast_kwh)) as mae_load,
                    COUNT(*) as samples
                FROM slot_observations o
                JOIN slot_forecasts f
                  ON o.slot_start = f.slot_start
                WHERE o.slot_start >= ? AND o.slot_start < ?
                  AND f.forecast_version IN ('baseline_7_day_avg', 'aurora')
                GROUP BY f.forecast_version
            """,
                (start_time.isoformat(), now.isoformat()),
            ).fetchall()

        versions = []
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
        raise HTTPException(500, str(e))


@forecast_router.get("/api/forecast/day")
async def forecast_day(date: str | None = None):
    """Return per-slot actual vs baseline/AURORA forecasts for a single day."""
    try:
        engine = get_learning_engine()
        tz = _get_timezone()

        try:
            target_date = datetime.fromisoformat(date).date() if date else datetime.now(tz).date()
        except Exception:
            target_date = datetime.now(tz).date()

        day_start = tz.localize(datetime(target_date.year, target_date.month, target_date.day))
        day_end = day_start + timedelta(days=1)

        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            obs_rows = cursor.execute(
                """
                SELECT slot_start, pv_kwh, load_kwh
                FROM slot_observations
                WHERE slot_start >= ? AND slot_start < ?
                ORDER BY slot_start ASC
            """,
                (day_start.isoformat(), day_end.isoformat()),
            ).fetchall()

            f_rows = cursor.execute(
                """
                SELECT slot_start, pv_forecast_kwh, load_forecast_kwh, forecast_version
                FROM slot_forecasts
                WHERE slot_start >= ? AND slot_start < ?
                  AND forecast_version IN ('baseline_7_day_avg', 'aurora')
            """,
                (day_start.isoformat(), day_end.isoformat()),
            ).fetchall()

        # Build response
        slots = {}
        for row in obs_rows:
            slot_start = row[0]
            slots[slot_start] = {
                "slot_start": slot_start,
                "actual_pv": row[1],
                "actual_load": row[2],
            }

        for row in f_rows:
            slot_start = row[0]
            if slot_start not in slots:
                slots[slot_start] = {"slot_start": slot_start}
            version = row[3]
            slots[slot_start][f"{version}_pv"] = row[1]
            slots[slot_start][f"{version}_load"] = row[2]

        return {"date": target_date.isoformat(), "slots": list(slots.values())}
    except Exception as e:
        logger.exception("Forecast day failed")
        raise HTTPException(500, str(e))


@forecast_router.get("/api/forecast/horizon")
async def forecast_horizon(hours: int = 48):
    """Return ML forecast for the next N hours."""
    try:
        slots = get_forecast_slots(horizon_hours=hours)
        return {"horizon_hours": hours, "slots": slots}
    except Exception as e:
        logger.exception("Forecast horizon failed")
        raise HTTPException(500, str(e))
