## Why

The stabilization-review-2 findings ledger (#12, #14, #15, #16) proved that the water-heating comfort model is partly fictional and one solver economic tiebreak is inverted:

- **#14 (root cause of #12):** the "max gap between heating" comfort protection **does not exist in the solver**. `max_hours_between_heating` is parsed and plumbed into `KeplerConfig.water_heating_max_gap_hours` (`planner/solver/types.py:73`) but **no constraint or objective term in `kepler.py` ever reads it**. The legacy penalty is hardcoded `gap_violation_penalty = 0.0` (`kepler.py:557`) and added to the objective twice (`kepler.py:632-633`). A designed linear-discomfort replacement existed (commit `af214dc8`, 2026-01-23, O(T) and performance-safe) but was **lost in a same-day refactor** — not removed on purpose.
- **#12 (the symptom):** with no gap term, the solver's optimum is to bunch the day's heating into the cheapest window and satisfy only the daily-total minimum. Production data showed **95 gaps > 8 h** (12–26 per non-vacation month, typically 9–18 h) — water can be cold in the evening even though the daily kWh quota was met.
- **#15:** the global `water_heating.*` penalty keys in config (`reliability_penalty_sek: 1000`, `block_start_penalty_sek`, `spacing_penalty_sek`, and also `block_penalty_sek`) are **never read** — all water penalties are derived from `comfort_level` via `COMFORT_MAP` (`adapter.py:277-314`). The operator believes a 1000 SEK "Must Have" penalty guards the daily minimum; the solver actually uses 15 SEK. The config and UI are lying about what controls behavior.
- **#16:** at export price ≤ 0, exporting PV costs 0 while curtailing costs `curtailment_penalty_sek` (0.1 SEK/kWh), so the solver **pays the grid up to 0.1 SEK/kWh to export** instead of curtailing (58 production slots exported at price ≤ 0). The "waste penalty" is applied even when exporting is worse than wasting.

This is the second recommended fix change from the review (`fix-observability-gaps` is first). It is scoped to the solver and its config/UI surface — no executor or recorder changes.

## What Changes

1. **Reinstate a gap-comfort penalty in the Kepler solver** using the linear-discomfort-counter formulation (per-device), with a **deadband at `max_hours_between_heating`**: gaps up to the ceiling are free, gaps beyond it accrue a soft cost. This finally makes `water_heating_max_gap_hours` a live input.
2. **`comfort_level` scales only the gap penalty weight, not the ceiling** (Design A, ratified 2026-07-05). A new `water_gap_penalty_sek` column is added to `COMFORT_MAP`; the ceiling stays exactly what the operator set in `max_hours_between_heating`. (Design B — level also shortens the ceiling — was rejected as it re-hides the explicit dial.)
3. **Preserve all existing anti-sawtooth and anti-long-block behavior unchanged**: hard `water_min_spacing_hours` (floor), block-start penalty, and `max_block_hours` block-breaker all remain exactly as-is. The gap penalty is purely additive.
4. **Remove the fictional config keys** (`water_heating.reliability_penalty_sek`, `.block_start_penalty_sek`, `.spacing_penalty_sek`, `.block_penalty_sek`) from `config.default.yaml` and the settings UI, and remove the dead `KeplerConfig.water_comfort_penalty_sek` field and the doubled `gap_violation_penalty` objective lines. The config/UI surface must reflect the real controls: `comfort_level`, `max_hours_between_heating`, `min_kwh_per_day`, `water_min_spacing_hours`, `power_kw`.
5. **Fix the curtailment/export tiebreak (#16):** curtailment must be preferred over exporting whenever the effective export price is ≤ 0, so the solver never pays to export.

## Capabilities

### New Capabilities
- `curtailment-price-floor`: The solver SHALL prefer curtailing surplus PV over exporting it whenever exporting would cost money (effective export price ≤ 0).

### Modified Capabilities
- `per-device-water-scheduling`: adds a per-device gap-comfort penalty with a deadband, defines `comfort_level` as the gap-penalty-weight scaler, and removes the fictional global penalty config keys in favor of the real control surface.

## Impact

- **Solver:** `planner/solver/kepler.py` (add discomfort/gap-over variables + constraints + objective term; fix curtailment tiebreak; delete doubled dead line), `planner/solver/types.py` (add `water_gap_penalty_sek` to `KeplerConfig`, remove dead `water_comfort_penalty_sek`), `planner/solver/adapter.py` (add `water_gap_penalty_sek` column to `COMFORT_MAP`, wire it into `KeplerConfig`).
- **Config:** `config.default.yaml` (remove 4 dead `water_heating.*` keys; the `max_hours_between_heating` and `comfort_level` comments become accurate).
- **Frontend:** `frontend/src/config-help.json`, `frontend/src/pages/settings/types.ts` (remove the 3 UI fields for the dead keys).
- **Tests:** `tests/planner/` water-solver and Kepler tests (new gap-behavior tests; update any test asserting the dead keys / deprecated field).
- **No behavior change** for executor, recorder, or ML. Vacation mode and bulk mode (`enable_top_ups: false`) continue to disable the gap penalty (they already zero `water_heating_max_gap_hours`).
