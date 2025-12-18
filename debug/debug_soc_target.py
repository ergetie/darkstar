#!/usr/bin/env python3
"""
Debug script to investigate end-of-day SOC target calculation.
Traces the full flow: s_index -> risk_factor -> target_soc
"""

import json
import yaml
from datetime import datetime, timedelta
from pprint import pprint

import pytz

from inputs import get_all_input_data
from planner.inputs.data_prep import prepare_df
from planner.inputs.weather import fetch_temperature_forecast
from planner.strategy.s_index import (
    calculate_dynamic_s_index,
    calculate_probabilistic_s_index,
    calculate_target_soc_risk_factor,
    calculate_dynamic_target_soc,
)


def main():
    print("=" * 70)
    print("🔍 DEBUG: End-of-Day SOC Target Investigation")
    print("=" * 70)

    # Load config
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    timezone_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(timezone_name)
    now = datetime.now(tz)

    print(f"\n📅 Current Time: {now.isoformat()}")
    print(f"   Timezone: {timezone_name}")

    # === CONFIG VALUES ===
    print("\n" + "=" * 70)
    print("📋 CONFIGURATION VALUES")
    print("=" * 70)

    s_index_cfg = config.get("s_index", {})
    battery_cfg = config.get("battery", {})

    print(f"\n[s_index]")
    print(f"   mode: {s_index_cfg.get('mode')}")
    print(f"   risk_appetite: {s_index_cfg.get('risk_appetite')}")
    print(f"   base_factor: {s_index_cfg.get('base_factor')}")
    print(f"   max_factor: {s_index_cfg.get('max_factor')}")
    print(f"   soc_scaling_factor: {s_index_cfg.get('soc_scaling_factor')}")
    print(f"   temp_weight: {s_index_cfg.get('temp_weight')}")
    print(f"   temp_baseline_c: {s_index_cfg.get('temp_baseline_c')}")
    print(f"   temp_cold_c: {s_index_cfg.get('temp_cold_c')}")
    print(f"   pv_deficit_weight: {s_index_cfg.get('pv_deficit_weight')}")

    print(f"\n[battery]")
    print(f"   capacity_kwh: {battery_cfg.get('capacity_kwh')}")
    print(f"   min_soc_percent: {battery_cfg.get('min_soc_percent')}")

    # === FETCH LIVE DATA ===
    print("\n" + "=" * 70)
    print("📡 FETCHING LIVE DATA")
    print("=" * 70)

    try:
        input_data = get_all_input_data("config.yaml")
        df = prepare_df(input_data, timezone_name)
        print(f"   ✅ Got {len(df)} slots of data")
        print(f"   Date range: {df.index.min()} → {df.index.max()}")
    except Exception as e:
        print(f"   ❌ Failed to fetch data: {e}")
        return

    # === TEMPERATURE FORECAST ===
    print("\n" + "=" * 70)
    print("🌡️  TEMPERATURE FORECAST (D1, D2)")
    print("=" * 70)

    try:
        temps = fetch_temperature_forecast([1, 2], tz, config)
        print(f"   D1 (Tomorrow): {temps.get(1)}°C")
        print(f"   D2 (Day After): {temps.get(2)}°C")
    except Exception as e:
        print(f"   ❌ Failed to fetch temperature: {e}")
        temps = {}

    # === S-INDEX CALCULATION ===
    print("\n" + "=" * 70)
    print("📊 S-INDEX CALCULATION")
    print("=" * 70)

    mode = s_index_cfg.get("mode", "dynamic")
    max_factor = float(s_index_cfg.get("max_factor", 1.5))

    if mode == "probabilistic":
        print(f"\n   Mode: PROBABILISTIC (Sigma Scaling)")
        factor, s_debug = calculate_probabilistic_s_index(
            df, s_index_cfg, max_factor, timezone_name
        )
        print(f"   Result Factor: {factor}")
        print(f"\n   Debug:")
        pprint(s_debug, indent=6)
    else:
        print(f"\n   Mode: DYNAMIC (Legacy)")
        factor, s_debug, temps_map = calculate_dynamic_s_index(
            df,
            s_index_cfg,
            max_factor,
            timezone_name,
            fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(days, t, config),
        )
        print(f"   Result Factor: {factor}")
        print(f"\n   Debug:")
        pprint(s_debug, indent=6)

    # === TARGET SOC RISK FACTOR (NEW FUNCTION) ===
    print("\n" + "=" * 70)
    print("⚠️  TARGET SOC RISK FACTOR (NEW) - Incorporates risk_appetite + PV")
    print("=" * 70)

    risk_factor, risk_debug = calculate_target_soc_risk_factor(
        df,
        s_index_cfg,
        timezone_name,
        fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(days, t, config),
    )
    print(f"\n   Risk Factor: {risk_factor}")
    print(f"\n   Debug:")
    pprint(risk_debug, indent=6)

    # === DYNAMIC TARGET SOC ===
    print("\n" + "=" * 70)
    print("🎯 DYNAMIC TARGET SOC (End-of-Day)")
    print("=" * 70)

    target_soc_pct, target_soc_kwh, soc_debug = calculate_dynamic_target_soc(
        risk_factor, battery_cfg, s_index_cfg
    )
    print(f"\n   Target SOC: {target_soc_pct:.1f}%")
    print(f"   Target SOC: {target_soc_kwh:.2f} kWh")
    print(f"\n   Debug:")
    pprint(soc_debug, indent=6)

    # === FORMULA BREAKDOWN ===
    print("\n" + "=" * 70)
    print("📐 FORMULA BREAKDOWN")
    print("=" * 70)

    min_soc = float(battery_cfg.get("min_soc_percent", 12))
    soc_scaling = float(s_index_cfg.get("soc_scaling_factor", 50))

    print(f"\n   Target % = min_soc + max(0, (risk_factor - 1.0) * soc_scaling)")
    print(f"   Target % = {min_soc} + max(0, ({risk_factor:.4f} - 1.0) * {soc_scaling})")
    print(f"   Target % = {min_soc} + max(0, {risk_factor - 1.0:.4f} * {soc_scaling})")
    print(f"   Target % = {min_soc} + {max(0, (risk_factor - 1.0) * soc_scaling):.2f}")
    print(f"   Target % = {target_soc_pct:.2f}%")

    # === CHECK: Does calculate_future_risk_factor use PV or risk_appetite? ===
    print("\n" + "=" * 70)
    print("❓ ISSUE ANALYSIS: What affects calculate_future_risk_factor?")
    print("=" * 70)

    print(
        """
    Looking at s_index.py `calculate_future_risk_factor()`:
    
    - It uses: base_factor, max_factor, temp_weight, temp_baseline_c, temp_cold_c
    - It fetches: D2 temperature only
    - It calculates: raw_factor = base_factor + (temp_weight * temp_adjustment)
    
    ❌ It does NOT use:
       - risk_appetite (only used in probabilistic S-Index for load inflation)
       - pv_deficit_weight (only used in dynamic S-Index for load inflation)
       - PV forecasts
       
    This means the End-of-Day Target SOC is ONLY affected by:
       1. s_index.base_factor
       2. s_index.temp_weight
       3. D2 temperature forecast
       4. s_index.soc_scaling_factor
       5. battery.min_soc_percent
    """
    )

    print("\n" + "=" * 70)
    print("✅ INVESTIGATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
