"""
Water Heating Scheduling

Handles water heating scheduling logic, including slot selection,
block consolidation, and historical usage tracking.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import pytz


def build_water_segments(
    cheap_slots_sorted: pd.DataFrame,
    slot_duration: pd.Timedelta,
    max_gap_slots: int,
    tolerance: float,
) -> list[dict[str, Any]]:
    """
    Break cheap slots into contiguous segments respecting tolerance/gap.
    """
    slots = []
    max_gap = max(0, int(max_gap_slots or 0))
    allowed_gap = slot_duration * max(1, max_gap + 1)
    tolerance = max(0.0, tolerance or 0.0)

    current_segment: list[tuple[pd.Timestamp, float]] = []
    prev_slot_time = None
    current_min = None
    current_max = None

    for slot_time, row in cheap_slots_sorted.iterrows():
        slot_price = float(row["import_price_sek_kwh"])
        if not current_segment:
            current_segment = [(slot_time, slot_price)]
            current_min = slot_price
            current_max = slot_price
        else:
            gap = slot_time - prev_slot_time
            candidate_min = min(current_min, slot_price)
            candidate_max = max(current_max, slot_price)
            price_span = candidate_max - candidate_min
            if gap <= allowed_gap and price_span <= tolerance:
                current_segment.append((slot_time, slot_price))
                current_min = candidate_min
                current_max = candidate_max
            else:
                slots.append(current_segment)
                current_segment = [(slot_time, slot_price)]
                current_min = slot_price
                current_max = slot_price
        prev_slot_time = slot_time

    if current_segment:
        slots.append(current_segment)

    segments = []
    for block in slots:
        times = [entry[0] for entry in block]
        prices = [entry[1] for entry in block]
        avg_price = float(sum(prices) / len(prices)) if prices else float("inf")
        segments.append({"slots": times, "avg_price": avg_price})

    segments.sort(key=lambda seg: (seg["avg_price"], seg["slots"][0]))
    return segments


def calculate_block_cost(
    block: list[pd.Timestamp],
    cheap_slots_sorted: pd.DataFrame,
) -> float:
    """Calculate the total cost of a block of water heating slots."""
    if not block:
        return 0.0

    total_cost = 0.0
    for slot_time in block:
        if slot_time in cheap_slots_sorted.index:
            total_cost += cheap_slots_sorted.loc[slot_time, "import_price_sek_kwh"]
    return total_cost


def find_best_merge(
    blocks: list[list[pd.Timestamp]],
    cheap_slots_sorted: pd.DataFrame,
    slot_duration: pd.Timedelta,
) -> int | None:
    """Find the best pair of blocks to merge with minimal cost penalty."""
    if len(blocks) < 2:
        return None

    best_merge_idx = None
    best_merge_cost = float("inf")

    for i in range(len(blocks) - 1):
        block1 = blocks[i]
        block2 = blocks[i + 1]

        # Calculate cost of current arrangement
        current_cost = calculate_block_cost(block1, cheap_slots_sorted) + calculate_block_cost(
            block2, cheap_slots_sorted
        )

        # Calculate cost if merged (need to fill gap)
        gap_start = block1[-1] + slot_duration
        gap_end = block2[0]
        gap_slots_needed = int((gap_end - gap_start) / slot_duration)

        # Find cheapest slots to fill the gap
        gap_cost = 0.0
        if gap_slots_needed > 0:
            gap_slots = cheap_slots_sorted[
                (cheap_slots_sorted.index >= gap_start) & (cheap_slots_sorted.index < gap_end)
            ].head(gap_slots_needed)
            gap_cost = gap_slots["import_price_sek_kwh"].sum()

        merged_cost = current_cost + gap_cost

        if merged_cost < best_merge_cost:
            best_merge_cost = merged_cost
            best_merge_idx = i

    return best_merge_idx


def merge_blocks(
    blocks: list[list[pd.Timestamp]],
    merge_idx: int,
) -> list[list[pd.Timestamp]]:
    """Merge two adjacent blocks at the specified index."""
    if merge_idx >= len(blocks) - 1:
        return blocks

    merged_block = blocks[merge_idx] + blocks[merge_idx + 1]
    return blocks[:merge_idx] + [merged_block] + blocks[merge_idx + 2 :]


def should_merge_water_blocks(
    block_a: list[pd.Timestamp],
    block_b: list[pd.Timestamp],
    tolerance: float,
    max_gap_slots: int,
    slot_duration: pd.Timedelta,
    cheap_slots_sorted: pd.DataFrame,
) -> bool:
    """Decide if two blocks should be merged based on price span and gap size."""
    if not block_a or not block_b:
        return False
    delta_seconds = (block_b[0] - block_a[-1]).total_seconds()
    slot_seconds = slot_duration.total_seconds() if slot_duration.total_seconds() > 0 else 900
    gap_slots = max(0, int(round(delta_seconds / slot_seconds)) - 1)
    if gap_slots > max_gap_slots:
        return False

    combined = block_a + block_b
    combined_index = pd.Index(combined)
    prices = cheap_slots_sorted.reindex(combined_index)["import_price_sek_kwh"].dropna()
    if prices.empty:
        return False
    price_span = prices.max() - prices.min()
    return price_span <= tolerance + 1e-9


def merge_water_blocks_by_tolerance(
    blocks: list[list[pd.Timestamp]],
    tolerance: float,
    max_gap_slots: int,
    slot_duration: pd.Timedelta,
    cheap_slots_sorted: pd.DataFrame,
) -> list[list[pd.Timestamp]]:
    """Merge adjacent blocks when price spread + gap constraints allow it."""
    if not blocks or len(blocks) < 2:
        return blocks
    if tolerance <= 0 and max_gap_slots <= 0:
        return blocks

    merged_any = True
    while merged_any and len(blocks) > 1:
        merged_any = False
        for idx in range(len(blocks) - 1):
            if should_merge_water_blocks(
                blocks[idx],
                blocks[idx + 1],
                tolerance,
                max_gap_slots,
                slot_duration,
                cheap_slots_sorted,
            ):
                blocks = merge_blocks(blocks, idx)
                merged_any = True
                break
    return blocks


def get_consolidation_params(
    water_heating_config: dict[str, Any],
    charging_strategy: dict[str, Any],
) -> tuple[float, int]:
    """Get tolerance and gap configuration for water block consolidation."""
    tolerance = water_heating_config.get("block_consolidation_tolerance_sek")
    if tolerance is None:
        tolerance = charging_strategy.get("block_consolidation_tolerance_sek", 0.0)
    try:
        tolerance = float(tolerance)
    except (TypeError, ValueError):
        tolerance = 0.0

    max_gap = water_heating_config.get("consolidation_max_gap_slots")
    if max_gap is None:
        max_gap = charging_strategy.get("consolidation_max_gap_slots", 0)
    try:
        max_gap = int(max_gap)
    except (TypeError, ValueError):
        max_gap = 0

    return max(0.0, tolerance), max(0, max_gap)


def select_slots_from_segments(
    cheap_slots_sorted: pd.DataFrame,
    slots_needed: int,
    max_blocks_per_day: int,
    slot_duration: pd.Timedelta,
    tolerance: float,
    max_gap_slots: int,
) -> list[pd.Timestamp]:
    """Create slot candidates by combining contiguous segments before falling back."""
    cheap_slots_by_time = cheap_slots_sorted.sort_index()
    segments = build_water_segments(cheap_slots_by_time, slot_duration, max_gap_slots, tolerance)
    if not segments:
        return []

    selected_segments = []
    total_slots = 0
    for segment in segments:
        selected_segments.append(segment)
        total_slots += len(segment["slots"])
        if total_slots >= slots_needed:
            break

    if total_slots < slots_needed:
        return []

    combined = []
    for segment in selected_segments:
        combined.extend(segment["slots"])
    return sorted(combined)


def consolidate_to_blocks(
    selected_slots: list[pd.Timestamp],
    max_blocks: int,
    slot_duration: pd.Timedelta,
    cheap_slots_sorted: pd.DataFrame,
    water_heating_config: dict[str, Any],
    charging_strategy: dict[str, Any],
) -> list[pd.Timestamp]:
    """Group selected slots into up to max_blocks contiguous groups."""
    if len(selected_slots) <= 1:
        return selected_slots

    # Sort by time for block creation
    selected_slots_sorted = sorted(selected_slots)

    # Determine water consolidation parameters
    tolerance, max_gap_slots = get_consolidation_params(water_heating_config, charging_strategy)

    # Create initial blocks
    blocks = []
    current_block = [selected_slots_sorted[0]]
    allowed_gap = slot_duration * max(1, max_gap_slots + 1)

    for slot_time in selected_slots_sorted[1:]:
        gap = slot_time - current_block[-1]
        if len(current_block) > 0 and gap <= allowed_gap:
            current_block.append(slot_time)
        else:
            blocks.append(current_block)
            current_block = [slot_time]

    blocks.append(current_block)

    # Merge blocks if too many
    while len(blocks) > max_blocks:
        merge_idx = find_best_merge(blocks, cheap_slots_sorted, slot_duration)
        if merge_idx is not None:
            blocks = merge_blocks(blocks, merge_idx)
        else:
            break

    # Merge remaining blocks by tolerance
    blocks = merge_water_blocks_by_tolerance(
        blocks, tolerance, max_gap_slots, slot_duration, cheap_slots_sorted
    )

    # Flatten
    consolidated_slots = []
    for block in blocks:
        consolidated_slots.extend(block)

    return consolidated_slots


def select_optimal_water_slots(
    cheap_slots_sorted: pd.DataFrame,
    slots_needed: int,
    max_blocks_per_day: int,
    slot_duration: pd.Timedelta,
    water_heating_config: dict[str, Any],
    charging_strategy: dict[str, Any],
) -> list[pd.Timestamp]:
    """Select optimal water heating slots."""
    if slots_needed <= 0 or cheap_slots_sorted.empty:
        return []

    tolerance, max_gap_slots = get_consolidation_params(water_heating_config, charging_strategy)

    candidate_slots = select_slots_from_segments(
        cheap_slots_sorted,
        slots_needed,
        max_blocks_per_day,
        slot_duration,
        tolerance,
        max_gap_slots,
    )

    if candidate_slots:
        selected_slots = candidate_slots[:slots_needed]
    else:
        selected_slots = []
        for _, slot in cheap_slots_sorted.iterrows():
            selected_slots.append(slot.name)
            if len(selected_slots) >= slots_needed:
                break
        selected_slots = selected_slots[:slots_needed]

    if not selected_slots:
        return []

    ordered_slots = sorted(dict.fromkeys(selected_slots))
    limited_slots = ordered_slots[:slots_needed]

    return consolidate_to_blocks(
        limited_slots,
        max_blocks_per_day,
        slot_duration,
        cheap_slots_sorted,
        water_heating_config,
        charging_strategy,
    )


def get_daily_water_usage_kwh(
    target_date: date,
    learning_config: dict[str, Any],
    ha_water_today: float | None = None,
    today_date: date | None = None,
) -> float:
    """Retrieve recorded water usage for the specified date."""
    if today_date is None:
        today_date = datetime.now(UTC).date()

    if target_date == today_date and ha_water_today is not None:
        return max(0.0, ha_water_today)

    if not learning_config.get("enable", False):
        return 0.0

    db_path = learning_config.get("sqlite_path", "data/learning.db")
    date_key = target_date.isoformat()

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute("SELECT used_kwh FROM daily_water WHERE date = ?", (date_key,))
            row = cur.fetchone()
            if row is not None and row[0] is not None:
                return float(row[0])

            # Initialize if not exists
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_water (date, used_kwh, updated_at)
                VALUES (?, 0, ?)
                """,
                (date_key, datetime.now(UTC).isoformat()),
            )
            conn.commit()
    except Exception:
        pass

    return 0.0


