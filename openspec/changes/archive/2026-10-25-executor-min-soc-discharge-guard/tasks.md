# Tasks

## 1. Executor guard

- [x] 1.1 Add a reason constant (design D5) and the guard latch logic in `executor/controller.py`: engage at `live_soc <= min_soc_percent`, release at `>= min_soc_percent + SOC_TRACKING_MARGIN` (D2). Apply after the mode intent is chosen in `_follow_plan`, replacing `self_consumption` and `export` with `idle` and leaving `charge` and `idle` alone (D1). Verify with the tests in 3.1.
- [x] 1.2 Handle `state.soc_available` False: keep the previous latch state (D4). Verify with a test.
- [x] 1.3 Add the latch as a `BatteryPlanState` field that `enter()` does not reset (D3); no engine plumbing needed. Verify with the slot-change test, and that the status-display copy (`engine.py` ~L604) does not change the engine's latch.

## 2. Reason visibility

- [x] 2.1 Set the guard reason as the decision note so it appears in logs and UI (D5). Verify the note text in a test.

## 3. Tests

- [x] 3.1 Add tests to `tests/executor/test_battery_plan_tracking.py`: PV-charge slot at min gives idle; export at min gives idle; release at min+2, not min+1; latch survives a slot change and replan; unavailable SoC keeps state (engaged and released); charge slots untouched; Deye-style profile (`soc_target` in every mode) unaffected. Verify with `UV_NO_SYNC=1 uv run python -m pytest tests/executor/test_battery_plan_tracking.py -v`.
- [x] 3.2 Run `./scripts/lint.sh` and `UV_NO_SYNC=1 uv run python -m pytest tests/executor -q`. Verify zero failures and a clean lint.

## Workflow follow-up

- Run `openspec validate executor-min-soc-discharge-guard --strict` before archive.
- After release, ask Kristofer to confirm SoC no longer falls below 12 % on his Fronius.
