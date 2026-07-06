# Tasks — fix-water-comfort-truthfulness

Implement in order. Each task is self-contained and verifiable. Read `design.md` for the full rationale and the exact constraint math (Decision 1) and comfort weights (Decision 2). Do NOT change daily-minimum, spacing, block-start, or block-duration behavior — the gap penalty is purely additive.

## 1. Add the gap-penalty config field and wire comfort_level

- [x] 1.1 In `planner/solver/types.py`, in the `KeplerConfig` dataclass (starts line ~47), ADD a new field `water_gap_penalty_sek: float = 0.0` with the comment `# Penalty per hour of gap beyond water_heating_max_gap_hours (0 = disabled); scaled by comfort_level`. Place it next to the existing `water_heating_max_gap_hours` field (line ~73).
- [x] 1.2 In `planner/solver/types.py`, REMOVE the dead field `water_comfort_penalty_sek: float = 0.50` (line ~74). Then grep the whole repo for `water_comfort_penalty_sek` and remove every remaining non-test reference (e.g. `adapter.py:313` sets `params["water_comfort_penalty_sek"] = 0.0` — delete that line). Update any test that references it.
- [x] 1.3 In `planner/solver/adapter.py`, in `COMFORT_MAP` (line ~277), ADD a `"water_gap_penalty_sek"` entry to EACH of the 5 levels with these values: L1=0.5, L2=2.0, L3=5.0, L4=15.0, L5=50.0. Keep all existing keys unchanged. Update the map's header comment (line ~278) to include the new column.
- [x] 1.4 In `planner/solver/adapter.py`, where `KeplerConfig` is constructed (the `**(...comfort...)` spread around line ~461-475 already injects the `COMFORT_MAP` dict), confirm `water_gap_penalty_sek` flows through the spread into `KeplerConfig`. If the spread is filtered to specific keys, add `water_gap_penalty_sek` to the allowed set. Verify by asserting `KeplerConfig(...).water_gap_penalty_sek` is non-zero for comfort_level 3.

## 2. Add the discomfort/gap-over variables and constraints in Kepler

- [x] 2.1 In `planner/solver/kepler.py`, near the other per-device water variable declarations (`water_heat` at line ~79, `water_start` at line ~99), ADD two per-device dicts initialized empty: `discomfort: dict[str, dict[int, Any]] = {}` and `gap_over: dict[str, dict[int, Any]] = {}`. Inside the loop that creates variables for each enabled heater `d`, create `discomfort[d] = pulp.LpVariable.dicts(f"discomfort_{d}", range(T), lowBound=0.0)` and `gap_over[d] = pulp.LpVariable.dicts(f"gap_over_{d}", range(T), lowBound=0.0)`. Match the existing `# type: ignore[reportUnknownMemberType]` style.
- [x] 2.2 In `planner/solver/kepler.py`, inside the `if water_enabled:` block, within the `for heater in water_heaters:` loop (line ~573), ADD the gap-comfort constraints per Decision 1. Compute `gap_penalty_active = config.water_heating_max_gap_hours > 0 and config.water_gap_penalty_sek > 0` once (before the heater loop). Inside the loop, only when `gap_penalty_active`, add for each `t in range(T)` with `duration = slot_hours[t]` and `M = 100.0`:
  - `t == 0`: `prob += discomfort[d][t] >= duration - water_heat[d][t] * M`
  - `t > 0`: `prob += discomfort[d][t] >= discomfort[d][t-1] + duration - water_heat[d][t] * M`
  - always: `prob += gap_over[d][t] >= discomfort[d][t] - config.water_heating_max_gap_hours`
  Add `# type: ignore[operator]` on the `prob +=` lines to match surrounding code.
- [x] 2.3 Guard the variable creation in 2.1 so that if `gap_penalty_active` is false the extra variables are harmless (they can be created but unconstrained and unused, OR skip creating them — pick one and be consistent so the objective term in 3.1 references only what exists). Simplest: always create the dicts but only add constraints + objective term when `gap_penalty_active`.

## 3. Add the objective term and delete the dead gap lines

- [x] 3.1 In `planner/solver/kepler.py`, in the objective `prob += (...)` block (line ~623-664), ADD the gap-comfort objective term:
  ```
  + (
      pulp.lpSum(gap_over[d][t] for d in gap_over for t in range(T)) * config.water_gap_penalty_sek
      if water_enabled and gap_penalty_active
      else 0.0
  )
  ```
- [x] 3.2 In the same objective block, DELETE the two doubled dead lines `+ gap_violation_penalty  # Deprecated in K16 (0.0)` (lines ~632-633) and DELETE the `gap_violation_penalty: float = 0.0` initialization (line ~557). Grep to confirm `gap_violation_penalty` no longer appears anywhere in `kepler.py`.

