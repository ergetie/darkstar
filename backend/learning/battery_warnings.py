"""Warn-only battery checks: sudden capacity change and under-delivered battery power.

Both are pure functions over recorded rows. They never change a setting or a planning input;
the health module turns their results into snoozable warnings.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytz

from backend.battery_benchmark import (
    CAPACITY_MIN_SOC_RANGE_PP,
    SLOT_MINUTES,
    _has_gap,  # pyright: ignore[reportPrivateUsage]
    _local_day_bounds,  # pyright: ignore[reportPrivateUsage]
    implied_capacity,
    rows_by_local_day,
    slot_recording,
)
from backend.learning.battery_estimators import slot_bounds
from backend.measurement_provenance import SUPPORTED_METHODS, parse_quality_flags, parse_recording

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from planner.solver.types import KeplerConfig

# --- Capacity change ---------------------------------------------------------------------
CAPACITY_WINDOW_DAYS = 7
CAPACITY_WINDOW_MIN_DAYS = 4  # usable days a window needs to give a capacity
CAPACITY_BASELINE_WINDOWS = 8
CAPACITY_BASELINE_MIN_VALID = 4
CAPACITY_CHANGE_THRESHOLD = 0.25
CAPACITY_WINDOW_COUNT = 2 + CAPACITY_BASELINE_WINDOWS

# --- Power shortfall ---------------------------------------------------------------------
POWER_WINDOW_DAYS = 14
POWER_MIN_SLOTS = 20
POWER_PLANNED_SHARE = 0.95
POWER_DELIVERED_SHARE = 0.8


@dataclass(frozen=True)
class CapacityWarning:
    baseline_kwh: float
    latest_kwh: tuple[float, float]  # newest window first
    configured_kwh: float


@dataclass(frozen=True)
class PowerShortfall:
    direction: str  # "charge" or "discharge"
    slots: int
    planned_kw: float  # median planned power of the qualifying slots
    delivered_kw: float  # median recorded battery power of the same slots
    limit_kw: float


def _usable_day(
    day: date,
    by_day: Mapping[date, list[dict[str, Any]]],
    tz: Any,
    now: datetime,
) -> bool:
    """A whole recorded day whose slots give exact battery flows, with a start-SoC slot."""
    rows = by_day.get(day)
    previous = by_day.get(day - timedelta(days=1))
    if not rows or not previous:
        return False
    start, end = _local_day_bounds(day, tz)
    if end > now:
        return False
    bounds = [slot_bounds(row) for row in rows]
    if any(b is None for b in bounds):
        return False
    times = [b for b in bounds if b is not None]
    expected = int((end - start).total_seconds() // (SLOT_MINUTES * 60))
    if (
        len(rows) != expected
        or times[0][0] != start
        or times[-1][1] != end
        or any(times[i - 1][1] != times[i][0] for i in range(1, len(times)))
    ):
        return False
    previous_end = slot_bounds(previous[-1])
    if previous_end is None or previous_end[1] != start:
        return False
    soc = previous[-1].get("soc_end_percent")
    if not isinstance(soc, int | float) or not math.isfinite(soc):
        return False
    return all(slot_recording(row) in {"clean", "partial"} and not _has_gap(row) for row in rows)


def window_capacities(
    rows: Sequence[dict[str, Any]], config: KeplerConfig, now: datetime
) -> list[float | None]:
    """Implied capacity of the latest ``CAPACITY_WINDOW_COUNT`` weeks, newest first.

    ``None`` for a window with too few usable days, no usable SoC swing or no fit. The
    windows end yesterday (local) and do not overlap.
    """
    tz = pytz.timezone(config.timezone_name)
    local_now = now.astimezone(tz)
    by_day = rows_by_local_day(list(rows), tz)
    today = local_now.date()
    result: list[float | None] = []
    for index in range(CAPACITY_WINDOW_COUNT):
        last = today - timedelta(days=1 + index * CAPACITY_WINDOW_DAYS)
        days = [last - timedelta(days=offset) for offset in range(CAPACITY_WINDOW_DAYS)]
        usable = [d for d in days if _usable_day(d, by_day, tz, local_now)]
        if len(usable) < CAPACITY_WINDOW_MIN_DAYS:
            result.append(None)
            continue
        implied, soc_range = implied_capacity(
            [by_day[d] for d in usable],
            [by_day[d - timedelta(days=1)][-1] for d in usable],
            config,
        )
        valid = implied is not None and implied > 0 and soc_range >= CAPACITY_MIN_SOC_RANGE_PP
        result.append(implied if valid else None)
    return result


def capacity_change_warning(
    rows: Sequence[dict[str, Any]], config: KeplerConfig, now: datetime
) -> CapacityWarning | None:
    """Warn when the two latest weekly capacities both differ >= 25 % from the baseline.

    The baseline is the median of the 8 preceding weeks and needs at least 4 valid ones.
    Pure: nothing is written and no setting or planning value is touched.
    """
    capacities = window_capacities(rows, config, now)
    latest = capacities[:2]
    baseline_values = [c for c in capacities[2:] if c is not None]
    if None in latest or len(baseline_values) < CAPACITY_BASELINE_MIN_VALID:
        return None
    baseline = statistics.median(baseline_values)
    if baseline <= 0:
        return None
    newest = (float(latest[0] or 0.0), float(latest[1] or 0.0))
    if all(abs(value - baseline) / baseline >= CAPACITY_CHANGE_THRESHOLD for value in newest):
        return CapacityWarning(baseline, newest, config.capacity_kwh)
    return None


def _battery_measured(row: Mapping[str, Any]) -> bool:
    flags = parse_quality_flags(row.get("quality_flags"))
    if flags.get("exclude") is True:
        return False
    recording = parse_recording(flags, SUPPORTED_METHODS)
    if recording is None:
        return False
    components: dict[str, Any] = recording["components"]
    return all(
        isinstance(components.get(name), dict) and components[name].get("method") == "power_history"
        for name in ("battery_charge", "battery_discharge")
    )


def _number(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def power_shortfall_warning(
    rows: Sequence[Mapping[str, Any]],
    plans: Sequence[Mapping[str, Any]],
    config: KeplerConfig,
    now: datetime,
) -> list[PowerShortfall]:
    """Charge and discharge shortfalls over the last 14 days (empty when none).

    A qualifying slot is one where the plan asked for at least 95 % of the configured
    maximum power. A direction warns with at least 20 such slots and a median recorded
    battery power below 80 % of the planned power. Pure and warn-only.
    """
    cutoff = now - timedelta(days=POWER_WINDOW_DAYS)
    recorded = {str(row["slot_start"]): row for row in rows if row.get("slot_start")}
    results: list[PowerShortfall] = []
    for direction, limit_kw, planned_key, recorded_key in (
        ("charge", config.max_charge_power_kw, "planned_charge_kwh", "batt_charge_kwh"),
        ("discharge", config.max_discharge_power_kw, "planned_discharge_kwh", "batt_discharge_kwh"),
    ):
        if limit_kw <= 0:
            continue
        planned_kw: list[float] = []
        delivered_kw: list[float] = []
        for plan in plans:
            bounds = slot_bounds(plan)
            planned = _number(plan, planned_key)
            row = recorded.get(str(plan.get("slot_start")))
            if bounds is None or planned is None or row is None:
                continue
            start, end = bounds
            hours = (end - start).total_seconds() / 3600.0
            if start < cutoff or end > now or planned < POWER_PLANNED_SHARE * limit_kw * hours:
                continue
            delivered = _number(row, recorded_key)
            if delivered is None or not _battery_measured(row):
                continue
            planned_kw.append(planned / hours)
            delivered_kw.append(delivered / hours)
        if len(planned_kw) < POWER_MIN_SLOTS:
            continue
        ratios = [d / p for d, p in zip(delivered_kw, planned_kw, strict=True) if p > 0]
        if ratios and statistics.median(ratios) < POWER_DELIVERED_SHARE:
            results.append(
                PowerShortfall(
                    direction,
                    len(planned_kw),
                    statistics.median(planned_kw),
                    statistics.median(delivered_kw),
                    limit_kw,
                )
            )
    return results
