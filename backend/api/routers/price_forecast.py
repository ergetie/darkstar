"""
Price forecast API router for Nordpool spot price predictions.

Provides endpoints to retrieve 7-day price forecasts (p10/p50/p90) when
price forecasting is enabled and models are trained.
"""

import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.core.secrets import load_yaml
from backend.learning import get_learning_engine
from ml.price_forecast import derive_consumer_prices, get_price_forecasts_from_db

logger = logging.getLogger("darkstar.api.price_forecast")
router = APIRouter(prefix="/api/price-forecast", tags=["price-forecast"])


def _fetch_forecasts_with_actuals(db_path: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT slot_start, issue_timestamp, days_ahead, spot_p10, spot_p50, spot_p90,
                   wind_index, temperature_c, cloud_cover, radiation_wm2
            FROM price_forecasts
            WHERE slot_start >= datetime('now', '-7 days')
            ORDER BY slot_start ASC
        """)
        rows = cursor.fetchall()

        forecasts = [
            {
                "slot_start": r["slot_start"],
                "issue_timestamp": r["issue_timestamp"],
                "days_ahead": r["days_ahead"],
                "spot_p10": r["spot_p10"],
                "spot_p50": r["spot_p50"],
                "spot_p90": r["spot_p90"],
                "wind_index": r["wind_index"],
                "temperature_c": r["temperature_c"],
                "cloud_cover": r["cloud_cover"],
                "radiation_wm2": r["radiation_wm2"],
            }
            for r in rows
        ]

        # Deduplicate by slot_start, keeping the row with highest days_ahead
        seen: dict[str, dict[str, Any]] = {}
        for f in forecasts:
            key = f["slot_start"]
            if key not in seen or f["days_ahead"] > seen[key]["days_ahead"]:
                seen[key] = f
        forecasts = list(seen.values())
        forecasts.sort(key=lambda x: x["slot_start"])
        return forecasts
    finally:
        conn.close()


def _fetch_actuals_map(db_path: str) -> dict[str, float | None]:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT slot_start, export_price_sek_kwh FROM slot_observations WHERE export_price_sek_kwh IS NOT NULL"
        )
        return {row[0]: float(row[1]) for row in cursor.fetchall()}
    finally:
        conn.close()


def _fetch_training_samples_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        count = conn.execute("SELECT COUNT(*) FROM price_forecasts").fetchone()
        return count[0] if count else 0
    finally:
        conn.close()


def _fetch_accuracy_rows(db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pf.slot_start, pf.spot_p50, so.export_price_sek_kwh
            FROM price_forecasts pf
            JOIN slot_observations so ON so.slot_start = pf.slot_start
            WHERE pf.days_ahead = 1
              AND pf.spot_p50 IS NOT NULL
              AND so.export_price_sek_kwh IS NOT NULL
              AND pf.slot_start >= datetime('now', '-7 days')
        """)
        return list(cursor.fetchall())
    finally:
        conn.close()


class PriceForecastResponse(BaseModel):
    """Response model for price forecast endpoint."""

    status: str
    message: str
    forecasts: list[dict[str, Any]]


def _load_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    try:
        return load_yaml("config.yaml")
    except Exception:
        return {}


def _is_price_forecast_enabled(config: dict[str, Any]) -> bool:
    """Check if price forecasting is enabled in config."""
    price_config = config.get("price_forecast", {})
    return price_config.get("enabled", False)


def _price_model_exists(config: dict[str, Any]) -> bool:
    """Check if a trained price model exists."""
    price_config = config.get("price_forecast", {})
    model_name = price_config.get("model_name", "price_model.lgb")
    model_path = Path("data/ml/models") / model_name
    return model_path.exists()


@router.get("", response_model=PriceForecastResponse)
async def get_price_forecasts(
    request: Request, include_actuals: bool = False
) -> PriceForecastResponse:
    """
    Get price forecasts for D+1 through D+7.

    Returns spot price forecasts (p10/p50/p90) along with derived
    import/export prices when price forecasting is enabled and a
    trained model is available.

    Response includes:
    - status: "enabled" | "disabled" | "no_model" | "no_data"
    - message: Human-readable status description
    - forecasts: Array of forecast records with slot_start, spot_p10/p50/p90,
                 import_p50, export_p50, days_ahead
    """
    config = _load_config()

    # Check if price forecasting is enabled
    if not _is_price_forecast_enabled(config):
        return PriceForecastResponse(
            status="disabled",
            message="Price forecasting is disabled in configuration",
            forecasts=[],
        )

    # Check if model exists
    if not _price_model_exists(config):
        return PriceForecastResponse(
            status="no_model",
            message="Price forecast model not yet trained (insufficient data)",
            forecasts=[],
        )

    # Get forecasts from database
    try:
        engine = get_learning_engine()
        db_path = str(engine.db_path)
    except Exception:
        db_path = "data/planner_learning.db"

    if include_actuals:
        forecasts = await asyncio.to_thread(_fetch_forecasts_with_actuals, db_path)
    else:
        forecasts = await get_price_forecasts_from_db(db_path=db_path, limit=1000)

    if not forecasts:
        return PriceForecastResponse(
            status="no_data",
            message="No price forecasts available yet",
            forecasts=[],
        )

    # Enrich forecasts with derived consumer prices
    enriched_forecasts: list[dict[str, Any]] = []

    actuals_map: dict[str, float | None] = {}
    if include_actuals:
        actuals_map = await asyncio.to_thread(_fetch_actuals_map, db_path)

    for forecast in forecasts:
        consumer_prices = derive_consumer_prices(
            spot_p10=forecast.get("spot_p10") or 0,
            spot_p50=forecast.get("spot_p50") or 0,
            spot_p90=forecast.get("spot_p90") or 0,
            config=config,
        )

        enriched_forecast = {
            "slot_start": forecast["slot_start"],
            "days_ahead": forecast["days_ahead"],
            "spot_p10": forecast.get("spot_p10"),
            "spot_p50": forecast.get("spot_p50"),
            "spot_p90": forecast.get("spot_p90"),
            "import_p50": consumer_prices.get("import_p50"),
            "export_p50": consumer_prices.get("export_p50"),
        }

        if include_actuals:
            enriched_forecast["actual_spot"] = actuals_map.get(forecast["slot_start"])

        enriched_forecasts.append(enriched_forecast)

    # Sort by slot_start
    enriched_forecasts.sort(key=lambda x: x["slot_start"])

    return PriceForecastResponse(
        status="enabled",
        message=f"Retrieved {len(enriched_forecasts)} price forecasts",
        forecasts=enriched_forecasts,
    )


