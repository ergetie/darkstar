from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pytz
from open_meteo_solar_forecast import OpenMeteoSolarForecast

if TYPE_CHECKING:
    from datetime import datetime

    from backend.learning import LearningEngine

logger = logging.getLogger("darkstar.learning.pv_openmeteo_backfill")


def _valid_arrays(config: dict[str, Any]) -> list[dict[str, float]]:
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    arrays: list[Any] = system_cfg.get("solar_arrays", []) or []
    if not arrays:
        legacy_array: dict[str, Any] = system_cfg.get("solar_array", {}) or {}
        arrays = [legacy_array] if legacy_array else []

    valid: list[dict[str, float]] = []
    for array in arrays:
        if not isinstance(array, dict):
            continue
        array_cfg = cast("dict[str, Any]", array)
        kwp = float(array_cfg.get("kwp", 0.0) or 0.0)
        if kwp <= 0.0:
            continue
        valid.append(
            {
                "kwp": kwp,
                "tilt": float(array_cfg.get("tilt", 30.0) or 30.0),
                "azimuth": (float(array_cfg.get("azimuth", 180.0) or 180.0) % 360) - 180,
            }
        )
    return valid


async def fetch_historical_openmeteo_pv_baselines(
    config: dict[str, Any],
    days: int = 28,
) -> list[dict[str, Any]]:
    """Fetch historical Open-Meteo PV baselines using forecast API past_days."""
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}
    latitude = float(loc_cfg.get("latitude", 59.3) or 59.3)
    longitude = float(loc_cfg.get("longitude", 18.1) or 18.1)
    timezone = pytz.timezone(str(config.get("timezone", "Europe/Stockholm")))
    arrays = _valid_arrays(config)
    if not arrays:
        return []

    summed_watts: dict[datetime, float] = {}
    for array in arrays:
        async with OpenMeteoSolarForecast(
            latitude=latitude,
            longitude=longitude,
            declination=array["tilt"],
            azimuth=array["azimuth"],
            dc_kwp=array["kwp"],
            forecast_days=0,
            past_days=max(1, min(int(days), 28)),
        ) as forecast:
            estimate = await forecast.estimate()
            for dt, watts in estimate.watts.items():
                if dt.tzinfo is None:
                    dt = pytz.UTC.localize(dt)
                summed_watts[dt] = summed_watts.get(dt, 0.0) + float(watts or 0.0)

    rows: list[dict[str, Any]] = []
    sorted_times = sorted(summed_watts)
    resolution_hours = 0.25
    if len(sorted_times) > 1:
        resolution_hours = max(
            abs((sorted_times[1] - sorted_times[0]).total_seconds()) / 3600.0,
            0.0001,
        )

    for dt in sorted_times:
        rows.append(
            {
                "slot_start": dt.astimezone(timezone),
                "openmeteo_pv_forecast_kwh": summed_watts[dt] * resolution_hours / 1000.0,
            }
        )
    return rows


async def backfill_openmeteo_pv_baselines(engine: LearningEngine, days: int = 28) -> int:
    """Backfill only actual-PV slots missing an Open-Meteo baseline."""
    missing_slots = await engine.store.get_pv_slots_missing_openmeteo_baseline(days_back=days)
    if not missing_slots:
        logger.info("Skipping Open-Meteo PV backfill: no missing baseline slots")
        return 0

    missing_slot_keys = {
        pd.Timestamp(slot).astimezone(engine.timezone).isoformat() for slot in missing_slots
    }

    try:
        rows = await fetch_historical_openmeteo_pv_baselines(engine.config, days=days)
    except Exception as exc:
        logger.warning("Skipping Open-Meteo PV backfill: historical fetch failed: %s", exc)
        return 0

    filtered = [
        row
        for row in rows
        if pd.Timestamp(row["slot_start"]).astimezone(engine.timezone).isoformat()
        in missing_slot_keys
    ]
    if not filtered:
        logger.info("Skipping Open-Meteo PV backfill: no fetched rows matched missing slots")
        return 0

    await engine.store_openmeteo_pv_baselines(filtered, forecast_version="aurora")
    logger.info("Backfilled %d missing Open-Meteo PV baseline slots", len(filtered))
    return len(filtered)
