"""
Price forecasting inference for Nordpool spot price prediction.

This module generates 7-day price forecasts by:
1. Loading the trained price model
2. Fetching regional weather data
3. Computing wind index and features
4. Running inference for p10/p50/p90 quantiles
5. Persisting forecasts to the database
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytz
from sqlalchemy import create_engine, func, tuple_
from sqlalchemy.orm import sessionmaker

from backend.core.prices import calculate_import_export_prices
from backend.learning.models import PriceForecast
from ml.price_features import build_price_features_batch
from ml.weather import compute_regional_wind_index, get_regional_weather

logger = logging.getLogger(__name__)


def derive_consumer_prices(
    spot_p10: float,
    spot_p50: float,
    spot_p90: float,
    config: dict[str, Any],
) -> dict[str, float]:
    """
    Derive import and export prices from spot price forecasts.

    Args:
        spot_p10: P10 spot price forecast in SEK/kWh
        spot_p50: P50 spot price forecast in SEK/kWh
        spot_p90: P90 spot price forecast in SEK/kWh
        config: Configuration dictionary with pricing settings

    Returns:
        Dictionary with derived prices:
        - import_p10, import_p50, import_p90: Import prices
        - export_p10, export_p50, export_p90: Export prices (same as spot)
    """
    # Convert from SEK/kWh to SEK/MWh for the calculation function
    spot_p10_mwh = spot_p10 * 1000.0
    spot_p50_mwh = spot_p50 * 1000.0
    spot_p90_mwh = spot_p90 * 1000.0

    # Calculate import/export prices for each quantile
    import_p10, export_p10 = calculate_import_export_prices(spot_p10_mwh, config)
    import_p50, export_p50 = calculate_import_export_prices(spot_p50_mwh, config)
    import_p90, export_p90 = calculate_import_export_prices(spot_p90_mwh, config)

    return {
        "import_p10": import_p10,
        "import_p50": import_p50,
        "import_p90": import_p90,
        "export_p10": export_p10,
        "export_p50": export_p50,
        "export_p90": export_p90,
    }


async def generate_price_forecasts(
    config: dict[str, Any],
    db_path: str = "data/planner_learning.db",
    model_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Generate price forecasts for D+1 through D+7.

    Args:
        config: Configuration dictionary
        db_path: Path to SQLite database for persisting forecasts
        model_path: Path to trained price model (if None, uses config)

    Returns:
        List of forecast records with spot prices and weather features
    """
    # Get model path from config if not provided
    if model_path is None:
        price_config = config.get("price_forecast", {})
        model_name = price_config.get("model_name", "price_model.lgb")
        model_path = Path("data/ml/models") / model_name

    # model_path is now guaranteed to be a Path
    assert isinstance(model_path, Path)

    # Derive quantile model paths (e.g., price_model_p10.lgb, price_model_p90.lgb)
    model_p10_path = model_path.parent / model_path.name.replace(".lgb", "_p10.lgb")
    model_p90_path = model_path.parent / model_path.name.replace(".lgb", "_p90.lgb")

    # Load all three quantile models
    models: dict[str, lgb.Booster] = {}
    has_model = True
    for quantile, path in [("p10", model_p10_path), ("p50", model_path), ("p90", model_p90_path)]:
        if not path.exists():
            logger.warning(
                "Price model for %s not found at %s, will continue with weather-only rows",
                quantile,
                path,
            )
            has_model = False
            break
    else:
        try:
            for quantile_load, path_load in [
                ("p10", model_p10_path),
                ("p50", model_path),
                ("p90", model_p90_path),
            ]:
                models[quantile_load] = lgb.Booster(model_file=str(path_load))
                logger.info("Loaded price model %s from %s", quantile_load, path_load)
        except Exception as exc:
            logger.warning("Failed to load price model: %s", exc)
            has_model = False

    # Get timezone
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    # Generate forecasts for D+1 through D+7
    all_forecasts: list[dict[str, Any]] = []
    issue_timestamp = now.isoformat()

    for days_ahead in range(1, 8):  # D+1 to D+7
        forecast_date = now.date() + timedelta(days=days_ahead)
        start_time = datetime.combine(forecast_date, datetime.min.time())
        start_time = tz.localize(start_time)
        end_time = start_time + timedelta(days=1)

        # Get regional weather for this day
        price_area = config.get("nordpool", {}).get("price_area", "SE4")

        try:
            regional_weather: dict[str, pd.DataFrame] = get_regional_weather(
                start_time=start_time,
                end_time=end_time,
                price_area=price_area,
                config=config,
            )

            if not regional_weather:
                logger.warning("No regional weather data for %s", forecast_date)
                continue

            # Compute wind index
            wind_index = compute_regional_wind_index(regional_weather)

            if wind_index.empty:
                logger.warning("Could not compute wind index for %s", forecast_date)
                continue

            # Build weather DataFrame with all features
            weather_df = pd.DataFrame(index=wind_index.index)
            weather_df["wind_index"] = wind_index

            # Get temperature from first coordinate's weather data
            for _coord_key, df in regional_weather.items():
                df = df  # type: ignore[assignment]
                if not df.empty and "temp_c" in df.columns:
                    weather_df["temperature_c"] = df["temp_c"]
                if not df.empty and "cloud_cover_pct" in df.columns:
                    weather_df["cloud_cover"] = df["cloud_cover_pct"]
                if not df.empty and "shortwave_radiation_w_m2" in df.columns:
                    weather_df["radiation_wm2"] = df["shortwave_radiation_w_m2"]
                break  # Use first coordinate's weather data

            # Build features for all slots
            feature_df = build_price_features_batch(
                start_time=start_time,
                end_time=end_time,
                days_ahead=days_ahead,
                weather_df=weather_df,
            )

            if feature_df.empty:
                logger.warning("No features generated for %s", forecast_date)
                continue

            # Run inference (only if we have models)
            if has_model:
                feature_cols = [
                    "hour",
                    "day_of_week",
                    "month",
                    "is_weekend",
                    "is_holiday",
                    "days_ahead",
                    "price_lag_1d",
                    "price_lag_7d",
                    "price_lag_24h_avg",
                    "wind_index",
                    "temperature_c",
                    "cloud_cover",
                    "radiation_wm2",
                ]

                X = feature_df[feature_cols]

                # Predict with all three quantile models
                pred_p10_raw = models["p10"].predict(X)  # type: ignore[assignment]
                pred_p50_raw = models["p50"].predict(X)  # type: ignore[assignment]
                pred_p90_raw = models["p90"].predict(X)  # type: ignore[assignment]

                predictions_p10: np.ndarray = np.asarray(pred_p10_raw).flatten()
                predictions_p50: np.ndarray = np.asarray(pred_p50_raw).flatten()
                predictions_p90: np.ndarray = np.asarray(pred_p90_raw).flatten()
            else:
                predictions_p10 = np.array([])
                predictions_p50 = np.array([])
                predictions_p90 = np.array([])

            # Create forecast records
            for i, (idx, row) in enumerate(feature_df.iterrows()):
                slot_start = pd.to_datetime(str(idx))

                if has_model:
                    spot_p10 = float(predictions_p10[i])
                    spot_p50 = float(predictions_p50[i])
                    spot_p90 = float(predictions_p90[i])
                else:
                    spot_p10 = None
                    spot_p50 = None
                    spot_p90 = None

                forecast_record: dict[str, Any] = {
                    "slot_start": slot_start.isoformat(),
                    "issue_timestamp": issue_timestamp,
                    "days_ahead": days_ahead,
                    "spot_p10": spot_p10,
                    "spot_p50": spot_p50,
                    "spot_p90": spot_p90,
                    "wind_index": row.get("wind_index"),
                    "temperature_c": row.get("temperature_c"),
                    "cloud_cover": row.get("cloud_cover"),
                    "radiation_wm2": row.get("radiation_wm2"),
                }

                all_forecasts.append(forecast_record)

        except Exception as exc:
            logger.error("Error generating forecast for %s: %s", forecast_date, exc)
            continue

    # Persist forecasts to database
    if all_forecasts:
        _persist_forecasts(all_forecasts, db_path)
        logger.info("Generated and persisted %d price forecasts", len(all_forecasts))

    return all_forecasts


