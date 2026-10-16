# Tasks

## 1. Stop grid charging at target

- [x] 1.1 Add failing tests in `tests/executor/test_executor_controller.py`: grid-charge slot with live SoC ≥ target selects hold; below target charges; solar-only charge slot unchanged; override and Top Up unchanged; verify they fail on current code
- [x] 1.2 In `executor/controller.py`, select hold instead of charge when `round(live SoC) ≥ soc_target` in a grid-charge slot; verify 1.1 passes
- [x] 1.3 Add the per-block latch (resume only at target − 2; reset at block change) with tests for stop, hold within 2, resume and reset; verify `tests/executor` passes
- [x] 1.4 Tick reason and execution log say "charge target reached, holding"; verify with a test on the recorded reason

## 2. Hold margin

- [x] 2.1 Add failing tests for every hold-margin scenario in the spec (49% auto, 48% block, 49% after block stays blocked, 50% lifts) and for EV source isolation keeping precedence; verify they fail on current code
- [x] 2.2 Implement the 2-point hold margin with per-hold-block state in the executor; verify 2.1 passes and existing controller rounding tests still pass (update only those whose expectation the spec changes, and list them in the PR)
- [x] 2.3 Tick reason and execution log say "hold margin used, blocking discharge"; verify with a test

## 3. Replan on SoC deviation

- [x] 3.1 Add `ReplanReason.SOC_DEVIATION = "soc_deviation"` in `backend/services/scheduler_service.py`; verify scheduler tests pass
- [x] 3.2 Add `executor.soc_deviation_replan_percent` (default 10, 0 disables, 0–50) to `executor/config.py` and `config.default.yaml` with a comment; verify with tests in `tests/executor/test_config.py`
- [x] 3.3 In `executor/engine.py`, compute the expected SoC by interpolation, track how long the deviation has exceeded the threshold (time-based, 5 min), and request the replan through `request_replan` with its own 15-minute limiter; skip on unavailable SoC, override or Top Up; log-only in shadow mode; verify with `tests/executor/test_soc_deviation_replan.py` covering every spec scenario
- [x] 3.4 Verify with a test that deviation replans and load-balancer replans do not consume each other's limit

## 4. Setting in the UI

- [x] 4.1 Add the field to `frontend/src/pages/settings/types.ts` (advanced, executor section) with help text per the spec, and to the settings search guide; verify settings frontend tests pass and the field saves via the dev app

## 5. Integration check

- [x] 5.1 Replay the reported scenarios in tests: plan from 3% charging to 18% stops at 18%; plan expecting 15% with live 3% for 5 minutes → one replan; hold slot with PV shortfall → at most one block, no flipping; verify they pass
- [x] 5.2 Run `./scripts/lint.sh` and the executor, backend, planner and frontend test suites; verify all pass
