#!/usr/bin/env python3
"""Debug why pv_contribution is 3x expected."""

import json

with open("schedule.json") as f:
    d = json.load(f)

fr = d.get("debug", {}).get("s_index", {}).get("future_risk", {})
pv_c = fr.get("pv_contribution")
pv_r = fr.get("pv_deficit_ratio_weighted")

print(f"pv_contribution: {pv_c}")
print(f"pv_deficit_ratio_weighted: {pv_r}")
print(f"effective_weight: {pv_c / pv_r:.4f}")
print(f"planned_at: {d.get('meta', {}).get('planned_at')}")
print(f"risk_factor: {fr.get('risk_factor')}")
print(f"target_soc: {d.get('debug', {}).get('s_index', {}).get('soc_target_percent')}%")
