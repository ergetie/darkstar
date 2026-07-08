"""
Kepler Adapter Module

Convert between Planner DataFrame format and Kepler solver types.
Migrated from backend/kepler/adapter.py during Rev K13 modularization.
"""

import logging
from datetime import datetime  # noqa: TC003
from typing import Any, cast

import pandas as pd

from .types import (
    EVChargerInput,
    ExcessPVSinkEntry,
    KeplerConfig,
    KeplerInput,
    KeplerInputSlot,
    KeplerResult,
    WaterHeaterInput,
)

logger = logging.getLogger(__name__)


def _get_config_version(config: dict[str, Any]) -> int:
    """Detect config format version for ARC15 migration compatibility."""
    return int(config.get("config_version", 1))


def build_water_heater_inputs(
    water_heaters_config: list[dict[str, Any]],
    global_wh_cfg: dict[str, Any] | None = None,
    water_heater_states: list[dict[str, Any]] | None = None,
) -> list[WaterHeaterInput]:
    """
    Build per-device WaterHeaterInput list from water_heaters[] config + state.

    Args:
        water_heaters_config: List of water heater config dicts from config.yaml
        global_wh_cfg: Global water_heating section (for enable_top_ups, spacing override)
        water_heater_states: Optional per-device state dicts.
            Each dict should have: id, heated_today_kwh (float), force_on_slots (list[int] | None)
            If None or empty, defaults are used.

    Returns:
        List of WaterHeaterInput objects for enabled heaters with power_kw > 0.
    """
    enabled_wh: list[dict[str, Any]] = [
        wh
        for wh in water_heaters_config
        if wh.get("enabled", True) and float(wh.get("power_kw", 0.0)) > 0
    ]

    if not enabled_wh:
        return []

    global_cfg = global_wh_cfg or {}
    enable_top_ups: bool = bool(global_cfg.get("enable_top_ups", True))

    # Build state lookup by heater ID
    state_by_id: dict[str, dict[str, Any]] = {}
    if water_heater_states:
        for s in water_heater_states:
            heater_id = s.get("id", "")
            if heater_id:
                state_by_id[heater_id] = s

    result: list[WaterHeaterInput] = []
    for wh in enabled_wh:
        heater_id: str = str(wh.get("id", ""))
        if not heater_id:
            continue

        # The config array uses 'water_min_spacing_hours' (with prefix) - handle both
        spacing_hours_raw: Any = wh.get("water_min_spacing_hours") or wh.get("min_spacing_hours")
        spacing_hours: float = float(spacing_hours_raw or 5.0)

        # When top-ups disabled globally, disable per-device spacing too
        if not enable_top_ups:
            spacing_hours = 0.0

        state = state_by_id.get(heater_id, {})
        heated_today = float(state.get("heated_today_kwh", 0.0))
        force_on_slots: list[int] | None = state.get("force_on_slots")

        result.append(
            WaterHeaterInput(
                id=heater_id,
                power_kw=float(wh.get("power_kw", 3.0)),
                min_kwh_per_day=float(wh.get("min_kwh_per_day", 0.0)),
                max_hours_between_heating=float(wh.get("max_hours_between_heating", 8.0)),
                min_spacing_hours=spacing_hours,
                force_on_slots=force_on_slots if force_on_slots else None,
                heated_today_kwh=heated_today,
            )
        )

    return result