@router.get("/status")
async def get_price_forecast_status(request: Request) -> dict[str, Any]:
    """
    Get status of the price forecasting system.

    Returns configuration and model status without fetching forecast data.
    """
    config = _load_config()
    price_config = config.get("price_forecast", {})

    enabled = _is_price_forecast_enabled(config)
    model_exists = _price_model_exists(config)

    # Get model info if it exists
    model_info = None
    if model_exists:
        model_name = price_config.get("model_name", "price_model.lgb")
        model_path = Path("data/ml/models") / model_name
        try:
            stat = model_path.stat()
            model_info = {
                "name": model_name,
                "size_bytes": stat.st_size,
                "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        except Exception:
            pass

    training_samples_count = 0
    try:
        engine = get_learning_engine()
        db_path = str(engine.db_path)
        training_samples_count = await asyncio.to_thread(_fetch_training_samples_count, db_path)
    except Exception:
        pass

    return {
        "enabled": enabled,
        "config": {
            "min_training_samples": price_config.get("min_training_samples", 500),
            "model_name": price_config.get("model_name", "price_model.lgb"),
        },
        "model_available": model_exists,
        "model_info": model_info,
        "training_samples_count": training_samples_count,
    }


@router.get("/accuracy")
async def get_price_forecast_accuracy(request: Request) -> dict[str, Any]:
    """
    Get D+1 price forecast accuracy metrics.

    Compares past D+1 forecasts against actual spot prices from slot_observations
    over the last 7 days to compute MAE and bias.
    """
    config = _load_config()

    if not _is_price_forecast_enabled(config):
        return {
            "enabled": False,
            "d1_mae": None,
            "d1_bias": None,
            "sample_days": 0,
            "status": "disabled",
        }

    try:
        engine = get_learning_engine()
        db_path = str(engine.db_path)
    except Exception:
        db_path = "data/planner_learning.db"

    rows = await asyncio.to_thread(_fetch_accuracy_rows, db_path)

    errors = [abs(float(r["spot_p50"]) - float(r["export_price_sek_kwh"])) for r in rows]
    biases = [float(r["spot_p50"]) - float(r["export_price_sek_kwh"]) for r in rows]
    unique_days = len({r["slot_start"][:10] for r in rows})

    if unique_days < 2:
        return {
            "enabled": True,
            "d1_mae": None,
            "d1_bias": None,
            "sample_days": unique_days,
            "status": "insufficient_data",
        }

    return {
        "enabled": True,
        "d1_mae": round(sum(errors) / len(errors), 4),
        "d1_bias": round(sum(biases) / len(biases), 4),
        "sample_days": unique_days,
        "status": "ok",
    }


@router.get("/outlook")
async def get_price_outlook(request: Request) -> dict[str, Any]:
    """
    Get daily price outlook for D+1 through D+7.

    Returns aggregated daily summaries with price levels and confidence,
    suitable for the Weekly Outlook UI widget.

    Response includes:
    - enabled: Whether price forecasting is enabled
    - days: Array of 7 daily summaries with date, avg prices, min/max, level, confidence
    - reference_avg: 14-day trailing average spot price (or null)
    - status: "ok" | "disabled" | "no_data"
    """
    config = _load_config()

    # Check if price forecasting is enabled
    if not _is_price_forecast_enabled(config):
        return {"enabled": False, "days": [], "reference_avg": None, "status": "disabled"}

    # Import outlook helpers
    # Get the forecast database path
    from backend.core.forecasts import get_forecast_db_path
    from backend.core.price_outlook import (
        async_get_daily_outlook,
        async_get_trailing_avg,
        build_outlook_response,
    )

    db_path = get_forecast_db_path()

    # Fetch daily outlook data
    daily_outlook = await async_get_daily_outlook(db_path)

    # Fetch trailing average reference
    reference_avg = await async_get_trailing_avg(db_path)

    # Build and return the response with classifications
    return build_outlook_response(daily_outlook, reference_avg, enabled=True)
