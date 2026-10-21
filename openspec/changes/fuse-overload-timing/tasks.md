## 1. Fuse model

- [ ] 1.1 Create `executor/fuse_model.py`: Typ C and Diazed gG curves (multiples of In, anchors as in the spec, commented as read from the Hager graphs, +/-30%, assumptions marked), custom two-point curve, log-log interpolation, trip-time function
- [ ] 1.2 Add per-phase `HeatTracker`: build at or above the curve start, hold from 1.0x to the start, symmetric cooling below 1.0x, frozen on stale, `reset()`
- [ ] 1.3 Unit tests in `tests/executor/test_fuse_model.py`: interpolation points, 1.05x hold and no-build, cooling, repeated overloads, worst phase, custom curve

## 2. Load balancer integration (`executor/load_balancer.py`)

- [ ] 2.1 Feed converted phase currents to the tracker at the start of `LoadBalancer.tick`; reduce to `main_fuse_a` x `target_margin_percent` (not `main_fuse_a`); compute "must reduce" from heat >= safety% or safety-scaled trip time < `executor.interval_seconds`
- [ ] 2.2 Replace the `binding < 0` trigger in `_resolve_battery` (including `hold_for_relief`) and the shed trigger in `tick`
- [ ] 2.3 Replace `_severe_phases` and the `pause_debounce_s` check in `_resolve_ev_decision` and `_degrade_at_floor`
- [ ] 2.4 Replace the `ramp_up_window_s` hold-offs (battery and EV) with "worst phase heat below 50%"; keep `ramp_up_window_s` as the averaging window, keep `increase_step_a`, `resume_delay_s`, `resume_confirm_s`
- [ ] 2.5 Keep the stale/missing fallback (immediate cut on over-limit reading, heat frozen)
- [ ] 2.6 Reset heat on restart (default state) and when `fuse_preset`, custom points or `main_fuse_a` change
- [ ] 2.7 Update status and execution-log reasons to show heat and safety %

## 3. Config and migration

- [ ] 3.1 `executor/config.py`: add `fuse_preset`, `fuse_safety_percent`, `fuse_custom_points` with validation and preset-dependent safety default; remove `pause_debounce_s` and `severe_overload_percent`
- [ ] 3.2 `backend/api/routers/config.py`: update `_validate_graceful_degradation_ranges` (remove old, add new, custom-point ordering)
- [ ] 3.3 `backend/config_migration.py`: add the two removed keys to `DEPRECATED_NESTED_KEYS["load_balancing"]` with a comment, matching the `charger_priority` entry
- [ ] 3.4 `config.default.yaml`: add new keys with comments, remove the two old keys, keep the 15 s interval advice
- [ ] 3.5 Migration tests: old keys load without error, are removed by `remove_deprecated_keys`, removal logged

## 4. Frontend

- [ ] 4.1 `frontend/src/pages/settings/types.ts` and `LoadBalancingTab.tsx`: preset select, safety % with preset-default placeholder, two custom points only for Custom (prefilled 130 % / 1200 s, 300 % / 4 s), per `docs/design-system/AI_GUIDELINES.md`
- [ ] 4.2a Add the slow-interval warning (load balancing enabled and `executor.interval_seconds` > 15) per design system, with tests
- [ ] 4.2 Remove the two old fields; update `search/guides.ts`, aliases and tests (`useSettingsForm.test.ts`, `LoadBalancingTab.test.tsx`)

## 5. Tests and specs

- [ ] 5.1 Update tests passing `pause_debounce_s` or `severe_overload_percent` (`tests/executor/test_load_balancer*.py`, `test_ev_*`, `test_load_balancer_wiring.py`, `test_load_balancer_e2e_dry_run.py`, `tests/config/test_graceful_degradation_config.py`, `tests/executor/test_config.py`)
- [ ] 5.2 Add balancer tests: heat trigger, immediate cut, stale fallback, restore below 50%, battery under `hold_for_relief`, restart and runtime reset
- [ ] 5.3 Run `./scripts/lint.sh`

## 6. Docs

- [ ] 6.1 `docs/BACKLOG.md` item removed (done when this change was created)
- [ ] 6.2 Hand the release-note line from `proposal.md` to the release author; do not edit `docs/RELEASE_NOTES.md`