def build_ev_charger_inputs(
    ev_chargers_config: list[dict[str, Any]],
    ev_charger_states: list[dict[str, Any]] | None = None,
) -> list[EVChargerInput]:
    """
    Build per-device EVChargerInput list from ev_chargers[] config + HA state.

    Args:
        ev_chargers_config: List of ev_charger config dicts from config.yaml
        ev_charger_states: Optional list of per-device HA state dicts.
            Each dict should have: id, soc_percent, plugged_in, deadline (optional)
            If None or empty, HA state defaults are used (0% SoC, not plugged in).

    Returns:
        List of EVChargerInput objects for enabled chargers.
        Chargers not plugged in are still included (solver skips them internally).
    """
    enabled_ev: list[dict[str, Any]] = [ev for ev in ev_chargers_config if ev.get("enabled", True)]

    # Filter out chargers registered as disabled (missing/zero max_power_kw)
    enabled_ev = [ev for ev in enabled_ev if not ev.get("disabled_reason")]

    # Build state lookup by charger ID
    state_by_id: dict[str, dict[str, Any]] = {}
    if ev_charger_states:
        for s in ev_charger_states:
            charger_id = s.get("id", "")
            if charger_id:
                state_by_id[charger_id] = s

    result: list[EVChargerInput] = []
    for ev in enabled_ev:
        charger_id: str = ev.get("id", "")
        if not charger_id:
            continue

        state = state_by_id.get(charger_id, {})

        soc_percent = float(state.get("soc_percent", 0.0))
        plugged_in = bool(state.get("plugged_in", False))
        deadline = state.get("deadline")  # datetime | None
        required_kwh = state.get("required_kwh")
        daily_quota_kwh = state.get("daily_quota_kwh")
        keep_on_after_target = bool(state.get("keep_on_after_target", False))

        result.append(
            EVChargerInput(
                id=charger_id,
                max_power_kw=float(ev.get("max_power_kw") or 0.0),
                battery_capacity_kwh=float(ev.get("battery_capacity_kwh", 0.0)),
                current_soc_percent=soc_percent,
                plugged_in=plugged_in,
                deadline=deadline,
                required_kwh=float(required_kwh) if required_kwh is not None else None,
                daily_quota_kwh=float(daily_quota_kwh) if daily_quota_kwh is not None else None,
                keep_on_after_target=keep_on_after_target,
                control_type=str(ev.get("type", "binary")).lower(),
            )
        )

    return result


def build_excess_pv_priority(excess_pv_cfg: dict[str, Any]) -> list[ExcessPVSinkEntry]:
    """Map executor.excess_pv.priority[] config into solver-side ExcessPVSinkEntry list.

    Computes each entry's rank-scaled effective reward in this single place
    (task 2.2): `override if set, else boost_reward_sek_per_kwh * (1 - rank * 0.15)`,
    floored at 0. Rank is the entry's position in the priority list (0 = highest).
    """
    base_reward = float(excess_pv_cfg.get("boost_reward_sek_per_kwh", 0.5) or 0.0)
    priority_raw: Any = excess_pv_cfg.get("priority")
    entries: list[ExcessPVSinkEntry] = []
    if not isinstance(priority_raw, list):
        return entries
    priority_list = cast("list[Any]", priority_raw)

    for rank, entry_raw in enumerate(priority_list):
        if not isinstance(entry_raw, dict):
            continue
        entry = cast("dict[str, Any]", entry_raw)
        entry_type = str(entry.get("type", "")).lower()
        if entry_type not in ("ev", "water_heater_boost", "custom_entity"):
            logger.warning("Ignoring excess_pv.priority[] entry with unknown type: %r", entry_type)
            continue

        override = entry.get("reward_sek_per_kwh")
        if override is not None:
            effective_reward = max(0.0, float(override))
        else:
            effective_reward = max(0.0, base_reward * (1 - rank * 0.15))

        entries.append(
            ExcessPVSinkEntry(
                type=entry_type,
                effective_reward_sek_per_kwh=effective_reward,
                charger_id=cast("str | None", entry.get("charger_id")),
                power_kw=float(entry.get("power_kw", 1.0)),
            )
        )

    return entries


