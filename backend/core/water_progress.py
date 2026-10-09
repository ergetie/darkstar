"""Per-heater delivered-energy progress for the first solver quota bucket."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, cast

import pytz

from backend.core.ha_client import get_power_history_batch, parse_power_states
from backend.core.water_heating import (
    DEFAULT_IDLE_POWER_THRESHOLD_KW,
    normalize_active_power_kw,
    water_quota_window,
)
from backend.learning.store import LearningStore
from backend.measurement_provenance import boundary_fingerprint

logger = logging.getLogger(__name__)


def _as_local_datetime(value: Any, timezone: pytz.BaseTzInfo) -> datetime | None:
    if isinstance(value, datetime):
        return timezone.localize(value) if value.tzinfo is None else value.astimezone(timezone)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return timezone.localize(parsed) if parsed.tzinfo is None else parsed.astimezone(timezone)


def _history_energy(
    states: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    cutoff_kw: float,
    timezone: pytz.BaseTzInfo,
) -> tuple[float, float]:
    """Integrate only known HA history segments; return energy and covered seconds."""
    valid_by_time = {
        local_time: value
        for timestamp, value in parse_power_states(states)
        if (local_time := _as_local_datetime(timestamp, timezone)) is not None
    }
    transitions: list[tuple[datetime, float | None]] = []
    cached_unit: str | None = None
    for state in states:
        timestamp = _as_local_datetime(
            state.get("last_changed") or state.get("last_updated"), timezone
        )
        if timestamp is None:
            continue
        attributes_raw = state.get("attributes")
        attributes = (
            cast("dict[str, Any]", attributes_raw) if isinstance(attributes_raw, dict) else {}
        )
        unit: object = attributes.get("unit_of_measurement")
        if unit not in (None, ""):
            cached_unit = str(unit)
        parsed_kw = valid_by_time.get(timestamp)
        if parsed_kw is None:
            raw = state.get("state")
            if not isinstance(raw, str | int | float) or isinstance(raw, bool):
                value = None
            else:
                try:
                    numeric = float(raw)
                except ValueError:
                    value = None
                else:
                    normalized_value = normalize_active_power_kw(
                        numeric, unit or cached_unit or "kW", cutoff_kw
                    )
                    value = max(0.0, normalized_value) if normalized_value is not None else None
        else:
            normalized_value = normalize_active_power_kw(parsed_kw, "kW", cutoff_kw)
            value = max(0.0, normalized_value) if normalized_value is not None else None
        transitions.append((timestamp, value))
    transitions.sort(key=lambda item: item[0])

    current: float | None = None
    cursor = start
    energy = 0.0
    covered_seconds = 0.0
    for timestamp, value in transitions:
        if timestamp <= start:
            current = value
            continue
        if timestamp >= end:
            break
        if current is not None:
            seconds = (timestamp - cursor).total_seconds()
            energy += current * seconds / 3600.0
            covered_seconds += seconds
        current = value
        cursor = timestamp
    if current is not None and cursor < end:
        seconds = (end - cursor).total_seconds()
        energy += current * seconds / 3600.0
        covered_seconds += seconds
    return max(0.0, energy), covered_seconds


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _gaps(
    start: datetime, end: datetime, intervals: list[tuple[datetime, datetime]]
) -> list[tuple[datetime, datetime]]:
    gaps: list[tuple[datetime, datetime]] = []
    cursor = start
    for covered_start, covered_end in _merge_intervals(intervals):
        if cursor < covered_start:
            gaps.append((cursor, covered_start))
        cursor = max(cursor, covered_end)
    if cursor < end:
        gaps.append((cursor, end))
    return gaps


async def read_water_heating_progress(
    config: dict[str, Any],
    cutoff: datetime,
    db_path: str,
    current_power_kw: dict[str, float | None] | None = None,
    measured_until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Combine attributable stored energy and uncovered HA history before ``cutoff``."""
    timezone = pytz.timezone(str(config.get("timezone", "Europe/Stockholm")))
    local_cutoff = _as_local_datetime(cutoff, timezone)
    if local_cutoff is None:
        raise ValueError("water progress cutoff must be a valid datetime")
    wh_settings = config.get("water_heating", {})
    defer_hours = float(wh_settings.get("defer_up_to_hours", 6.0))
    bucket_start, bucket_end = water_quota_window(local_cutoff, defer_hours, timezone)
    end = min(local_cutoff, bucket_end)
    if measured_until is not None:
        available_end = _as_local_datetime(measured_until, timezone)
        if available_end is None:
            raise ValueError("water measurement cutoff must be a valid datetime")
        end = max(bucket_start, min(end, available_end))
    raw_heaters = config.get("water_heaters", [])
    heater_values = cast("list[object]", raw_heaters) if isinstance(raw_heaters, list) else []
    heaters: list[dict[str, Any]] = []
    for raw_heater in heater_values:
        if isinstance(raw_heater, dict):
            heater = cast("dict[str, Any]", raw_heater)
            if heater.get("enabled", True):
                heaters.append(heater)
    heaters = [heater for heater in heaters if heater.get("id")]
    enabled_ids = [str(heater["id"]) for heater in heaters]
    values = dict.fromkeys(enabled_ids, 0.0)
    sources: dict[str, set[str]] = {heater_id: set() for heater_id in enabled_ids}
    covered: dict[str, list[tuple[datetime, datetime]]] = {
        heater_id: [] for heater_id in enabled_ids
    }

    store = LearningStore(db_path, timezone)
    try:
        rows = await store.get_water_heater_energy_range(bucket_start, end)
    finally:
        await store.close()

    current_fingerprint = boundary_fingerprint(config)
    for row in rows:
        row_start = _as_local_datetime(row.get("slot_start"), timezone)
        row_end = _as_local_datetime(row.get("slot_end"), timezone)
        if row_start is None:
            continue
        if row_end is None or row_end <= row_start:
            row_end = row_start + timedelta(minutes=15)
        if row_start < bucket_start or row_end > end:
            continue
        device_energy = row.get("energy")
        if isinstance(device_energy, dict):
            energy_by_id = cast("dict[str, Any]", device_energy)
            for heater_id in enabled_ids:
                entry: Any = energy_by_id.get(heater_id)
                if not isinstance(entry, dict):
                    continue
                energy_entry = cast("dict[str, Any]", entry)
                if not energy_entry.get("coverage"):
                    continue
                cutoff_kw = float(
                    next(
                        heater.get("idle_power_threshold_kw", DEFAULT_IDLE_POWER_THRESHOLD_KW)
                        for heater in heaters
                        if str(heater["id"]) == heater_id
                    )
                )
                if float(energy_entry["idle_power_threshold_kw"]) != cutoff_kw:
                    continue
                values[heater_id] += float(energy_entry["energy_kwh"])
                covered[heater_id].append((row_start, row_end))
                sources[heater_id].add(str(energy_entry["source"]))
        elif (
            len(heaters) == 1
            and float(heaters[0].get("idle_power_threshold_kw", 0.0)) == 0.0
            and row.get("coverage") == "measured"
            and row.get("boundary_fingerprint") == current_fingerprint
            and row.get("water_kwh") is not None
        ):
            heater_id = enabled_ids[0]
            values[heater_id] += max(0.0, float(row["water_kwh"]))
            covered[heater_id].append((row_start, row_end))
            sources[heater_id].add("legacy")

    sensor_ids = list(
        dict.fromkeys(str(heater["sensor"]) for heater in heaters if heater.get("sensor"))
    )
    history_start = bucket_start - timedelta(minutes=1)
    history = (
        await get_power_history_batch(sensor_ids, history_start, end)
        if sensor_ids and bucket_start < end
        else None
    )
    results: list[dict[str, Any]] = []
    duration = max(0.0, (end - bucket_start).total_seconds())
    for heater in heaters:
        heater_id = str(heater["id"])
        sensor = str(heater.get("sensor", ""))
        cutoff_kw = float(heater.get("idle_power_threshold_kw", DEFAULT_IDLE_POWER_THRESHOLD_KW))
        known_seconds = sum(
            (covered_end - covered_start).total_seconds()
            for covered_start, covered_end in _merge_intervals(covered[heater_id])
        )
        if history is not None and sensor:
            states = history.get(sensor, [])
            for gap_start, gap_end in _gaps(bucket_start, end, covered[heater_id]):
                added_kwh, added_seconds = _history_energy(
                    states, gap_start, gap_end, cutoff_kw, timezone
                )
                values[heater_id] += added_kwh
                known_seconds += added_seconds
                if added_seconds:
                    sources[heater_id].add("power_history")
        coverage = (
            "complete"
            if duration == 0 or known_seconds >= duration - 0.001
            else "partial"
            if known_seconds > 0
            else "unavailable"
        )
        live_power = (current_power_kw or {}).get(heater_id)
        # Normalization has already zeroed values below the cutoff. Keep exact
        # zero inactive when the backward-compatible cutoff is zero.
        active: bool | None = None if live_power is None else live_power > 0.0
        source = "+".join(sorted(sources[heater_id])) if sources[heater_id] else "unknown"
        if coverage != "complete":
            logger.warning(
                "Water heater %s progress has %s history coverage before %s (%s kWh credited)",
                heater_id,
                coverage,
                local_cutoff.isoformat(),
                values[heater_id],
            )
        results.append(
            {
                "id": heater_id,
                "heated_today_kwh": values[heater_id],
                "progress_source": source,
                "progress_coverage": coverage,
                "active_heating": active,
            }
        )
    return results
