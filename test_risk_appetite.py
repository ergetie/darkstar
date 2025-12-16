#!/usr/bin/env python3
"""Test script to verify risk_appetite affects target SOC properly."""

import yaml
import pytz
from datetime import datetime

from inputs import get_all_input_data
from planner.inputs.data_prep import prepare_df
from planner.inputs.weather import fetch_temperature_forecast
from planner.strategy.s_index import calculate_target_soc_risk_factor, calculate_dynamic_target_soc

with open('config.yaml') as f:
    config = yaml.safe_load(f)

timezone_name = config.get('timezone', 'Europe/Stockholm')
input_data = get_all_input_data('config.yaml')
df = prepare_df(input_data, timezone_name)

battery_cfg = config.get('battery', {})
s_index_base = config.get('s_index', {})

print('Testing risk_appetite effect on target SOC:')
print('=' * 70)

for appetite in [1, 2, 3, 4, 5]:
    s_cfg = s_index_base.copy()
    s_cfg['risk_appetite'] = appetite
    
    risk_factor, debug = calculate_target_soc_risk_factor(
        df, s_cfg, timezone_name,
        fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(days, t, config)
    )
    
    target_pct, target_kwh, soc_debug = calculate_dynamic_target_soc(risk_factor, battery_cfg, s_cfg)
    
    print(f'Level {appetite}: mult={debug["buffer_multiplier"]:.2f}, adjusted_buf={debug["adjusted_buffer"]:+.3f}, risk_factor={risk_factor:.4f} -> Target SOC: {target_pct:.1f}%')

print()
print('Key debug values (Level 3 - Neutral):')
s_cfg = s_index_base.copy()
s_cfg['risk_appetite'] = 3
risk_factor, debug = calculate_target_soc_risk_factor(
    df, s_cfg, timezone_name,
    fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(days, t, config)
)
print(f'  raw_factor: {debug["raw_factor"]}')
print(f'  buffer_above_one: {debug["buffer_above_one"]}')
print(f'  pv_contribution: {debug["pv_contribution"]}')
print(f'  temp_contribution: {debug["temp_contribution"]}')