def planner_to_kepler_input(
    df: pd.DataFrame,
    initial_soc_kwh: float,
    max_dc_input_kw: float | None = None,
) -> KeplerInput:
    """
    Convert Planner DataFrame to KeplerInput.
    Expects DataFrame index to be timestamps (start_time).

    Args:
        df: DataFrame with forecast data
        initial_soc_kwh: Initial battery state of charge in kWh
        max_dc_input_kw: Maximum DC power from PV strings (clips PV forecast)
    """
    slots: list[KeplerInputSlot] = []

    # Ensure required columns exist
    required_cols = ["load_forecast_kwh", "pv_forecast_kwh", "import_price_sek_kwh"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = 0.0

    if "export_price_sek_kwh" not in df.columns:
        df["export_price_sek_kwh"] = df["import_price_sek_kwh"]

    for idx, row in df.iterrows():
        start_time: datetime = idx  # type: ignore[assignment]
        if "end_time" in df.columns:
            end_time: datetime = row["end_time"]  # type: ignore[assignment]
        else:
            end_time = start_time + pd.Timedelta(minutes=15)

        # Prefer adjusted forecasts if available (already represents Base Load)
        load = float(row.get("adjusted_load_kwh", row.get("load_forecast_kwh", 0.0)))
        pv = float(row.get("adjusted_pv_kwh", row.get("pv_forecast_kwh", 0.0)))

        # PV DC clipping: limit PV to max DC input capacity
        if max_dc_input_kw is not None:
            slot_hours = (end_time - start_time).total_seconds() / 3600.0
            max_pv_kwh = max_dc_input_kw * slot_hours
            if pv > max_pv_kwh:
                original_pv = pv
                pv = max_pv_kwh
                logger.debug(
                    f"PV clipped from {original_pv:.3f} to {pv:.3f} kWh at {start_time} "
                    f"(max_dc={max_dc_input_kw}kW)"
                )

        slots.append(
            KeplerInputSlot(
                start_time=start_time,
                end_time=end_time,
                load_kwh=load,
                pv_kwh=pv,
                import_price_sek_kwh=float(row["import_price_sek_kwh"]),
                export_price_sek_kwh=float(row["export_price_sek_kwh"]),
            )
        )

    return KeplerInput(slots=slots, initial_soc_kwh=initial_soc_kwh)  # type: ignore[arg-type]


def _comfort_level_to_penalty(
    comfort_level: int, daily_kwh: float = 0.0, heater_power_kw: float = 0.0
) -> dict[str, float]:
    """Map comfort level (1-5) to penalty configuration and dynamic window size.

    Level 1: Economy - comfort is nice-to-have, large windows for bulk heating
    Level 5: Maximum - almost hard constraint, small windows for frequent heating

    Args:
        comfort_level: 1-5 comfort level
        daily_kwh: Daily water heating requirement
        heater_power_kw: Water heater power rating
    """
    # Comfort multipliers for window sizing
    COMFORT_MULTIPLIERS = {
        1: 1.5,  # Economy: Larger windows = bulk heating in cheapest period
        2: 1.0,  # Balanced: Moderate windows
        3: 0.8,  # Neutral: Slight spacing preference
        4: 0.5,  # Priority: More frequent heating
        5: 0.25,  # Maximum: Very frequent = stable temperature
    }

    # Calculate dynamic window size
    if daily_kwh > 0 and heater_power_kw > 0:
        min_heating_hours = daily_kwh / heater_power_kw
        multiplier = COMFORT_MULTIPLIERS.get(comfort_level, 0.8)
        max_block_hours = min_heating_hours * multiplier
    else:
        # Fallback to current behavior if parameters missing
        max_block_hours = 2.0

    # Penalty parameters explained:
    # - water_reliability_penalty_sek: Applied ONCE PER DAY when daily minimum (min_kwh_per_day) is not met.
    #   Higher values = stricter enforcement of daily heating requirement.
    #   Example: 300 SEK = 300 SEK total penalty if day fails to meet minimum.
    # - water_block_start_penalty_sek: Applied ONCE PER HEATING BLOCK when a new heating session starts.
    #   Higher values = preference for fewer, longer blocks vs many short blocks.
    #   Example: 1.5 SEK = 1.5 SEK penalty for each heating block created.
    # - water_block_penalty_sek: Applied PER SLOT when heating block exceeds max_block_hours.
    #   Higher values = stricter enforcement of window size limits.
    #   Example: 10 SEK = 10 SEK penalty for each 15-minute slot that overshoots the window.
    # - max_block_hours: Maximum duration for a single heating block (calculated dynamically).
    #   Smaller values = more frequent heating = more stable temperature.

    COMFORT_MAP = {
        # Level: {reliability, block_start, block, gap_penalty, max_block_hours}
        1: {
            "water_reliability_penalty_sek": 2.0,
            "water_block_start_penalty_sek": 1.5,
            "water_block_penalty_sek": 0.5,
            "water_gap_penalty_sek": 0.5,
            "max_block_hours": max_block_hours,
        },  # Economy
        2: {
            "water_reliability_penalty_sek": 7.0,
            "water_block_start_penalty_sek": 2.25,
            "water_block_penalty_sek": 1.0,
            "water_gap_penalty_sek": 2.0,
            "max_block_hours": max_block_hours,
        },  # Balanced
        3: {
            "water_reliability_penalty_sek": 15.0,
            "water_block_start_penalty_sek": 3.0,
            "water_block_penalty_sek": 2.0,
            "water_gap_penalty_sek": 5.0,
            "max_block_hours": max_block_hours,
        },  # Neutral
        4: {
            "water_reliability_penalty_sek": 30.0,
            "water_block_start_penalty_sek": 4.5,
            "water_block_penalty_sek": 5.0,
            "water_gap_penalty_sek": 15.0,
            "max_block_hours": max_block_hours,
        },  # Priority
        5: {
            "water_reliability_penalty_sek": 300.0,
            "water_block_start_penalty_sek": 1.0,
            "water_block_penalty_sek": 10.0,
            "water_gap_penalty_sek": 50.0,
            "max_block_hours": max_block_hours,
        },  # Maximum
    }
    # Default to Level 3 (Neutral) if invalid
    params = COMFORT_MAP.get(comfort_level, COMFORT_MAP[3]).copy()
    return params


def _apply_bulk_mode_override(params: dict[str, float]) -> dict[str, float]:
    """Apply bulk heating mode override - forces single block behavior.

    Overrides ONLY block-related parameters while preserving reliability penalties.
    This allows users to request bulk heating (single block) while maintaining
    their chosen reliability level (e.g., Level 5 + bulk mode = strict reliability
    but consolidated heating).

    Args:
        params: Penalty parameters from comfort level

    Returns:
        Modified parameters with bulk mode overrides
    """
    params["max_block_hours"] = 24.0  # Allow entire day as one block
    params["water_block_penalty_sek"] = 0.0  # No penalty for long blocks
    # Keep water_reliability_penalty_sek and water_block_start_penalty_sek unchanged
    return params


def config_to_kepler_config(
    planner_config: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    slots: list[Any] | None = None,
    water_heater_states: list[dict[str, Any]] | None = None,
    ev_charger_states: list[dict[str, Any]] | None = None,
) -> KeplerConfig:
    """
    Convert the main config dictionary to KeplerConfig.

    Args:
        planner_config: Main configuration dictionary
        overrides: Optional runtime overrides
        slots: Optional list of KeplerInputSlot (Legacy argument, currently unused)
    """
    system = planner_config.get("system", {})
    battery = system.get("battery", planner_config.get("battery", {}))

    kepler_overrides: dict[str, Any] = {}
    if overrides and "kepler" in overrides:
        kepler_overrides = overrides["kepler"]

    def get_val(key: str, default: float) -> float:
        # Check runtime overrides first, then config file, then default
        # Check kepler_overrides (legacy support)
        if key in kepler_overrides:
            return float(kepler_overrides[key])

        val = planner_config.get(key)
        # Check overrides (standard)
        if overrides and key in overrides:
            val = overrides[key]
        return float(val) if val is not None else default

    # ARC15: Detect config format and load water heating settings
    config_version = _get_config_version(planner_config)
    water_heaters_cfg = planner_config.get("water_heaters", [])
    ev_chargers = planner_config.get("ev_chargers", [])
    global_wh = planner_config.get("water_heating", {})

    # Build per-device WaterHeaterInput list
    if config_version >= 2 and water_heaters_cfg:
        water_inputs = build_water_heater_inputs(water_heaters_cfg, global_wh, water_heater_states)
    else:
        # Legacy format: no per-device support
        water_inputs = []

    # For global comfort settings, use the water_heating section
    wh_cfg = global_wh

    # ARC15: Load EV charging settings (per-device)
    if config_version >= 2 and ev_chargers:
        ev_inputs = build_ev_charger_inputs(ev_chargers, ev_charger_states)
    else:
        ev_inputs = []

    capacity = float(battery.get("capacity_kwh", 13.5))
    charge_eff = float(battery.get("charge_efficiency", 0.95))
    discharge_eff = float(battery.get("discharge_efficiency", 0.95))
    battery_cycle_cost_kwh = float(
        planner_config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.0)
    )
    resolved_wear_cost = get_val("wear_cost_sek_per_kwh", battery_cycle_cost_kwh)

    # Dynamic Power Limits (Rev F17)
    # Hardware limits (Amps or Watts) drive the Optimizer limits (kW)
    inverter_cfg = planner_config.get("executor", {}).get("inverter", {})
    control_unit = inverter_cfg.get("control_unit", "A")

    if control_unit == "W":
        max_charge_kw = float(battery.get("max_charge_w", 0.0)) / 1000.0
        max_discharge_kw = float(battery.get("max_discharge_w", 0.0)) / 1000.0
    else:
        # Amps mode - use nominal voltage for planning
        voltage = float(battery.get("nominal_voltage_v", battery.get("system_voltage_v", 48.0)))
        max_charge_kw = (float(battery.get("max_charge_a", 0.0)) * voltage) / 1000.0
        max_discharge_kw = (float(battery.get("max_discharge_a", 0.0)) * voltage) / 1000.0

    kepler_cfg = KeplerConfig(
        capacity_kwh=capacity,
        min_soc_percent=float(battery.get("min_soc_percent", 10.0)),
        max_soc_percent=float(battery.get("max_soc_percent", 100.0)),
        max_charge_power_kw=max_charge_kw,
        max_discharge_power_kw=max_discharge_kw,
        charge_efficiency=charge_eff,
        discharge_efficiency=discharge_eff,
        wear_cost_sek_per_kwh=max(battery_cycle_cost_kwh, resolved_wear_cost),
        max_export_power_kw=(
            float(system.get("grid", {}).get("max_power_kw"))
            if system.get("grid", {}).get("max_power_kw")
            else None
        ),
        max_import_power_kw=(
            float(system.get("grid", {}).get("max_power_kw"))
            if system.get("grid", {}).get("max_power_kw")
            else None
        ),
        max_inverter_ac_kw=(
            float(system.get("inverter", {}).get("max_ac_power_kw"))
            if system.get("inverter", {}).get("max_ac_power_kw")
            else None
        ),
        inverter_topology=str(system.get("inverter", {}).get("topology", "dc_coupled")),
        ramping_cost_sek_per_kw=float(
            planner_config.get("kepler", {}).get(
                "ramping_cost_sek_per_kw", get_val("ramping_cost_sek_per_kw", 0.05)
            )
        ),
        curtailment_penalty_sek=float(
            planner_config.get("kepler", {}).get("curtailment_penalty_sek", 0.1)
        ),
        ev_shortfall_penalty_sek_per_kwh=float(
            planner_config.get("kepler", {}).get("ev_shortfall_penalty_sek_per_kwh", 50.0)
        ),
        export_threshold_sek_per_kwh=get_val("export_threshold_sek_per_kwh", 0.0),
        # Per-device water heater inputs
        water_heaters=water_inputs,
        # Global water heating settings
        # PRODUCTION FIX B1: Disable gap constraint when enable_top_ups=false
        water_heating_max_gap_hours=float(
            wh_cfg.get("max_hours_between_heating", 8.0)
            if wh_cfg.get("enable_top_ups", True)
            else 0.0
        ),
        # Rev K23: Multi-Parameter Comfort Control (ALWAYS applied)
        # Rev K24: Apply bulk mode override if enable_top_ups=false
        # Use total power/daily_kwh across all heaters for max_block_hours calculation
        **(  # type: ignore[arg-type]
            _apply_bulk_mode_override(
                _comfort_level_to_penalty(
                    int(wh_cfg.get("comfort_level", 3)),
                    daily_kwh=sum(h.min_kwh_per_day for h in water_inputs),
                    heater_power_kw=sum(h.power_kw for h in water_inputs),
                )
            )
            if not wh_cfg.get("enable_top_ups", True)
            else _comfort_level_to_penalty(
                int(wh_cfg.get("comfort_level", 3)),
                daily_kwh=sum(h.min_kwh_per_day for h in water_inputs),
                heater_power_kw=sum(h.power_kw for h in water_inputs),
            )
        ),
        defer_up_to_hours=float(wh_cfg.get("defer_up_to_hours", 0.0)),
        # Rev E4: Export Toggle
        enable_export=bool(planner_config.get("export", {}).get("enable_export", True)),
        # Export SoC Floor: minimum SoC required to allow grid export
        export_floor_soc_percent=(
            float(planner_config.get("export", {}).get("export_floor_soc_percent"))
            if planner_config.get("export", {}).get("export_floor_soc_percent") is not None
            else None
        ),
        # Per-device EV charger inputs (multi-device support)
        ev_chargers=ev_inputs,
        # Excess PV dispatch
        excess_pv_slots=[],  # Populated by pipeline after forecast analysis
        excess_pv_priority=build_excess_pv_priority(
            planner_config.get("executor", {}).get("excess_pv", {})
        ),
        excess_pv_soc_threshold_percent=float(
            planner_config.get("executor", {})
            .get("excess_pv", {})
            .get("soc_threshold_percent", 95.0)
        ),
    )

    return kepler_cfg


