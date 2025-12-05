"""
Water Heating Scheduling Helpers

Pure helper functions for water heating slot selection and block consolidation.
Extracted from planner_legacy.py during Rev K13 modularization.

Note: The main scheduling logic (_pass_2_schedule_water_heating) remains in 
planner_legacy.py due to tight coupling with HeliosPlanner class state.
These helpers are used by that method.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def build_water_segments(
    cheap_slots_sorted: pd.DataFrame,
    slot_duration: pd.Timedelta,
    max_gap_slots: int,
    tolerance: float,
) -> List[Dict[str, Any]]:
    """
    Break cheap slots into contiguous segments respecting tolerance/gap.
    
    Args:
        cheap_slots_sorted: DataFrame of cheap slots sorted by time
        slot_duration: Duration of each time slot
        max_gap_slots: Max slots to bridge within a segment
        tolerance: Price tolerance for segment grouping
        
    Returns:
        List of segment dicts with 'slots' (list of timestamps) and 'avg_price'
    """
    slots = []
    max_gap = max(0, int(max_gap_slots or 0))
    allowed_gap = slot_duration * max(1, max_gap + 1)
    tolerance = max(0.0, tolerance or 0.0)

    current_segment: List[Tuple[pd.Timestamp, float]] = []
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


def find_best_merge(
    blocks: List[List[pd.Timestamp]],
    cheap_slots_sorted: pd.DataFrame,
    slot_duration: pd.Timedelta,
) -> Optional[int]:
    """
    Find the best pair of blocks to merge with minimal cost penalty.

    Args:
        blocks: List of blocks (each block is list of slot times)
        cheap_slots_sorted: Cheap slots with price data
        slot_duration: Duration of each slot

    Returns:
        Index of first block to merge (None if no good merge found)
    """
    if len(blocks) < 2:
        return None

    best_merge_idx = None
    best_merge_cost = float("inf")

    for i in range(len(blocks) - 1):
        block1 = blocks[i]
        block2 = blocks[i + 1]

        # Calculate cost of current arrangement
        current_cost = calculate_block_cost(
            block1, cheap_slots_sorted
        ) + calculate_block_cost(block2, cheap_slots_sorted)

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


def calculate_block_cost(
    block: List[pd.Timestamp],
    cheap_slots_sorted: pd.DataFrame,
) -> float:
    """
    Calculate the total cost of a block of water heating slots.
    
    Args:
        block: List of timestamps in the block
        cheap_slots_sorted: DataFrame with price data
        
    Returns:
        Total cost (sum of prices for slots in block)
    """
    if not block:
        return 0.0
    
    total_cost = 0.0
    for slot_time in block:
        if slot_time in cheap_slots_sorted.index:
            total_cost += cheap_slots_sorted.loc[slot_time, "import_price_sek_kwh"]
    return total_cost


def merge_blocks(
    blocks: List[List[pd.Timestamp]],
    merge_idx: int,
) -> List[List[pd.Timestamp]]:
    """
    Merge two adjacent blocks at the specified index.

    Args:
        blocks: List of blocks
        merge_idx: Index of first block to merge

    Returns:
        Updated blocks list
    """
    if merge_idx >= len(blocks) - 1:
        return blocks

    merged_block = blocks[merge_idx] + blocks[merge_idx + 1]
    return blocks[:merge_idx] + [merged_block] + blocks[merge_idx + 2:]


def get_consolidation_params(
    water_heating_config: Dict[str, Any],
    charging_strategy: Dict[str, Any],
) -> Tuple[float, int]:
    """
    Get tolerance and gap configuration for water block consolidation.
    
    Args:
        water_heating_config: Water heating section of config
        charging_strategy: Charging strategy section of config
        
    Returns:
        Tuple of (tolerance, max_gap_slots)
    """
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
