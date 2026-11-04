"""Shared PV slot cleaning for model training, the Reflex bias input and the site sanity check.

A slot is a credible PV measurement unless it is night, a sensor dropout, a spike above what
the array can produce, or curtailed by a full battery. Shaded slots (zero PV while the
Open-Meteo baseline is positive) are kept so the model can learn shading.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd

from ml.weather import _calculate_solar_position  # type: ignore[reportPrivateUsage]

logger = logging.getLogger("darkstar.learning.pv_cleaning")

# Slots with a baseline at or below this are night (or negligible production).
MIN_BASELINE_KWH = 0.01
# Recorded 0 while the baseline is above this is a sensor/inverter dropout, not shade.
DROPOUT_BASELINE_KWH = 0.3
# Maximum credible slot energy is kWp * 0.25 h, with a margin for panel over-performance.
SPIKE_SLOT_HOURS = 0.25
SPIKE_MARGIN = 1.05
# Production above this while the sun is below NIGHT_ELEVATION_DEG is a measurement artefact.
NIGHT_PV_KWH = 0.05
NIGHT_ELEVATION_DEG = -3.0
# Battery full and nothing exported means the inverter throttled the panels.
CURTAIL_SOC_PERCENT = 97.0
CURTAIL_EXPORT_KWH = 0.02
CURTAIL_MIN_BASELINE_KWH = 0.05
SLOT_MINUTES = 15

RULES = ("no_baseline", "dropout", "spike", "night_production", "curtailed")


def total_solar_kwp(config: dict[str, Any]) -> float:
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    arrays: list[Any] = system_cfg.get("solar_arrays", []) or []
    if not arrays:
        legacy_array: dict[str, Any] = system_cfg.get("solar_array", {}) or {}
        arrays = [legacy_array] if legacy_array else []
    return sum(
        float(cast("dict[str, Any]", array).get("kwp", 0.0) or 0.0)
        for array in arrays
        if isinstance(array, dict)
    )


def site_location(config: dict[str, Any]) -> tuple[float, float]:
    """Latitude and longitude from config, with the same defaults as the weather code."""
    system_cfg: dict[str, Any] = config.get("system", {}) or {}
    loc_cfg: dict[str, Any] = system_cfg.get("location", {}) or {}
    return float(loc_cfg.get("latitude", 59.3)), float(loc_cfg.get("longitude", 18.1))


def _night_production_mask(
    df: pd.DataFrame, latitude: float, longitude: float, pv: pd.Series[float]
) -> pd.Series[bool]:
    mask = pd.Series(False, index=df.index)
    candidates = pv > NIGHT_PV_KWH
    if not candidates.any():
        return mask
    mid = pd.to_datetime(df.loc[candidates, "slot_start"], utc=True) + pd.Timedelta(
        minutes=SLOT_MINUTES / 2
    )
    below_horizon = np.array(
        [
            _calculate_solar_position(latitude, longitude, ts.to_pydatetime())["elevation"]
            < NIGHT_ELEVATION_DEG
            for ts in mid
        ]
    )
    mask.loc[candidates] = below_horizon
    return mask


def clean_pv_slots(
    df: pd.DataFrame,
    *,
    total_kwp: float,
    latitude: float | None,
    longitude: float | None,
) -> pd.DataFrame:
    """Return ``df`` without slots that are not credible PV measurements.

    Needs ``slot_start`` (tz-aware), ``pv_kwh`` and ``baseline_kwh``; ``soc_end_percent`` and
    ``export_kwh`` are optional. Each rule is evaluated on the original rows and a slot is
    dropped when any rule matches; a rule whose inputs are missing is skipped for that slot.
    Per-rule drop counts are in ``result.attrs["dropped_by_rule"]`` (a slot counts once per
    matching rule).
    """
    if df.empty:
        out = df.copy()
        out.attrs["dropped_by_rule"] = dict.fromkeys(RULES, 0)
        return out

    pv = pd.to_numeric(df["pv_kwh"], errors="coerce")
    baseline = pd.to_numeric(df["baseline_kwh"], errors="coerce")

    masks: dict[str, pd.Series[bool]] = {
        "no_baseline": ~(baseline > MIN_BASELINE_KWH),
        "dropout": (pv == 0) & (baseline > DROPOUT_BASELINE_KWH),
    }

    spike = pd.Series(False, index=df.index)
    if total_kwp > 0:
        spike = pv > total_kwp * SPIKE_SLOT_HOURS * SPIKE_MARGIN
    masks["spike"] = spike

    if latitude is not None and longitude is not None:
        masks["night_production"] = _night_production_mask(df, latitude, longitude, pv)
    else:
        masks["night_production"] = pd.Series(False, index=df.index)

    if "soc_end_percent" in df.columns and "export_kwh" in df.columns:
        soc = pd.to_numeric(df["soc_end_percent"], errors="coerce")
        export = pd.to_numeric(df["export_kwh"], errors="coerce")
        masks["curtailed"] = (
            (soc >= CURTAIL_SOC_PERCENT)
            & (export < CURTAIL_EXPORT_KWH)
            & (baseline > CURTAIL_MIN_BASELINE_KWH)
        )
    else:
        masks["curtailed"] = pd.Series(False, index=df.index)

    drop = pd.Series(False, index=df.index)
    for mask in masks.values():
        drop |= mask
    out = df.loc[~drop].copy()
    dropped = {rule: int(masks[rule].sum()) for rule in RULES}
    out.attrs["dropped_by_rule"] = dropped
    logger.info(
        "PV cleaning kept %d of %d slots; dropped by rule: %s",
        len(out),
        len(df),
        dropped,
    )
    return out
