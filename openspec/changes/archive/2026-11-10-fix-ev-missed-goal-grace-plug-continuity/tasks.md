## 1. Plug-session tracking

- [x] 1.1 Add session-start tracking to `backend/core/ev_plug.py` (transition-based, unreachable ignored, unknown-at-startup = None, reset helper for tests)
- [x] 1.2 Expose `plug_session_start` in `ha_state` from `ev_live_state.py` / `ha_client.py` read paths

## 1b. Unplug debounce and persistence

- [x] 1b.1 Add `EV_UNPLUG_DEBOUNCE_MINUTES = 10` and `first_unplugged_at` tracking to `ev_plug.py` (flicker keeps session, long unplug ends it, unreachable ignored)
- [x] 1b.2 Persist `plug_session` (`start`, `first_unplugged_at`) per charger via `update_ev_state` on transitions only; restore on first valid reading per D1b; tolerate missing/corrupt/old files; preserve it in the planner entry rewrite and goal-clear path and keep it out of the API goal view
- [x] 1b.3 Tests in `tests/backend/test_ev_plug_session.py`: flicker, long unplug, flicker across deadline, restart restore / car left / mid-debounce, missing/corrupt file, no write on repeated readings, Torleif regression
- [x] 1b.4 Update design/spec text that claimed a restart loses history; run `openspec validate --strict`

## 2. Grace continuity

- [x] 2.1 Update `resolve_ev_effective_deadline` per D2/D2b/D5 (session_start <= missed, non-stale SoC, SoC-drop check for known-continuous and unknown history with `EV_SOC_DROP_NOISE_PERCENT`, none available = legacy, unreachable uses last known, tolerance)
- [x] 2.3 Read SoC at the missed deadline from HA history of `soc_sensor` (only when grace is otherwise possible, i.e. no replug after the deadline); pass as `ha_state["soc_at_missed_deadline"]`; verify/generalise the history helper
- [x] 2.2 Pass staleness (`soc_status`) into the grace decision; update docstrings

## 3. Cost-aware grace

- [x] 3.1 Add per-charger shortfall penalty to Kepler charger input (`types.py`, `adapter.py`) and use it in `kepler.py` instead of the global penalty
- [x] 3.2 When `in_grace`, derive the penalty from import prices up to the next regular deadline (D3 constants `EV_GRACE_SPREAD_FRACTION`, `EV_GRACE_MIN_MARGIN_SEK`, `EV_GRACE_PENALTY_FALLBACK_SEK`; flat/negative/unknown handled); keep 50 for regular goals; carry `next_deadline` in plan state

## 3b. Tolerance setting

- [x] 3b.1 Add `MISSED_GOAL_TOLERANCE_PERCENT_DEFAULT = 5.0` and parsing (absent/invalid -> default, 0 = off) in `planner/pipeline.py`
- [x] 3b.2 Add `missed_goal_tolerance_percent: 5` to `config.default.yaml` next to `missed_goal_grace_hours`; confirm no migration is needed
- [x] 3b.3 Add the field to `EntityArrayEditor.tsx` (type, defaults, NumberInput) following the grace-hours pattern

## 4. Diagnostics

- [x] 4.1 Pass `real_now` to `compute_ev_goal_diagnostics`; use for eligibility and slot-0 remaining time
- [x] 4.2 Classify `deadline_too_close` when remaining time x max kW < required
- [x] 4.3 Scale min_chunk in `_warn_on_zero_scheduled_active_goals` for a partial slot

## 5. Tests

- [x] 5.1 Extend `tests/planner/test_ev_missed_goal_grace.py`: replug after deadline, unknown history (deadline SoC higher by > noise -> no grace; equal/within noise/higher -> grace; none available -> legacy), tolerance (82 vs 85 no grace; 66 vs 85 grace; tolerance 0; absent key default; exactly at boundary),  unreachable (plugged / unplugged), stale SoC, late departure, grace 0, goal changed, weekdays/every_n_days rollover
- [x] 5.2 Extend `tests/planner/test_ev_goal_diagnostics.py`: partial slot, real now, deadline_too_close
- [x] 5.3 Extend `tests/planner/test_ev_goal_shortfall_replay.py` and add Torleif-like regression (unplug 05:56 at 82%, replug 07:22 at 66%, expensive morning, cheap night: no grace, ~overnight plan); add Kepler/adapter tests for the price-derived grace penalty: cheap day, expensive day (same relative behaviour), price spike, flat prices, negative min price, unknown prices, and Torleif-like 5.8 now vs 2.4 overnight (no grace charging)
- [x] 5.4 Run `./scripts/lint.sh` and the planner test suite
