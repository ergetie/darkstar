"""Plausibility of recorded PV against the Open-Meteo baseline, measured on clear days.

A ratio far from 1 on clear days points at shading, wrong panel settings or a faulty PV
measurement. The raw baseline is optimistic, so the plausible band is wide (measured ratios
on four correctly configured sites were 0.65-0.93).
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytz

from backend.learning.pv_cleaning import (
    clean_pv_slots,
    site_location,
    total_solar_kwp,
)

logger = logging.getLogger("darkstar.learning.pv_site_sanity")

PV_SITE_RATIO_LOW = 0.55
PV_SITE_RATIO_HIGH = 1.30
# Acknowledged notices reappear when the ratio moves this much further in the same direction.
PV_SITE_RATIO_REAPPEAR_DELTA = 0.10
PV_SITE_WINDOW_DAYS = 60
# A clear day has at least this share of the window's best daily baseline, and an absolute floor.
CLEAR_DAY_FRACTION = 0.75
CLEAR_DAY_MIN_BASELINE_KWH = 1.0
MIN_CLEAR_DAYS = 14

NOTICE_LOW = "pv_site_ratio_low"
NOTICE_HIGH = "pv_site_ratio_high"
_EPSILON = 1e-9


def notice_code(ratio: float) -> str | None:
    """The notice id for a ratio outside the plausible band, else None."""
    if ratio < PV_SITE_RATIO_LOW:
        return NOTICE_LOW
    if ratio > PV_SITE_RATIO_HIGH:
        return NOTICE_HIGH
    return None


def should_show(ratio: float, acknowledged: float | None) -> bool:
    """Whether the notice for an out-of-band ``ratio`` is visible given an acknowledgement."""
    if acknowledged is None:
        return True
    if acknowledged < PV_SITE_RATIO_LOW:
        return (
            ratio <= acknowledged - PV_SITE_RATIO_REAPPEAR_DELTA + _EPSILON
            or ratio > PV_SITE_RATIO_HIGH
        )
    if acknowledged > PV_SITE_RATIO_HIGH:
        return (
            ratio >= acknowledged + PV_SITE_RATIO_REAPPEAR_DELTA - _EPSILON
            or ratio < PV_SITE_RATIO_LOW
        )
    return True


async def compute_pv_site_ratio(
    store: Any, config: dict[str, Any], days: int = PV_SITE_WINDOW_DAYS
) -> tuple[float, int] | None:
    """Recorded PV / baseline over clear days, and the clear-day count.

    None when there is no data or fewer than ``MIN_CLEAR_DAYS`` clear days.
    """
    df: pd.DataFrame = await store.get_pv_actual_vs_baseline(days)
    if df.empty:
        return None

    latitude, longitude = site_location(config)
    cleaned = clean_pv_slots(
        pd.DataFrame(
            {
                "slot_start": pd.to_datetime(df["slot_start"], utc=True, format="ISO8601"),
                "pv_kwh": df["actual"],
                "baseline_kwh": df["baseline"],
                "soc_end_percent": df["soc_end_percent"],
                "export_kwh": df["export_kwh"],
            }
        ),
        total_kwp=total_solar_kwp(config),
        latitude=latitude,
        longitude=longitude,
    )
    if cleaned.empty:
        return None

    tz = pytz.timezone(str(config.get("timezone", "Europe/Stockholm")))
    day = cleaned["slot_start"].dt.tz_convert(tz).dt.date
    daily_baseline = cleaned.groupby(day)["baseline_kwh"].sum()
    clear = daily_baseline[
        (daily_baseline >= CLEAR_DAY_FRACTION * daily_baseline.max())
        & (daily_baseline >= CLEAR_DAY_MIN_BASELINE_KWH)
    ]
    if len(clear) < MIN_CLEAR_DAYS:
        return None

    selected = cleaned[day.isin(clear.index)]
    return float(selected["pv_kwh"].sum() / selected["baseline_kwh"].sum()), len(clear)
