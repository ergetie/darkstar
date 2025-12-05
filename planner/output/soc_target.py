"""
SoC Target Calculation

Derives per-slot soc_target_percent based on Kepler actions and battery configuration.
This ensures the inverter receives the correct target for each slot type:
- Charge blocks: Target = projected SoC at END of charge block
- Export blocks: Target = projected SoC at END of export block  
- Discharge: Target = min_soc_percent
- Hold: Target = entry SoC (current battery state)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("darkstar.planner.soc_target")


def apply_soc_target_percent(
    df: pd.DataFrame,
    config: Dict[str, Any],
    now_slot: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """
    Derive per-slot SoC target signal based on planner actions and configuration.
    
    This function processes the schedule to set appropriate soc_target_percent
    for each slot based on the action type:
    - Charge blocks: All slots in a charge window use the projected SoC at block end
    - Export blocks: Use projected SoC at block end (with guard floor as minimum)
    - Discharge: Use min_soc_percent
    - Hold: Maintain entry SoC
    
    Args:
        df: Schedule DataFrame with 'action', 'projected_soc_percent', '_entry_soc_percent' columns
        config: Configuration dictionary containing battery settings
        now_slot: Current time slot (for distinguishing historical vs future slots)
        
    Returns:
        DataFrame with 'soc_target_percent' column applied
    """
    if df is None or df.empty:
        if df is not None:
            df["soc_target_percent"] = []
        return df
    
    # Extract required series
    entry_series = df.get("_entry_soc_percent")
    if entry_series is None:
        # Fallback: use projected_soc_percent if entry not available
        df["soc_target_percent"] = df.get("projected_soc_percent", pd.Series([None] * len(df)))
        return df
    
    # Convert to lists for efficient iteration
    entry_list = entry_series.tolist()
    actions = df["action"].tolist() if "action" in df.columns else ["Hold"] * len(df)
    projected = df.get("projected_soc_percent", pd.Series([None] * len(df))).tolist()
    water_kw = df.get("water_heating_kw", pd.Series([0.0] * len(df))).tolist()
    water_from_grid = df.get("water_from_grid_kwh", pd.Series([0.0] * len(df))).tolist()
    water_from_battery = df.get("water_from_battery_kwh", pd.Series([0.0] * len(df))).tolist()
    
    # Manual action support
    manual_series = df.get("manual_action", pd.Series([None] * len(df)))
    manual_actions = [
        m.strip().lower() if isinstance(m, str) else None 
        for m in manual_series.tolist()
    ]
    
    # Battery configuration
    battery_config = config.get("battery", {})
    min_soc_percent = float(battery_config.get("min_soc_percent", 12.0))
    max_soc_percent = float(battery_config.get("max_soc_percent", 100.0))
    capacity_kwh = float(battery_config.get("capacity_kwh", 34.2))
    
    # Manual planning configuration
    manual_cfg = config.get("manual_planning", {}) or {}
    
    def _clamp(value: Optional[float], fallback: float) -> float:
        """Clamp value to min/max SoC bounds."""
        if value is None:
            return fallback
        try:
            val = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(min_soc_percent, min(max_soc_percent, val))
    
    # Guard floor is minimum safe SoC (at least min_soc_percent)
    guard_floor_percent = min_soc_percent
    
    # Manual targets
    manual_charge_target = _clamp(manual_cfg.get("charge_target_percent"), max_soc_percent)
    manual_export_target = _clamp(manual_cfg.get("export_target_percent"), guard_floor_percent)
    
    # Initialize targets array with min_soc
    targets: List[float] = [min_soc_percent for _ in range(len(df))]
    
    # Determine now position for historical vs future slot handling
    index_list = list(df.index)
    if now_slot is None and index_list:
        now_slot = index_list[0]
    
    try:
        now_pos = index_list.index(now_slot) if now_slot in index_list else -1
    except (ValueError, TypeError):
        now_pos = -1
    
    # Preserve historical slot targets using entry values
    if now_pos >= 0:
        for i in range(now_pos):
            entry = entry_list[i]
            if entry is not None:
                targets[i] = float(entry)
    
    # Initial pass: Set action-specific defaults
    start_idx = max(now_pos, 0)
    
    # Set current slot target to entry if available
    if 0 <= now_pos < len(df):
        current_entry = entry_list[now_pos]
        if current_entry is not None:
            targets[now_pos] = float(current_entry)
    
    # Action-specific defaults for future slots
    for i in range(start_idx, len(df)):
        action = actions[i]
        entry = entry_list[i]
        
        if action == "Hold" and entry is not None:
            targets[i] = float(entry)
        elif action == "Export":
            if manual_actions[i] == "export":
                targets[i] = manual_export_target
            else:
                targets[i] = guard_floor_percent
        elif action == "Discharge":
            targets[i] = min_soc_percent
    
    # =========================================================================
    # Charge Block Logic
    # Group charge slots into blocks (allow 1-slot gaps)
    # Set all slots in block to projected SoC at block END
    # =========================================================================
    charge_indices = [idx for idx, a in enumerate(actions) if a == "Charge"]
    
    if charge_indices:
        blocks = _group_into_blocks(charge_indices, max_gap=1)
        
        for block in blocks:
            if not block:
                continue
            start = block[0]
            end = block[-1]
            
            # Use projected SoC at END of the charge block as target
            block_target = projected[end]
            if block_target is None:
                block_target = projected[start]
            if block_target is None and entry_list[start] is not None:
                block_target = entry_list[start]
            
            block_value = float(block_target) if block_target is not None else targets[start]
            block_value = max(min_soc_percent, min(max_soc_percent, block_value))
            
            # Apply manual constraints if present
            if any(manual_actions[k] == "charge" for k in block):
                block_value = min(block_value, manual_charge_target)
            
            # Apply target to ALL slots in the block (including gaps)
            for j in range(start, end + 1):
                targets[j] = block_value
    
    # =========================================================================
    # Export Block Logic
    # Group export slots into blocks
    # Set target to projected SoC at block END (with guard floor as minimum)
    # =========================================================================
    i = start_idx
    while i < len(df):
        if actions[i] == "Export":
            start = i
            manual_block = manual_actions[i] == "export"
            
            # Find end of export block
            while i + 1 < len(df) and actions[i + 1] == "Export":
                i += 1
                if manual_actions[i] == "export":
                    manual_block = True
            end = i
            
            # Calculate block target
            if manual_block:
                block_value = manual_export_target
            else:
                end_projected = projected[end]
                if end_projected is not None:
                    block_value = max(guard_floor_percent, float(end_projected))
                else:
                    block_value = guard_floor_percent
            
            # Apply to all slots in export block
            for j in range(start, end + 1):
                targets[j] = block_value
            i += 1
        else:
            i += 1
    
    # =========================================================================
    # Water Heating Block Logic
    # Differentiate battery vs grid supply
    # =========================================================================
    i = start_idx
    while i < len(df):
        if water_kw[i] > 0:
            start = i
            has_battery = water_from_battery[i] > 0
            has_grid = water_from_grid[i] > 0
            
            # Find end of water heating block
            while i + 1 < len(df) and water_kw[i + 1] > 0:
                i += 1
                has_battery = has_battery or water_from_battery[i] > 0
                has_grid = has_grid or water_from_grid[i] > 0
            end = i
            
            if has_battery:
                # Battery-powered water heating: use min_soc
                for j in range(start, end + 1):
                    targets[j] = min_soc_percent
            elif has_grid:
                # Grid-powered water heating: maintain entry SoC  
                block_entry = entry_list[start]
                block_value = float(block_entry) if block_entry is not None else targets[start]
                for j in range(start, end + 1):
                    if actions[j] != "Charge":
                        targets[j] = max(targets[j], block_value)
            i += 1
        else:
            i += 1
    
    # =========================================================================
    # Hold Slot Final Pass
    # Ensure Hold slots show entry SoC (current battery state)
    # =========================================================================
    for i in range(len(df)):
        if actions[i] == "Hold":
            entry = entry_list[i]
            if entry is not None:
                targets[i] = float(entry)
    
    # Apply targets to DataFrame
    df["soc_target_percent"] = [round(float(val), 2) for val in targets]
    
    # Clean up internal columns from output
    drop_candidates = ["_entry_soc_percent", "_entry_soc_kwh"]
    existing = [col for col in drop_candidates if col in df.columns]
    if existing:
        df = df.drop(columns=existing)
    
    return df


def _group_into_blocks(indices: List[int], max_gap: int = 1) -> List[List[int]]:
    """
    Group indices into contiguous blocks, allowing for small gaps.
    
    Args:
        indices: Sorted list of indices
        max_gap: Maximum allowed gap between indices to still be in same block
        
    Returns:
        List of blocks, where each block is a list of indices
    """
    if not indices:
        return []
    
    blocks = []
    current_block = [indices[0]]
    
    for idx in indices[1:]:
        if idx <= current_block[-1] + max_gap + 1:
            current_block.append(idx)
        else:
            blocks.append(current_block)
            current_block = [idx]
    
    blocks.append(current_block)
    return blocks
