"""Load-training data rules, recent-level feature and slot means for the load forecast.

Pure pandas helpers (no database, no network). The same functions are used by training
(``ml/train.py``) and inference (``ml/forward.py``) so both see identical values.

Rules (universal, no per-site values):

* Legacy ``source: backfill`` rows without modern ``recording`` provenance are dropped.
* Whole legacy local days with a clamp signature are dropped. The pre-recorder pipeline
  subtracted EV load and clamped at 0, leaving days with near-zero load while import, PV
  or battery discharge was clearly active.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd

from backend.measurement_provenance import parse_quality_flags, parse_recording

LOAD_SCHEMA_VERSION = 2

# Clamp-signature day detector.
CLAMP_LOAD_KWH = 0.02
CLAMP_FLOW_KWH = 0.1
CLAMP_SHARE = 0.3
CLAMP_MIN_SLOTS = 80

# Level feature and slot means.
SLOTS_PER_DAY = 96
LEVEL_WINDOW_DAYS = 7
LEVEL_MIN_DAYS = 3
LEVEL_COMPLETE_SHARE = 0.9
SLOT_MEAN_MIN_DAYS = 3

_FLOW_COLUMNS = ("import_kwh", "pv_kwh", "batt_discharge_kwh")


def empty_clean_stats() -> dict[str, int]:
    return {
        "dropped_backfill_rows": 0,
        "dropped_clamp_days": 0,
        "dropped_clamp_rows": 0,
    }


def _flag_info(raw: object) -> tuple[bool, bool]:
    """Return ``(is_backfill, has_recording)`` for one quality_flags value."""
    flags = parse_quality_flags(raw)
    return flags.get("source") == "backfill", parse_recording(flags) is not None


def _provenance_columns(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    if "quality_flags" not in df.columns:
        false = pd.Series(False, index=df.index)
        return false, false
    cache: dict[Any, tuple[bool, bool]] = {}
    backfill: list[bool] = []
    recording: list[bool] = []
    for raw in df["quality_flags"].tolist():
        key = raw if isinstance(raw, str) or raw is None else repr(raw)
        info = cache.get(key)
        if info is None:
            info = _flag_info(raw)
            cache[key] = info
        backfill.append(info[0])
        recording.append(info[1])
    return pd.Series(backfill, index=df.index), pd.Series(recording, index=df.index)


def clean_load_observations(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply the load training data rule to slot observations.

    ``df`` needs tz-aware ``slot_start`` and ``load_kwh``; ``quality_flags``,
    ``import_kwh``, ``pv_kwh`` and ``batt_discharge_kwh`` are used when present. The
    frame must still contain near-zero load rows, otherwise clamp days cannot be seen.
    The ``load_kwh > 0.001`` filter is the caller's job and must run afterwards.

    Returns ``(clean_df, stats)`` with the original index preserved.
    """
    stats = empty_clean_stats()
    if df.empty:
        return df, stats

    is_backfill, has_recording = _provenance_columns(df)
    drop_backfill = is_backfill & ~has_recording
    stats["dropped_backfill_rows"] = int(drop_backfill.sum())

    local_day = df["slot_start"].dt.date
    load = pd.to_numeric(df["load_kwh"], errors="coerce")
    flow_active = pd.Series(False, index=df.index)
    for col in _FLOW_COLUMNS:
        if col in df.columns:
            flow_active |= pd.to_numeric(df[col], errors="coerce") > CLAMP_FLOW_KWH
    clamp_slot = (load <= CLAMP_LOAD_KWH) & flow_active

    # Backfill rows never count towards the day statistics (they are dropped anyway).
    considered = ~drop_backfill
    day_frame = pd.DataFrame(
        {
            "day": local_day[considered],
            "clamp": clamp_slot[considered],
            "recording": has_recording[considered],
        }
    )
    grouped = day_frame.groupby("day")
    slots = grouped["clamp"].size()
    share = grouped["clamp"].mean()
    legacy = ~grouped["recording"].any()
    flagged_days = share.index[(slots >= CLAMP_MIN_SLOTS) & legacy & (share > CLAMP_SHARE)]

    drop_clamp = local_day.isin(set(flagged_days)) & ~drop_backfill
    stats["dropped_clamp_days"] = len(flagged_days)
    stats["dropped_clamp_rows"] = int(drop_clamp.sum())

    return df[~(drop_backfill | drop_clamp)], stats