## 4. Fix the curtailment/export tiebreak (#16)

- [x] 4.1 In `planner/solver/kepler.py`, in the per-slot objective terms (around lines ~500-523), make curtailment preferred over loss-making export per Decision 6: when the slot's `effective_export_price` (`s.export_price_sek_kwh - config.export_threshold_sek_per_kwh`) is `<= 0`, the modelled curtailment cost for that slot SHALL be 0 (so the solver curtails instead of paying to export); when it is `> 0`, keep `curtailment[t] * config.curtailment_penalty_sek`. Implement as a per-slot conditional on `effective_export_price` (compute it once per slot; it is already computed at line ~500).
- [x] 4.2 Verify the sign/direction manually with the finding's example: at export price 0, exporting must no longer be chosen over curtailing.

## 5. Remove the fictional config keys and UI fields (#15)

- [x] 5.1 In `config.default.yaml`, in the `water_heating:` section (lines ~61-80), DELETE these four keys and their comments: `block_start_penalty_sek` (line ~63), `spacing_penalty_sek` (line ~65), `reliability_penalty_sek` (line ~79), `block_penalty_sek` (line ~80). KEEP `defer_up_to_hours`, `comfort_level`, `enable_top_ups`, and the `vacation_mode:` block. Update the `comfort_level` comment (line ~64) to read `# 1-5 (Economy→Maximum) - controls water heating comfort incl. gap penalty` (now accurate).
- [x] 5.2 In `frontend/src/config-help.json`, DELETE the entries `"water_heating.block_start_penalty_sek"` (line ~22) and `"water_heating.spacing_penalty_sek"` (line ~24), plus any `water_heating.reliability_penalty_sek` / `water_heating.block_penalty_sek` help entries if present.
- [x] 5.3 In `frontend/src/pages/settings/types.ts`, DELETE the three field definitions for `water_heating.spacing_penalty_sek` (lines ~1079-1081), `water_heating.block_start_penalty_sek` (lines ~1094-1097), and `water_heating.reliability_penalty_sek` (lines ~1103-1106), plus `water_heating.block_penalty_sek` if present. Ensure the surrounding array/object stays syntactically valid (commas, brackets).
- [x] 5.4 Grep the repo (excluding `openspec/` and archived changes) for the four removed keys. For each remaining hit in non-test source, remove it. For test files that assert on these keys, update or delete those assertions (they were testing dead config).

## 6. Tests

- [x] 6.1 Add a solver test (in `tests/planner/`, e.g. extend `test_multi_device_water_solver.py` or a new `test_water_gap_comfort.py`) for the "gaps beyond the ceiling are broken up" scenario: cheap-night/expensive-day prices, `max_hours_between_heating = 8`, `comfort_level = 3`; assert the resulting schedule has no heating gap materially exceeding 8 h (allow one slot tolerance).
- [x] 6.2 Add a test for "gaps within the ceiling are free": a case where a ≤8 h gap plan is optimal and assert the gap-penalty variables contribute 0 (or that raising `water_gap_penalty_sek` does not change the plan).
- [x] 6.3 Add a test that the gap penalty is DISABLED when `enable_top_ups: false` and in vacation mode (i.e. `water_heating_max_gap_hours == 0` ⇒ no gap constraints/term, no over-heating).
- [x] 6.4 Add a test that `comfort_level` maps to a monotonic non-decreasing `water_gap_penalty_sek` (L1 ≤ ... ≤ L5) and does NOT change the deadband.
- [x] 6.5 Add a #16 test: a slot with effective export price ≤ 0 and surplus PV ⇒ curtailment chosen (grid_export ≈ 0); a slot with positive export price ⇒ export chosen.
- [x] 6.6 Add a config-loading test that a config still containing the four removed keys loads without error and produces identical solver behavior (keys ignored).

## 7. Verification

- [x] 7.1 Run the solver/planner test subset: `uv run python -m pytest tests/planner -q` — all green.
- [x] 7.2 Run `scripts/ci_local.sh` (or the repo's equivalent) — ruff, pyright strict, full pytest, OpenAPI, and frontend ESLint all pass.
- [x] 7.3 Representative-day sanity check (Decision 2 tuning): run the solver on a real/representative day at comfort_level 3 and confirm heating is spread so gaps stay ≤ ~8 h without excessive extra cycling; if it over- or under-heats, adjust the `water_gap_penalty_sek` column (keep monotonic) and note the final values in this change's design.md.
- [x] 7.4 Confirm the settings UI renders without the removed fields and without console errors (build the frontend or load the settings page).
