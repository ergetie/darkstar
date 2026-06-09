## 1. Fix the constraint

- [x] 1.1 In `planner/solver/kepler.py` (export-floor constraint, ~lines 453–457), change the bound from start-of-slot `soc[t]` to end-of-slot `soc[t + 1]`, keeping the `is_exporting[t]` binary, the `min_soc_kwh` fallback term, and the `- export_floor_violation[t]` slack unchanged.
- [x] 1.2 Confirm the `export_floor_active` gating (`enable_export and export_floor_soc_percent is not None`), the `EXPORT_FLOOR_PENALTY` (1000) objective term, and the `is_exporting` ↔ `grid_export` big-M link are all untouched.
- [x] 1.3 Verify `soc[t + 1]` is valid for every export slot (SoC array spans `range(T + 1)`), including the final slot.

## 2. Tests

- [x] 2.1 Update `tests/planner/test_kepler_export_floor.py` so existing cases assert end-of-slot SoC (`soc[t+1]`) stays at or above the floor while exporting (not start-of-slot).
- [x] 2.2 Add a regression test for the production scenario: `capacity_kwh = 66`, `export_floor_soc_percent = 28`, high discharge power (~16.5 kW) — assert the plan does not export the battery below ~28% within a slot (no ~22% overshoot).
- [x] 2.3 Add/confirm a boundary-slot test: when only partial export keeps `soc[t+1]` at the floor, the solver throttles `grid_export[t]` to land at the floor rather than stopping a full slot early.
- [x] 2.4 Confirm the inactive-path tests still pass (`enable_export = False`, `export_floor_soc_percent = None`) — no `is_exporting` variable, behaviour unchanged.

## 3. Verify

- [x] 3.1 Run the planner test suite (`pytest tests/planner/test_kepler_export_floor.py` and the broader solver tests) and confirm green.
- [x] 3.2 Re-run the beta user's scenario (66 kWh / 28% floor) and confirm planned export now stops at the floor instead of ~22%.