def _persist_forecasts(forecasts: list[dict[str, Any]], db_path: str) -> None:
    """Persist forecast records to the database."""
    session = None
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        forecast_pairs = {
            (forecast["slot_start"], forecast["days_ahead"]) for forecast in forecasts
        }
        if forecast_pairs:
            session.query(PriceForecast).filter(
                tuple_(PriceForecast.slot_start, PriceForecast.days_ahead).in_(forecast_pairs)
            ).delete(synchronize_session=False)

        for forecast in forecasts:
            pf = PriceForecast(
                slot_start=forecast["slot_start"],
                issue_timestamp=forecast["issue_timestamp"],
                days_ahead=forecast["days_ahead"],
                spot_p10=forecast["spot_p10"],
                spot_p50=forecast["spot_p50"],
                spot_p90=forecast["spot_p90"],
                wind_index=forecast.get("wind_index"),
                temperature_c=forecast.get("temperature_c"),
                cloud_cover=forecast.get("cloud_cover"),
                radiation_wm2=forecast.get("radiation_wm2"),
            )
            session.add(pf)

        session.commit()

    except Exception as exc:
        if session is not None:
            session.rollback()
        logger.error("Error persisting forecasts: %s", exc)
    finally:
        if session is not None:
            session.close()


def cleanup_price_forecast_duplicates(
    db_path: str = "data/planner_learning.db",
) -> int:
    """
    Delete all but the latest issue_timestamp row per (slot_start, days_ahead) pair.

    Returns the number of rows deleted.
    """
    engine = create_engine(f"sqlite:///{db_path}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    latest_per_slot = (
        session.query(
            PriceForecast.slot_start,
            PriceForecast.days_ahead,
            func.max(PriceForecast.issue_timestamp).label("latest_issue"),
        )
        .group_by(PriceForecast.slot_start, PriceForecast.days_ahead)
        .subquery()
    )

    duplicates = (
        session.query(PriceForecast)
        .join(
            latest_per_slot,
            (PriceForecast.slot_start == latest_per_slot.c.slot_start)
            & (PriceForecast.days_ahead == latest_per_slot.c.days_ahead),
        )
        .filter(PriceForecast.issue_timestamp != latest_per_slot.c.latest_issue)
        .all()
    )

    count = len(duplicates)
    for row in duplicates:
        session.delete(row)

    session.commit()
    session.close()
    return count


