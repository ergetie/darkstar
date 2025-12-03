import pandas as pd
from typing import Dict, Any, Optional
from .types import KeplerInput, KeplerInputSlot, KeplerConfig, KeplerResult

def planner_to_kepler_input(
    df: pd.DataFrame, 
    initial_soc_kwh: float
) -> KeplerInput:
    """
    Convert Planner DataFrame to KeplerInput.
    Expects DataFrame index to be timestamps (start_time).
    """
    slots = []
    
    # Ensure required columns exist, fill with 0 if missing
    required_cols = ["load_forecast_kwh", "pv_forecast_kwh", "import_price_sek_kwh"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = 0.0
            
    # Handle export price
    if "export_price_sek_kwh" not in df.columns:
        df["export_price_sek_kwh"] = df["import_price_sek_kwh"]

    # Iterate over DataFrame rows
    # Assuming index is start_time
    for start_time, row in df.iterrows():
        # Calculate end_time (assume next row start or +15min/1h)
        if "end_time" in df.columns:
            end_time = row["end_time"]
        else:
            end_time = start_time + pd.Timedelta(minutes=15)

        # Prefer adjusted forecasts (safety margins applied) if available
        load = float(row.get("adjusted_load_kwh", row.get("load_forecast_kwh", 0.0)))
        pv = float(row.get("adjusted_pv_kwh", row.get("pv_forecast_kwh", 0.0)))
        
        # Add water heating load if present (pre-calculated by heuristic pass)
        water_kw = float(row.get("water_heating_kw", 0.0))
        # Assuming 15-min slots (0.25h). If duration varies, we should use (end-start).
        # But planner usually works on 15-min.
        slot_hours = (end_time - start_time).total_seconds() / 3600.0
        load += water_kw * slot_hours

        slots.append(KeplerInputSlot(
            start_time=start_time,
            end_time=end_time,
            load_kwh=load,
            pv_kwh=pv,
            import_price_sek_kwh=float(row["import_price_sek_kwh"]),
            export_price_sek_kwh=float(row["export_price_sek_kwh"])
        ))

    return KeplerInput(slots=slots, initial_soc_kwh=initial_soc_kwh)

def config_to_kepler_config(planner_config: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> KeplerConfig:
    """
    Convert the main config dictionary to KeplerConfig.
    """
    system = planner_config.get("system", {})
    battery = system.get("battery", planner_config.get("battery", {}))
    learning = planner_config.get("learning", {})
    
    # Apply overrides if present (specifically for 'kepler' section)
    # The Strategy Engine returns a deep dict, e.g. {'kepler': {'wear_cost_sek_per_kwh': 0.0}}
    kepler_overrides = {}
    if overrides and "kepler" in overrides:
        kepler_overrides = overrides["kepler"]
    
    capacity = float(battery.get("capacity_kwh", 0.0))
    
    # Efficiency: try roundtrip first, then separate
    roundtrip = float(battery.get("roundtrip_efficiency_percent", 95.0))
    eff_one_way = (roundtrip / 100.0) ** 0.5
    
    # Helper to get value with override priority
    def get_val(key: str, default: float) -> float:
        if key in kepler_overrides:
            return float(kepler_overrides[key])
        return default

    # For wear cost, default comes from learning config
    default_wear = float(learning.get("default_battery_cost_sek_per_kwh", 0.0))
    
    return KeplerConfig(
        capacity_kwh=capacity,
        min_soc_percent=float(battery.get("min_soc_percent", 10.0)),
        max_soc_percent=float(battery.get("max_soc_percent", 100.0)),
        max_charge_power_kw=float(battery.get("max_charge_power_kw", 0.0)),
        max_discharge_power_kw=float(battery.get("max_discharge_power_kw", 0.0)),
        charge_efficiency=eff_one_way,
        discharge_efficiency=eff_one_way,
        wear_cost_sek_per_kwh=get_val("wear_cost_sek_per_kwh", default_wear),
        max_export_power_kw=float(system.get("grid", {}).get("max_power_kw")) if system.get("grid", {}).get("max_power_kw") else None,
        max_import_power_kw=float(system.get("grid", {}).get("max_power_kw")) if system.get("grid", {}).get("max_power_kw") else None,
        ramping_cost_sek_per_kw=get_val("ramping_cost_sek_per_kw", 0.0),
        export_threshold_sek_per_kwh=get_val("export_threshold_sek_per_kwh", 0.0),
        grid_import_limit_kw=float(planner_config.get("grid", {}).get("import_limit_kw")) if planner_config.get("grid", {}).get("import_limit_kw") else None
    )

def kepler_result_to_dataframe(result: KeplerResult, capacity_kwh: float = 0.0, initial_soc_kwh: float = 0.0) -> pd.DataFrame:
    """
    Convert KeplerResult to a DataFrame suitable for logging/comparison.
    Matches the column structure expected by the UI.
    """
    records = []
    prev_soc_kwh = initial_soc_kwh
    
    for s in result.slots:
        # Calculate kW from kWh (assuming uniform duration for now, or use s.end-s.start)
        duration_h = (s.end_time - s.start_time).total_seconds() / 3600.0
        if duration_h <= 0:
            duration_h = 0.25 # Fallback
            
        charge_kw = s.charge_kwh / duration_h
        discharge_kw = s.discharge_kwh / duration_h
        
        # Determine action label
        action = "Hold"
        if charge_kw > 0.01:
            action = "Charge"
        elif discharge_kw > 0.01:
            if s.grid_export_kwh > 0.01:
                action = "Export"
            else:
                action = "Discharge"
        
        # Calculate entry SoC for this slot
        entry_soc_kwh = prev_soc_kwh
        entry_soc_percent = (entry_soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0
        
        # Update prev_soc_kwh for next slot (Kepler result soc_kwh is end of slot)
        prev_soc_kwh = s.soc_kwh
        
        records.append({
            "start_time": s.start_time,
            "end_time": s.end_time,
            
            # Kepler specific (for debug/shadow)
            "kepler_charge_kwh": s.charge_kwh,
            "kepler_discharge_kwh": s.discharge_kwh,
            "kepler_import_kwh": s.grid_import_kwh,
            "kepler_export_kwh": s.grid_export_kwh,
            "kepler_soc_kwh": s.soc_kwh,
            "kepler_cost_sek": s.cost_sek,
            
            # Legacy UI columns
            "battery_charge_kw": charge_kw,
            "battery_discharge_kw": discharge_kw,
            "charge_kw": min(s.charge_kwh, s.grid_import_kwh) / duration_h,  # Legacy grid charge (approx)
            "projected_soc_kwh": s.soc_kwh,
            "projected_soc_percent": (s.soc_kwh / capacity_kwh * 100.0) if capacity_kwh > 0 else 0.0,
            # "soc_target_percent": ... # Removed simple alias, will be calculated by planner
            "_entry_soc_percent": entry_soc_percent,
            "action": action,
            
            # Grid interaction (legacy usually calculates this later or has it)
            "grid_import_kw": s.grid_import_kwh / duration_h,
            "grid_export_kw": s.grid_export_kwh / duration_h,
            "import_kwh": s.grid_import_kwh,
            "export_kwh": s.grid_export_kwh,
            
            # Placeholders for features not yet in Kepler (Water, etc.)
            "water_heating_kw": 0.0,
            "water_from_grid_kwh": 0.0,
            "water_from_pv_kwh": 0.0,
            "water_from_battery_kwh": 0.0,
            
            # Placeholder for cost basis (not tracked by Kepler explicitly yet)
            "projected_battery_cost": 0.0, 
        })
    
    df = pd.DataFrame(records)
    if not df.empty:
        df.set_index("start_time", inplace=True)
    return df
