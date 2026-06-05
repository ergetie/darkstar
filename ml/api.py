"""
API router for Aurora-based forecasting.

Supports hybrid PV forecasting with physics base + ML residual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import pytz

from backend.learning import LearningEngine, get_learning_engine
from ml.weather import calculate_physics_pv, get_weather_series

if TYPE_CHECKING:
    from datetime import datetime


def get_engine() -> LearningEngine:
    """Return the shared LearningEngine instance."""
    return get_learning_engine()


def _load_config() -> dict[str, Any]:
    """Load configuration from YAML file."""
    from pathlib import Path

    import yaml

    try:
        with Path("config.yaml").open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


async def get_forecast_slots(
    start_time: datetime,
    end_time: datetime,
    forecast_version: str,
    include_open_meteo: bool = True,
) -> list[dict[str, Any]]:
    """
    Async return forecast slots for the given time window and version using LearningStore.

    Hybrid PV Forecast Structure:
    - base.pv_kwh: Open-Meteo PV baseline used by the planner/API contract
    - ml_residual.pv_kwh: bounded ML residual on top of the Open-Meteo baseline
    - final.pv_kwh: authoritative forecast value
    - physics.pv_kwh/open_meteo_kwh: legacy diagnostic fields only
    """
    engine = get_engine()
    rows = await engine.store.get_forecasts_range(start_time, forecast_version)

    if not rows:
        return []

    df = pd.DataFrame(rows)
    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True)
    df = df[
        df["slot_start"] < end_time.astimezone(pytz.UTC if end_time.tzinfo else engine.timezone)
    ]

    if df.empty:
        return []

    df["slot_start"] = df["slot_start"].dt.tz_convert(engine.timezone)

    # Load config for physics calculation
    config = _load_config()
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}
    solar_arrays: list[dict[str, Any]] = system_cfg.get("solar_arrays", [])  # type: ignore[assignment]

    # Fallback to legacy single array
    if not solar_arrays:
        legacy_array: dict[str, Any] = system_cfg.get("solar_array", {}) or {}
        if legacy_array:
            solar_arrays = [legacy_array]

    latitude = float(loc_cfg.get("latitude", 59.3) or 59.3)
    longitude = float(loc_cfg.get("longitude", 18.1) or 18.1)

    # Fetch weather for physics calculation
    weather_df = get_weather_series(start_time, end_time, config=config)

    # Calculate physics for each slot
    physics_data: dict[str, dict[str, Any]] = {}
    if solar_arrays and not weather_df.empty and "shortwave_radiation_w_m2" in weather_df.columns:
        for ts_idx, row_data in weather_df.iterrows():
            ts_str = ts_idx.isoformat()  # type: ignore[attr-defined]
            radiation = row_data.get("shortwave_radiation_w_m2")
            physics_kwh, per_array = calculate_physics_pv(
                radiation_w_m2=radiation,
                solar_arrays=solar_arrays,  # type: ignore[arg-type]
                slot_start=ts_idx,  # type: ignore[arg-defined]
                latitude=latitude,
                longitude=longitude,
            )
            physics_data[ts_str] = {
                "physics_kwh": physics_kwh if physics_kwh is not None else 0.0,
                "physics_arrays": per_array if per_array else None,
            }

    # Legacy diagnostic Open-Meteo fields (kept for backward compatibility).
    # The authoritative Open-Meteo baseline is stored in openmeteo_pv_forecast_kwh
    # and exposed as base.pv_kwh below.
    open_meteo_data: dict[str, dict[str, Any]] = {}
    if include_open_meteo and solar_arrays:
        for ts_str, phys_entry in physics_data.items():
            open_meteo_data[ts_str] = {
                "open_meteo_kwh": phys_entry.get("physics_kwh"),
                "open_meteo_arrays": phys_entry.get("physics_arrays"),
            }

    records: list[dict[str, Any]] = []
    for raw_row in df.to_dict("records"):
        row: dict[str, Any] = raw_row  # type: ignore[assignment]
        final_pv = float(row.get("pv_forecast_kwh") or 0.0)
        raw_openmeteo_pv = row.get("openmeteo_pv_forecast_kwh")
        openmeteo_pv = float(raw_openmeteo_pv or 0.0)
        base_load = float(row.get("base_load_forecast_kwh") or row.get("load_forecast_kwh") or 0.0)

        pv_p10_val: float | None = row.get("pv_p10")
        pv_p90_val: float | None = row.get("pv_p90")
        load_p10_val: float | None = row.get("load_p10")
        load_p90_val: float | None = row.get("load_p90")

        slot_ts = row["slot_start"]
        slot_ts_str = str(slot_ts) if not hasattr(slot_ts, "isoformat") else slot_ts.isoformat()  # type: ignore[union-attr]

        # Get physics for this slot
        phys_entry = physics_data.get(slot_ts_str, {})
        physics_kwh = float(phys_entry.get("physics_kwh", 0.0) or 0.0)

        base_pv = openmeteo_pv if raw_openmeteo_pv is not None else physics_kwh
        ml_residual_kwh = final_pv - base_pv

        # Legacy Open-Meteo entry
        om_entry = open_meteo_data.get(slot_ts_str, {})

        records.append(
            {
                "slot_start": slot_ts_str,
                # Hybrid PV structure
                "physics": {"pv_kwh": round(physics_kwh, 4)},
                "ml_residual": {"pv_kwh": round(ml_residual_kwh, 4)},
                "final": {
                    "pv_kwh": round(final_pv, 4),
                    "load_kwh": round(base_load, 4),
                },
                # Legacy fields (backward compatibility)
                "base": {"pv_kwh": round(base_pv, 4), "load_kwh": round(base_load, 4)},
                "probabilistic": {
                    "pv_p10": float(pv_p10_val) if pv_p10_val is not None else None,
                    "pv_p90": float(pv_p90_val) if pv_p90_val is not None else None,
                    "load_p10": float(load_p10_val) if load_p10_val is not None else None,
                    "load_p90": float(load_p90_val) if load_p90_val is not None else None,
                },
                "temp_c": row.get("temp_c"),
                "forecast_version": row.get("forecast_version"),
                # Legacy Open-Meteo fields (deprecated, use physics instead)
                "open_meteo_kwh": om_entry.get("open_meteo_kwh"),
                "open_meteo_arrays": om_entry.get("open_meteo_arrays"),
                "physics_arrays": phys_entry.get("physics_arrays"),
            },
        )

    return records