async def get_price_forecasts_from_db(
    db_path: str = "data/planner_learning.db",
    days_ahead: int | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """
    Retrieve price forecasts from the database.

    Args:
        db_path: Path to SQLite database
        days_ahead: Filter by specific days_ahead value (optional)
        limit: Maximum number of records to return

    Returns:
        List of forecast records
    """
    try:
        engine = create_engine(f"sqlite:///{db_path}")
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()

        if days_ahead is not None:
            latest_per_slot = (
                session.query(
                    PriceForecast.slot_start,
                    func.max(PriceForecast.issue_timestamp).label("latest_issue"),
                )
                .filter(PriceForecast.days_ahead == days_ahead)
                .group_by(PriceForecast.slot_start)
                .subquery()
            )
            query = (
                session.query(PriceForecast)
                .join(
                    latest_per_slot,
                    (PriceForecast.slot_start == latest_per_slot.c.slot_start)
                    & (PriceForecast.issue_timestamp == latest_per_slot.c.latest_issue),
                )
                .filter(PriceForecast.days_ahead == days_ahead)
            )
        else:
            latest_per_slot = (
                session.query(
                    PriceForecast.slot_start,
                    PriceForecast.days_ahead,
                    func.max(PriceForecast.issue_timestamp).label("latest_issue"),
                )
                .group_by(PriceForecast.slot_start, PriceForecast.days_ahead)
                .subquery()
            )
            query = session.query(PriceForecast).join(
                latest_per_slot,
                (PriceForecast.slot_start == latest_per_slot.c.slot_start)
                & (PriceForecast.days_ahead == latest_per_slot.c.days_ahead)
                & (PriceForecast.issue_timestamp == latest_per_slot.c.latest_issue),
            )

        query = query.order_by(PriceForecast.slot_start.desc()).limit(limit)

        results = query.all()

        best_by_slot: dict[str, dict[str, Any]] = {}
        for pf in results:
            row = {
                "slot_start": pf.slot_start,
                "issue_timestamp": pf.issue_timestamp,
                "days_ahead": pf.days_ahead,
                "spot_p10": pf.spot_p10,
                "spot_p50": pf.spot_p50,
                "spot_p90": pf.spot_p90,
                "wind_index": pf.wind_index,
                "temperature_c": pf.temperature_c,
                "cloud_cover": pf.cloud_cover,
                "radiation_wm2": pf.radiation_wm2,
            }
            key = pf.slot_start
            existing = best_by_slot.get(key)
            if existing is None or pf.issue_timestamp > existing["issue_timestamp"]:
                best_by_slot[key] = row

        session.close()
        return list(best_by_slot.values())

    except Exception as exc:
        logger.error("Error retrieving forecasts: %s", exc)
        return []


async def get_d1_price_forecast_fallback(
    config: dict[str, Any],
    db_path: str = "data/planner_learning.db",
) -> list[dict[str, Any]] | None:
    """
    Get D+1 price forecast for fallback when real Nordpool prices not yet available.

    Returns forecast records for D+1 if available, otherwise None.
    Filters out weather-only rows (null-prediction rows) to ensure only valid
    forecasts are returned to the planner.
    """
    try:
        forecasts = await get_price_forecasts_from_db(
            db_path=db_path,
            days_ahead=1,
            limit=96,  # 24 hours * 4 slots per hour
        )

        # Filter out weather-only rows (null-prediction rows)
        valid_forecasts = [f for f in forecasts if f.get("spot_p50") is not None]

        # Deduplicate on slot_start (defence-in-depth against DB duplicates leaking through)
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for f in valid_forecasts:
            slot = f["slot_start"]
            if slot not in seen:
                seen.add(slot)
                deduped.append(f)
        if len(deduped) < len(valid_forecasts):
            logger.warning(
                "get_d1_price_forecast_fallback dropped %d duplicate slot_start entries",
                len(valid_forecasts) - len(deduped),
            )
        valid_forecasts = deduped

        # Filter out stale slots (date <= today)
        today_local = datetime.now(pytz.timezone(config.get("timezone", "Europe/Stockholm"))).date()
        future_forecasts: list[dict[str, Any]] = []
        for f in valid_forecasts:
            slot_dt = f["slot_start"]
            if isinstance(slot_dt, str):
                slot_dt = datetime.fromisoformat(slot_dt)
            slot_date = slot_dt.date() if hasattr(slot_dt, "date") else None
            if slot_date and slot_date > today_local:
                future_forecasts.append(f)

        stale_count = len(valid_forecasts) - len(future_forecasts)
        if stale_count > 0:
            logger.info(
                "get_d1_price_forecast_fallback discarded %d stale slots (date <= today)",
                stale_count,
            )
        valid_forecasts = future_forecasts

        if not valid_forecasts:
            return None

        # Derive consumer prices for each forecast
        for forecast in valid_forecasts:
            consumer_prices = derive_consumer_prices(
                spot_p10=forecast.get("spot_p10", 0),
                spot_p50=forecast.get("spot_p50", 0),
                spot_p90=forecast.get("spot_p90", 0),
                config=config,
            )
            forecast.update(consumer_prices)

        return valid_forecasts

    except Exception as exc:
        logger.error("Error getting D+1 fallback: %s", exc)
        return None
