## Context

`kepler.py` (~line 1058-1062) tries `pulp.GLPK_CMD` then falls back to `pulp.PULP_CBC_CMD(msg=False, timeLimit=...)`, which runs one thread. Time limit is resolved by `resolve_solver_time_limit_s` in `planner/solver/adapter.py`, carried in `KeplerConfig` (`types.py`), and validated in `backend/api/routers/config.py` (~971). CBC 2.10.3 (pulp 3.3.2) supports `threads`.

## Goals / Non-Goals

**Goals:** use available cores for CBC; configurable override; faster default time limit (90 s).
**Non-Goals:** GLPK changes, warm start (rejected), deterministic results, editing users' `config.yaml`, changing `time_limit_hit` detection.

## Decisions

- **Resolver `resolve_solver_threads(kepler_section)` in adapter.py**, mirroring `resolve_solver_time_limit_s`: absent/0 -> auto; 1-64 -> explicit; invalid -> warn and auto. Result stored in `KeplerConfig.solver_threads` (int, 0 = auto resolved at solve time is avoided: adapter resolves to a concrete int).
- **Auto detection helper `available_cpu_count()`**: `len(os.sched_getaffinity(0))`, falling back to `os.cpu_count()`, min 1; then cap by cgroup v2 `/sys/fs/cgroup/cpu.max` (`quota period`, ceil(quota/period); "max" = no cap), with cgroup v1 `cpu.cfs_quota_us`/`cpu.cfs_period_us` as optional fallback. All file reads are failure-tolerant. Place alongside the resolver so tests can monkeypatch.
- **kepler.py** passes `threads=config.solver_threads` only to `PULP_CBC_CMD` and logs the count. If `KeplerConfig.solver_threads` is unset by direct callers, default 1 keeps old behavior.
- **Default 90 s** in `config.default.yaml`, `types.py`, resolver default and docstrings/comments; range 10-600 unchanged. Add `solver_threads: 0` with comment to `config.default.yaml`.
- **API validation** in config.py: accept int 0-64, reject others, same error shape as the time limit.

## Risks / Trade-offs

- Nondeterminism (~1-2 SEK noise) between runs -> accepted; tests must not assert exact plans across runs.
- Cgroup quota misdetection -> falls back to affinity; user can override via `solver_threads`.
- More CPU contention with other services during solve -> override available.
- Users with explicit 60 s keep it (60 s with 4 threads was ~8 SEK worse); no migration.
