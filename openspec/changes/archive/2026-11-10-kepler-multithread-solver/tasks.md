## 1. Thread resolution

- [x] 1.1 Add `solver_threads: int = 1` to `KeplerConfig` in `planner/solver/types.py`; change `solver_time_limit_s` default to 90 and update its comment
- [x] 1.2 Add CPU detection helper (affinity, cpu_count fallback, cgroup v2 `cpu.max` and v1 quota, min 1) in `planner/solver/adapter.py`
- [x] 1.3 Add `resolve_solver_threads` (absent/0 auto, 1-64 explicit, invalid warns and falls back to auto) and wire it where `resolve_solver_time_limit_s` is used (~line 606)
- [x] 1.4 Change `resolve_solver_time_limit_s` default and docstring to 90 s (range 10-600 unchanged)

## 2. Solver

- [x] 2.1 Pass `threads=config.solver_threads` to `pulp.PULP_CBC_CMD` in `planner/solver/kepler.py`; leave GLPK call and `time_limit_hit` detection unchanged
- [x] 2.2 Log the thread count used for the solve

## 3. Config and API

- [x] 3.1 Update `config.default.yaml`: `solver_time_limit_s: 90`, add `solver_threads: 0` with explanatory comment (do not touch `config.yaml`)
- [x] 3.2 Add `kepler.solver_threads` validation (integer 0-64) in `backend/api/routers/config.py`, update time-limit docs/comments to 90

- [x] 3.3 Expose `kepler.solver_threads` in Settings > Advanced Tuning (`frontend/src/pages/settings/types.ts`, `frontend/src/config-help.json`), mirroring the time-limit entry (number, min 0, max 64)

## 4. Tests

- [x] 4.1 Resolution tests: auto, config override, invalid values, affinity and cpu_count fallback, cgroup quota (v2 `max`, fractional, unreadable file)
- [x] 4.2 Test that `threads` is passed to `PULP_CBC_CMD` and GLPK call is unchanged
- [x] 4.3 Test default time limit is 90 in code defaults and `config.default.yaml`; API validation tests for `solver_threads`
- [x] 4.4 Run `./scripts/lint.sh` and fix issues