def kepler_result_to_dataframe(
    result: KeplerResult, capacity_kwh: float = 0.0, initial_soc_kwh: float = 0.0
) -> pd.DataFrame:
    """
    Convert KeplerResult to a DataFrame suitable for logging/comparison.
    Matches the column structure expected by the UI.
    """
    records: list[dict[str, Any]] = []
    prev_soc_kwh = initial_soc_kwh

    for s in result.slots:
        duration_h = (s.end_time - s.start_time).total_seconds() / 3600.0
        if duration_h <= 0:
            duration_h = 0.25

        charge_kw = s.charge_kwh / duration_h
        discharge_kw = s.discharge_kwh / duration_h

        action = "Hold"
        if charge_kw > 0.01:
            action = "Charge"
        elif discharge_kw > 0.01:
            action = "Export" if s.grid_export_kwh > 0.01 else "Discharge"

        entry_soc_kwh = prev_soc_kwh
        entry_soc_percent = (entry_soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0
        prev_soc_kwh = s.soc_kwh

        records.append(  # type: ignore[arg-type]
            {
                "start_time": s.start_time,
                "end_time": s.end_time,
                "kepler_charge_kwh": s.charge_kwh,
                "kepler_discharge_kwh": s.discharge_kwh,
                "kepler_import_kwh": s.grid_import_kwh,
                "kepler_export_kwh": s.grid_export_kwh,
                "kepler_soc_kwh": s.soc_kwh,
                "kepler_cost_sek": s.cost_sek,
                "planned_cost_sek": (s.grid_import_kwh * s.import_price_sek_kwh)
                - (s.grid_export_kwh * s.export_price_sek_kwh),
                "battery_charge_kw": charge_kw,
                "battery_discharge_kw": discharge_kw,
                "discharge_kw": discharge_kw,  # Alias for simulation.py compatibility
                "charge_kw": min(s.charge_kwh, s.grid_import_kwh) / duration_h,
                "projected_soc_kwh": s.soc_kwh,
                "projected_soc_percent": (
                    (s.soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0
                ),
                "_entry_soc_percent": entry_soc_percent,
                "action": action,
                "grid_import_kw": s.grid_import_kwh / duration_h,
                "grid_export_kw": s.grid_export_kwh / duration_h,
                "import_kwh": s.grid_import_kwh,
                "export_kwh": s.grid_export_kwh,
                "water_heating_kw": s.water_heat_kw,  # Aggregate (backward compat)
                "water_heaters": s.water_heater_results,  # Per-device: heater_id -> kW
                "water_heating_boost": s.water_heating_boost,  # Per-device: heater_id -> bool
                "custom_entity_active": s.custom_entity_active,  # Whether custom entity should be on
                "water_from_grid_kwh": 0.0,
                "water_from_pv_kwh": 0.0,
                "water_from_battery_kwh": 0.0,
                "ev_charging_kw": s.ev_charge_kw,  # Aggregate EV charging power (backward compat)
                "ev_chargers": s.ev_charger_results,  # Per-device: charger_id -> kW
                "ev_surplus_kw": s.ev_surplus_kw,  # Per-charger: charger_id -> surplus-eligible kW
                "projected_battery_cost": 0.0,
            }
        )

    df = pd.DataFrame(records)  # type: ignore[arg-type]
    if not df.empty:
        df.set_index("start_time", inplace=True)
    return df
