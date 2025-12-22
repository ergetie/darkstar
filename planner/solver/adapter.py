"""
Kepler Adapter Module

Convert between Planner DataFrame format and Kepler solver types.
Migrated from backend/kepler/adapter.py during Rev K13 modularization.
"""

import pandas as pd
from typing import Dict, Any, Optional
from .types import KeplerInput, KeplerInputSlot, KeplerConfig, KeplerResult


def planner_to_kepler_input(df: pd.DataFrame, initial_soc_kwh: float) -> KeplerInput:
    """
    Convert Planner DataFrame to KeplerInput.
    Expects DataFrame index to be timestamps (start_time).
    """
    slots = []

    # Ensure required columns exist
    required_cols = ["load_forecast_kwh", "pv_forecast_kwh", "import_price_sek_kwh"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = 0.0

    if "export_price_sek_kwh" not in df.columns:
        df["export_price_sek_kwh"] = df["import_price_sek_kwh"]

    for start_time, row in df.iterrows():
        if "end_time" in df.columns:
            end_time = row["end_time"]
        else:
            end_time = start_time + pd.Timedelta(minutes=15)

        # Prefer adjusted forecasts if available
        load = float(row.get("adjusted_load_kwh", row.get("load_forecast_kwh", 0.0)))
        pv = float(row.get("adjusted_pv_kwh", row.get("pv_forecast_kwh", 0.0)))

        # Add water heating load if present
        water_kw = float(row.get("water_heating_kw", 0.0))
        slot_hours = (end_time - start_time).total_seconds() / 3600.0
        load += water_kw * slot_hours

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

    return KeplerInput(slots=slots, initial_soc_kwh=initial_soc_kwh)


def _comfort_level_to_penalty(comfort_level: int) -> float:
    """Map comfort level (1-5) to gap penalty (SEK/hour beyond threshold).
    
    Level 1: Economy - comfort is nice-to-have
    Level 5: Maximum - almost hard constraint
    """
    COMFORT_PENALTY_MAP = {
        1: 0.05,   # Economy
        2: 0.20,   # Balanced
        3: 0.50,   # Neutral
        4: 1.00,   # Priority
        5: 3.00,   # Maximum
    }
    return COMFORT_PENALTY_MAP.get(comfort_level, 0.50)


def config_to_kepler_config(
    planner_config: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None
) -> KeplerConfig:
    """
    Convert the main config dictionary to KeplerConfig.
    """
    system = planner_config.get("system", {})
    battery = system.get("battery", planner_config.get("battery", {}))
    learning = planner_config.get("learning", {})

    kepler_overrides = {}
    if overrides and "kepler" in overrides:
        kepler_overrides = overrides["kepler"]

    # Also read from config.yaml kepler section
    kepler_config = planner_config.get("kepler", {})

    capacity = float(battery.get("capacity_kwh", 0.0))
    roundtrip = float(battery.get("roundtrip_efficiency_percent", 95.0))
    eff_one_way = (roundtrip / 100.0) ** 0.5

    def get_val(key: str, default: float) -> float:
        # Check runtime overrides first, then config file, then default
        if key in kepler_overrides:
            return float(kepler_overrides[key])
        if key in kepler_config:
            return float(kepler_config[key])
        return default

    # Wear cost (battery degradation per cycle)
    # Read from battery_economics.battery_cycle_cost_kwh (the correct key)
    battery_economics = planner_config.get("battery_economics", {})
    default_wear = float(battery_economics.get("battery_cycle_cost_kwh", 0.2))

    # Rev K20: Stored energy cost (what energy in battery is "worth")
    # Read from BatteryCostTracker, fallback to config default
    # This value is used as terminal_value to prevent wasteful discharge
    stored_energy_cost = 1.0  # Conservative default
    if kepler_config.get("use_stored_energy_cost", True):
        try:
            from backend.battery_cost import BatteryCostTracker
            db_path = learning.get("sqlite_path", "data/planner_learning.db")
            tracker = BatteryCostTracker(db_path, capacity)
            state = tracker.get_state()
            if state.get("updated_at") is not None:
                stored_energy_cost = state["avg_cost_sek_per_kwh"]
        except Exception:
            pass  # Keep default

    return KeplerConfig(
        capacity_kwh=capacity,
        min_soc_percent=float(battery.get("min_soc_percent", 10.0)),
        max_soc_percent=float(battery.get("max_soc_percent", 100.0)),
        max_charge_power_kw=float(battery.get("max_charge_power_kw", 0.0)),
        max_discharge_power_kw=float(battery.get("max_discharge_power_kw", 0.0)),
        charge_efficiency=eff_one_way,
        discharge_efficiency=eff_one_way,
        wear_cost_sek_per_kwh=get_val("wear_cost_sek_per_kwh", default_wear),
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
        ramping_cost_sek_per_kw=get_val("ramping_cost_sek_per_kw", 0.0),
        export_threshold_sek_per_kwh=get_val("export_threshold_sek_per_kwh", 0.0),
        # Rev K20: terminal_value = stored_energy_cost
        # This ensures Kepler values battery energy correctly and won't discharge at a loss
        terminal_value_sek_kwh=stored_energy_cost,
        grid_import_limit_kw=(
            float(planner_config.get("grid", {}).get("import_limit_kw"))
            if planner_config.get("grid", {}).get("import_limit_kw")
            else None
        ),
        # Water heating as deferrable load (Rev K17/K18)
        water_heating_power_kw=float(
            planner_config.get("water_heating", {}).get("power_kw", 0.0)
        ),
        water_heating_min_kwh=float(
            planner_config.get("water_heating", {}).get("min_kwh_per_day", 0.0)
        ),
        water_heating_max_gap_hours=float(
            planner_config.get("water_heating", {}).get("max_hours_between_heating", 8.0)
        ),
        water_heated_today_kwh=0.0,  # Set in pipeline from HA sensor
        water_comfort_penalty_sek=_comfort_level_to_penalty(
            int(planner_config.get("water_heating", {}).get("comfort_level", 3))
        ),
    )


def kepler_result_to_dataframe(
    result: KeplerResult, capacity_kwh: float = 0.0, initial_soc_kwh: float = 0.0
) -> pd.DataFrame:
    """
    Convert KeplerResult to a DataFrame suitable for logging/comparison.
    Matches the column structure expected by the UI.
    """
    records = []
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
            if s.grid_export_kwh > 0.01:
                action = "Export"
            else:
                action = "Discharge"

        entry_soc_kwh = prev_soc_kwh
        entry_soc_percent = (entry_soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0
        prev_soc_kwh = s.soc_kwh

        records.append(
            {
                "start_time": s.start_time,
                "end_time": s.end_time,
                "kepler_charge_kwh": s.charge_kwh,
                "kepler_discharge_kwh": s.discharge_kwh,
                "kepler_import_kwh": s.grid_import_kwh,
                "kepler_export_kwh": s.grid_export_kwh,
                "kepler_soc_kwh": s.soc_kwh,
                "kepler_cost_sek": s.cost_sek,
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
                "water_heating_kw": s.water_heat_kw,  # From Kepler MILP (Rev K17)
                "water_from_grid_kwh": 0.0,
                "water_from_pv_kwh": 0.0,
                "water_from_battery_kwh": 0.0,
                "projected_battery_cost": 0.0,
            }
        )

    df = pd.DataFrame(records)
    if not df.empty:
        df.set_index("start_time", inplace=True)
    return df