def schedule_water_heating(
    df: pd.DataFrame,
    config: dict[str, Any],
    now_slot: pd.Timestamp,
    ha_water_today: float | None = None,
) -> pd.DataFrame:
    """
    Schedule water heating in contiguous blocks per day.

    Args:
        df: Prepared DataFrame
        config: Full configuration
        now_slot: Current planning slot
        ha_water_today: Water usage today from Home Assistant

    Returns:
        Updated DataFrame with water_heating_kw column
    """
    df = df.copy()
    water_heating_config = config.get("water_heating", {})
    charging_strategy = config.get("charging_strategy", {})
    learning_config = config.get("learning", {})

    timezone_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)

    power_kw = float(water_heating_config.get("power_kw", 3.0))
    min_hours_per_day = float(water_heating_config.get("min_hours_per_day", 2.0))
    min_kwh_per_day = float(
        water_heating_config.get("min_kwh_per_day", power_kw * min_hours_per_day)
    )
    max_blocks_per_day = int(water_heating_config.get("max_blocks_per_day", 2))
    schedule_future_only = True
    defer_up_to_hours = float(water_heating_config.get("defer_up_to_hours", 0))
    plan_days_ahead = int(water_heating_config.get("plan_days_ahead", 1))
    plan_days_ahead = max(0, min(plan_days_ahead, 1))

    slot_minutes = int(config.get("nordpool", {}).get("resolution_minutes", 15) or 15)
    slot_duration = pd.Timedelta(minutes=slot_minutes)
    slot_energy_kwh = power_kw * (slot_duration.total_seconds() / 3600.0)

    slots_for_min_hours = (
        max(1, math.ceil(min_hours_per_day * 60.0 / slot_minutes)) if min_hours_per_day > 0 else 0
    )

    # Build local datetime mapping
    try:
        local_datetimes = df.index.tz_convert(tz)
    except TypeError:
        local_datetimes = df.index.tz_localize(tz)

    df["water_heating_kw"] = 0.0

    try:
        now_local = now_slot.tz_convert(tz)
    except TypeError:
        now_local = now_slot.tz_localize(tz)

    today_local = now_local.normalize()
    global_limit_local = today_local + pd.Timedelta(hours=48)

    daily_water_kwh_today = get_daily_water_usage_kwh(
        today_local.date(), learning_config, ha_water_today, today_local.date()
    )

    def _has_full_price_day(start_local: pd.Timestamp) -> bool:
        base_end = start_local + pd.Timedelta(days=1)
        base_mask = (local_datetimes >= start_local) & (local_datetimes < base_end)
        expected_slots = int(round((base_end - start_local) / slot_duration))
        return base_mask.sum() >= expected_slots

    for day_offset in range(0, plan_days_ahead + 1):
        day_start_local = today_local + pd.Timedelta(days=day_offset)
        if day_start_local >= global_limit_local:
            break

        base_end_local = day_start_local + pd.Timedelta(days=1)
        day_horizon_local = min(
            base_end_local + pd.Timedelta(hours=max(0.0, defer_up_to_hours)), global_limit_local
        )

        day_mask = (local_datetimes >= day_start_local) & (local_datetimes < day_horizon_local)
        day_slots = df.loc[day_mask]
        if day_slots.empty:
            continue

        if day_offset > 0 and not _has_full_price_day(day_start_local):
            continue

        if schedule_future_only:
            day_slots = day_slots[day_slots.index > now_slot]
            if day_slots.empty:
                continue

        if day_offset == 0:
            day_consumed = daily_water_kwh_today
        else:
            day_consumed = get_daily_water_usage_kwh(
                day_start_local.date(), learning_config, None, today_local.date()
            )

        remaining_energy = max(0.0, min_kwh_per_day - day_consumed)

        if remaining_energy <= 0:
            continue

        energy_slots = math.ceil(remaining_energy / slot_energy_kwh) if slot_energy_kwh > 0 else 0
        required_slots = max(slots_for_min_hours, energy_slots, 1)

        cheap_slots = day_slots[day_slots["is_cheap"]].copy()
        if cheap_slots.empty:
            continue

        # Sort cheap slots by price
        cheap_slots_sorted = cheap_slots.sort_values("import_price_sek_kwh")

        selected_slots = select_optimal_water_slots(
            cheap_slots_sorted,
            required_slots,
            max_blocks_per_day,
            slot_duration,
            water_heating_config,
            charging_strategy,
        )

        if not selected_slots:
            continue

        for slot_time in selected_slots:
            if slot_time not in df.index:
                continue
            df.loc[slot_time, "water_heating_kw"] = power_kw

    return df