def _local_dates(slot_starts: pd.Series) -> pd.Series:
    return slot_starts.dt.date


def _daily_loads(clean_df: pd.DataFrame) -> dict[date, float]:
    """Daily load (kWh) of complete local days: mean slot load scaled to 96 slots."""
    if clean_df.empty:
        return {}
    frame = pd.DataFrame(
        {
            "day": _local_dates(clean_df["slot_start"]),
            "load": pd.to_numeric(clean_df["load_kwh"], errors="coerce"),
        }
    ).dropna()
    grouped = frame.groupby("day")["load"].agg(["size", "mean"])
    min_slots = LEVEL_COMPLETE_SHARE * SLOTS_PER_DAY
    days: list[date] = [cast("date", d) for d in grouped.index.tolist()]
    counts: list[int] = [int(c) for c in grouped["size"].tolist()]
    means: list[float] = [float(m) for m in grouped["mean"].tolist()]
    return {
        day: mean * SLOTS_PER_DAY
        for day, count, mean in zip(days, counts, means, strict=True)
        if count >= min_slots
    }


def load_level_7d(clean_df: pd.DataFrame, slot_starts: pd.Series) -> pd.Series:
    """``load_level_7d`` for each slot start (index of ``slot_starts`` is kept).

    For a slot on local day D: mean daily load over the complete clean local days
    D-7..D-1. With fewer than 3 such days the value of the most recent earlier day that
    had at least 3 is held; NaN when there never was one. Day D and later never
    contribute, forecast values never enter the level.
    """
    if len(slot_starts) == 0:
        return pd.Series(dtype="float64", index=slot_starts.index)
    daily = _daily_loads(clean_df)
    if not daily:
        return pd.Series(np.nan, index=slot_starts.index, dtype="float64")

    wanted = _local_dates(slot_starts)
    first_day = min(daily) + timedelta(days=1)
    last_day = max(wanted.max(), first_day)

    level_by_day: dict[date, float] = {}
    held = float("nan")
    day = first_day
    while day <= last_day:
        values = [
            daily[day - timedelta(days=k)]
            for k in range(1, LEVEL_WINDOW_DAYS + 1)
            if (day - timedelta(days=k)) in daily
        ]
        if len(values) >= LEVEL_MIN_DAYS:
            held = float(np.mean(values))
        level_by_day[day] = held
        day += timedelta(days=1)

    levels = [level_by_day.get(day, float("nan")) for day in wanted.tolist()]
    return pd.Series(levels, index=slot_starts.index, dtype="float64")


def slot_means_7d(
    clean_df: pd.DataFrame,
    slot_starts: pd.Series,
    now: pd.Timestamp,
) -> pd.Series:
    """Mean actual load of the same local 15-minute slot over the previous 7 local days.

    Only observations strictly before ``now`` contribute. NaN where fewer than 3 days
    provide the slot. The index of ``slot_starts`` is kept.
    """
    result = pd.Series(np.nan, index=slot_starts.index, dtype="float64")
    if clean_df.empty or len(slot_starts) == 0:
        return result

    obs = clean_df[clean_df["slot_start"] < now]
    if obs.empty:
        return result
    obs_days = _local_dates(obs["slot_start"])
    obs_minutes = obs["slot_start"].dt.hour * 60 + obs["slot_start"].dt.minute
    obs_load = pd.to_numeric(obs["load_kwh"], errors="coerce")
    lookup: dict[tuple[date, int], float] = {}
    for day, minute, value in zip(obs_days, obs_minutes, obs_load, strict=True):
        if np.isfinite(value):
            lookup[(day, int(minute))] = float(value)

    slot_days = _local_dates(slot_starts)
    slot_minutes = slot_starts.dt.hour * 60 + slot_starts.dt.minute
    means: list[float] = []
    for day, minute in zip(slot_days, slot_minutes, strict=True):
        values = [
            lookup[(day - timedelta(days=k), int(minute))]
            for k in range(1, LEVEL_WINDOW_DAYS + 1)
            if (day - timedelta(days=k), int(minute)) in lookup
        ]
        means.append(float(np.mean(values)) if len(values) >= SLOT_MEAN_MIN_DAYS else float("nan"))
    return pd.Series(means, index=slot_starts.index, dtype="float64")
