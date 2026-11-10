## Why

The Kepler MILP solve runs CBC single-threaded with a 240 s time limit in production (~4 min per replan). Replaying 3 real prod plans showed 4 CBC threads at 90 s matched or beat 1 thread at 240 s (within ~0.3-1.8 SEK of the best result), while 4 threads at 60 s was 7.5-8 SEK worse. The prod container now has 6 cores, so using them cuts replan latency by more than half at equal plan quality. Warm start was tested and rejected (no clear gain).

## What Changes

- CBC solves use multiple threads, derived from the CPU cores actually available to the process (affinity, cgroup quota, cpu_count; minimum 1).
- New optional config `kepler.solver_threads` (absent/0 = auto, 1-64 explicit override), validated like `kepler.solver_time_limit_s`.
- The thread count used is logged on each solve.
- Default `kepler.solver_time_limit_s` changes from 60 to 90 (range stays 10-600). Existing user `config.yaml` values are untouched.
- GLPK path unchanged (not installed in prod); only CBC receives threads. `time_limit_hit` detection unchanged.

Note: multi-threaded CBC is nondeterministic (~1-2 SEK run-to-run noise).

## Capabilities

### New Capabilities
- `kepler-solver-threading`: thread count resolution and configuration for the Kepler CBC solve, plus the default solve time limit.

### Modified Capabilities
(none)

## Impact

- `planner/solver/kepler.py` (CBC invocation, logging), `planner/solver/adapter.py` (resolver), `planner/solver/types.py` (config field and default), `backend/api/routers/config.py` (validation), `config.default.yaml` (new key, default 90), `frontend/src/pages/settings/types.ts` and `frontend/src/config-help.json` (Advanced Tuning setting).
- Tests under `tests/` for resolution, CBC argument passing, defaults and API validation.
- No new dependencies, no schema changes.
