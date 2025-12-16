#!/usr/bin/env python3
"""Debug why API shows different pv_contribution."""
import yaml

from inputs import get_all_input_data
from planner.inputs.data_prep import prepare_df
from planner.inputs.weather import fetch_temperature_forecast
from planner.strategy.s_index import calculate_target_soc_risk_factor

with open('config.yaml') as f:
    config = yaml.safe_load(f)

timezone_name = config.get('timezone', 'Europe/Stockholm')
input_data = get_all_input_data('config.yaml')
df = prepare_df(input_data, timezone_name)

s_index_cfg = config.get('s_index', {}).copy()

print('Config values:')
print(f'  base_factor: {s_index_cfg.get("base_factor")}')
print(f'  pv_deficit_weight: {s_index_cfg.get("pv_deficit_weight")}')  
print(f'  temp_weight: {s_index_cfg.get("temp_weight")}')
print(f'  max_factor: {s_index_cfg.get("max_factor")}')
print(f'  risk_appetite: {s_index_cfg.get("risk_appetite")}')

risk_factor, debug = calculate_target_soc_risk_factor(
    df, s_index_cfg, timezone_name,
    fetch_temperature_fn=lambda days, t: fetch_temperature_forecast(days, t, config)
)

print()
print('Calculated values:')
print(f'  base_factor: {debug["base_factor"]}')
print(f'  pv_deficit_ratio: {debug["pv_deficit_ratio_weighted"]}')
print(f'  pv_contribution: {debug["pv_contribution"]}')  
print(f'  temp_contribution: {debug["temp_contribution"]}')
print(f'  raw_factor: {debug["raw_factor"]}')
print(f'  buffer_above_one: {debug["buffer_above_one"]}')
print(f'  buffer_multiplier: {debug["buffer_multiplier"]}')
print(f'  risk_factor: {debug["risk_factor"]}')
print(f'  (with risk_appetite={debug["risk_appetite"]})')

# Manually calculate what pv_contribution SHOULD be
expected_pv = s_index_cfg.get('pv_deficit_weight', 0.2) * debug['pv_deficit_ratio_weighted']
print()
print(f'Expected pv_contribution: {expected_pv:.4f}')
print(f'Actual pv_contribution:   {debug["pv_contribution"]:.4f}')
