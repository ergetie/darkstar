# Tasks

## 1. Executor: min_soc-bounded hold margin

- [x] 1.1 Add `min_soc_percent: float = 10.0` to `ControllerConfig` and read it from `battery.min_soc_percent` in `load_executor_config` (design D2). Verify with a config test that `battery.min_soc_percent: 12` yields 12.0, a missing key yields 10.0, and `reload_config()` picks up a changed value.
- [x] 1.2 Change `_hold_mode` to use floor `max(target − SOC_TRACKING_MARGIN, min(target, min_soc))`, latching at `live <= floor` and lifting at `live >= target and live > floor` (design D1). Update the docstring and the battery-plan-tracking comment. Verify that the existing `TestHoldMargin` tests in `tests/executor/test_battery_plan_tracking.py` pass unchanged.
- [x] 1.3 Add executor tests to `tests/executor/test_battery_plan_tracking.py` with `ControllerConfig(min_soc_percent=12)`: target 13 at live 12 blocks; target 12 at live 12 blocks immediately and stays idle across repeated ticks at 12; target 12 lifts at 13; target 11 at live 11 is idle (no charge) and lifts only at 12. Verify they pass with `UV_NO_SYNC=1 uv run python -m pytest tests/executor/test_battery_plan_tracking.py -v`.
- [x] 1.4 Add a Fronius-profile test (`load_profile("fronius")`): a hold slot at target = min_soc selects `idle` ("Block Discharging") on the first tick. Add the reported-sequence regression: charge block target 12 latches idle, the following hold slot at target 12 stays idle (no self-consumption), and the following charge slot at live 12 stays idle. Verify the tests pass.
- [x] 1.5 Add a Deye no-regression test (`load_profile("deye")`, min_soc 12): a hold at target 50 gives self-consumption at 49 and idle at 48, a grid-charge latch at 18 resumes at 16, and `soc_target` passes through unchanged. Verify the test passes.
- [x] 1.6 Confirm the grid-charge latch is unchanged (design D3) by running the existing `TestStopGridChargeAtTarget` tests (including `test_small_dip_keeps_holding` and `test_clear_drop_resumes`). Verify they pass unmodified.

## 2. Planner: recovery window in Kepler

- [x] 2.1 Add constants `MIN_SOC_RECOVERY_HOURS = 6.0` and `MIN_SOC_RECOVERY_MAX_DEFICIT_PERCENT = 5.0` and build per-state `floor_kwh[0..T]` (design D4/D5/D6): recovery is active only when `benchmark is None` and `min_soc_kwh − 5 % · capacity ≤ initial_soc < min_soc_kwh`; terminal state always `min_soc_kwh`. Verify by running `tests/planner/test_kepler_solver.py`, `test_kepler_export_floor.py`, `test_kepler_soft_max_soc.py` and `tests/backend/test_battery_benchmark.py` unchanged.
- [x] 2.2 Use `floor_kwh[t]` / `floor_kwh[T]` in the min-SoC constraints and `floor_kwh[t + 1]` in the export-floor fallback term. Update the misleading "Hard constraint" comment and the `planner/pipeline.py` penalty comment to mention the recovery window. Verify the tests from 2.1 still pass.
- [x] 2.3 Create `tests/planner/test_kepler_min_soc_recovery.py` covering the `min-soc-recovery` scenarios. Verify all pass:
  - drift to min − 1 (19.2 kWh, min 12, initial 11 %) with expensive first 3 h and a cheap hour at 3–4 h plans no grid import for battery charging before hour 3, no state below 11 %, and ≥ 12 % from 6 h on
  - flat price still reaches 12 % by 6 h with zero `soc_violation`
  - initial 6 % (min − 6) charges in the first slot despite a cheaper later slot
  - initial 7 % (exactly min − 5) uses the window
  - a 4 h horizon holds the terminal state to 12 %
  - initial ≥ min is identical to the pre-change bound
  - export floor 20 % with initial 11 % produces no `export_floor_violation` in non-export window slots
  - a benchmark solve starting at 10 % keeps its relaxed bound
- [x] 2.4 Update the docstring of `test_min_soc_violation_behavior_unchanged` in `tests/planner/test_kepler_soft_max_soc.py` to note that its 30-point deficit stays on the deep-deficit path (updated "Lower bound behavior unchanged" scenario). Verify that file passes.

## 3. Planner: SoC targets consistent with recovery

- [x] 3.1 In `planner/output/soc_target.py`, clamp charge-block targets below at `min(min_soc_percent, block-end projection)` when a projection exists, keeping `min_soc_percent` for the fallback paths (design D7). Update the module docstring. Verify with 3.2.
- [x] 3.2 Create `tests/planner/test_soc_target.py`. Verify all pass:
  - a charge block projected to end at 11.4 % with min 12 gives target 11
  - a block ending at 80 % gives 80
  - a hold slot with entry 11 % gives 11
  - a discharge slot gives min_soc

## 4. Integration and docs

- [x] 4.1 Run `./scripts/lint.sh` and the full executor and planner test suites (`UV_NO_SYNC=1 uv run python -m pytest tests/executor tests/planner tests/backend/test_battery_benchmark.py -q`). Verify zero failures and a clean lint.
- [x] 4.2 With user approval (`docs/` is ask-first), add two sentences to the "Battery State of Charge (SoC) Limits" section of `docs/USER_MANUAL.md`: hold slots never discharge below `min_soc_percent`, and a deficit of up to 5 points is refilled within 6 h at the cheapest time while larger deficits are refilled immediately. Verify the section renders and states both values.

## Workflow follow-up

- Run `openspec validate min-soc-floor-tracking --strict` before archive.
- After release, ask Kristofer to confirm execution history no longer cycles Charge → Self-consumption → Idle near 12 %.
