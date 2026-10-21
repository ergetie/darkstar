## 1. Fuse model

- [x] 1.1 Create `executor/fuse_model.py`: Typ C and Diazed gG curves (multiples of In, anchors as in the spec, commented as read from the Hager graphs, +/-30%, assumptions marked), custom two-point curve, log-log interpolation, trip-time function
- [x] 1.2 Add `FuseHeatModel`: per-phase heat with build at or above the curve start, hold from 1.0x to the start, symmetric cooling below 1.0x, frozen on stale, gap guard `max(120 s, 2 x interval)`, `relief_needed(phase, momentary_a, now, stale) -> Relief` (amount = reading minus `main_fuse_a` x `target_margin_percent`, urgent = immediate-cut), `cooled(phases)` (below 50%), `reset()`, signature-based reset
- [x] 1.3 Unit tests in `tests/executor/test_fuse_model.py`: interpolation points, 1.05x hold and no-build, cooling, repeated overloads, worst phase, custom curve, relief amount and urgent flag, stale freeze, gap guard

## 2. Load balancer integration (`executor/load_balancer.py`, `executor/engine.py`)

- [x] 2.1 Widen the trigger contract: `ReliefTrigger`/`relief_trigger` receives the phase, tick time and stale flag and exposes `cooled(phases)`; make `FuseHeatModel` the default in place of `relief_needed` (line 98) and drop `severe_percent` from the call in `tick` (line ~1597); keep `Relief`, the pool derivation and `_urgent_phases` unchanged. Do not add any overload comparison in `_resolve_battery`, `_degrade_at_floor`, `_resolve_ev_decision` or the shed pass
- [x] 2.2 Remove the pause delay and severe code: `_degrade_at_floor` debounce branch (goes straight to 1-phase relief or pause), `_ev_overload_since`, `_debounce_phases` and its shed skip, `_severe_phases` (use `_urgent_phases`), messages naming `severe_overload_percent`; update the shed pass so it waits only on the pending-relief rule
- [x] 2.3 Replace the `ramp_up_window_s` hold-offs (EV `_ev_reduced_at` check ~999, battery `_battery_reduced_at` check ~1498) with `cooled(phases)`, next to `_pacing_ok` and the room gate; keep `ramp_up_window_s` as the averaging window only
- [x] 2.4 Add `cooled(entry.phases)` to `restore_shed` next to `resume_delay_s`, `min_off_s` and the room-for-power check (water heater needs all three); paused charger and battery re-fit stay un-gated
- [x] 2.5 Pass `executor.interval_seconds` into the model from the engine at construction and on config reload (engine.py ~401, ~536); reset heat when `fuse_preset`, custom points or `main_fuse_a` change, 0 on restart
- [x] 2.6 Update status, execution-log and trace reasons to show heat and safety % (including `balancer_trace.json` snapshots)
- [x] 2.7 Floor phase heat at `safety%` while the trigger calls for relief on that phase, with a regression test for an urgent cut from low heat

## 3. Config and migration

- [x] 3.1 `executor/config.py`: add `fuse_preset`, `fuse_safety_percent`, `fuse_custom_points` with validation and preset-dependent safety default; remove `pause_debounce_s`, `severe_overload_percent`, `PAUSE_DEBOUNCE_RANGE`, `SEVERE_OVERLOAD_RANGE` and their loader code; leave `max_step_interval_s`, `write_deadband_percent`, `pending_timeout_s`, `phase_sign`, `min_on_s`/`min_off_s` and custom `power_kw`/`power_sensor` untouched
- [x] 3.2 `backend/api/routers/config.py`: update `_validate_graceful_degradation_ranges` (remove the two old keys and imports, add new keys, custom-point ordering)
- [x] 3.3 `backend/config_migration.py`: add the two removed keys to `DEPRECATED_NESTED_KEYS["load_balancing"]` with a comment naming this change, after `replan_after_throttled_s`
- [x] 3.4 `config.default.yaml`: add new keys with comments, remove the two old keys, update the `target_margin_percent` and `ramp_up_window_s` comments, keep the 15 s interval advice
- [x] 3.5 Migration tests: old keys load without error, are removed by `remove_deprecated_keys`, removal logged, idempotent, template merge does not re-add them (extend `tests/config/`)

## 4. Frontend

- [x] 4.1 `frontend/src/pages/settings/types.ts` and `LoadBalancingTab.tsx`: preset select, safety % with preset-default placeholder, two custom points only for Custom (prefilled 130 % / 1200 s, 300 % / 4 s), per `docs/design-system/AI_GUIDELINES.md`
- [x] 4.2 Remove the two old fields; update `search/guides.ts` (lines ~40, ~135), aliases and tests (`useSettingsForm.test.ts`, `LoadBalancingTab.test.tsx`); optionally extend the existing slow-tick warning copy (no new warning)

- [x] 4.3 Add a responsive, accessible live fuse characteristic graph in Overload Handling for all presets, with logarithmic axes, backend-aligned trip and safety-scaled cold-start curves, invalid-input handling and approximation/heat/timing caveats; verify anchor/interpolation agreement and unsaved input updates.

## 5. Tests and specs

- [x] 5.1 Update tests passing `pause_debounce_s` or `severe_overload_percent` (`tests/executor/test_load_balancer.py`, `test_load_balancer_graceful_degradation.py`, `test_load_balancer_coordinated_ramping.py`, `test_load_balancer_wiring.py`, `test_load_balancer_e2e_dry_run.py`, `test_ev_measured_draw.py`, `test_ev_surplus_engine.py`, `tests/config/test_graceful_degradation_config.py`, `tests/config/test_coordinated_ramping_config.py`, `tests/executor/test_config.py`); use a fake trigger via `relief_trigger=` where a test needs the instant behaviour
- [x] 5.2 Add balancer tests through the trigger and the ledger: heat trigger, immediate cut (urgent bypasses hold-for-relief but not the fresh-sample guard), charger at floor pauses or requests 1-phase without delay, shed waits only for pending relief, restore gated by heat below 50% together with pacing and room gate, water heater needs room and `min_off_s` and cooling, battery cut unaffected by lagging measured charge, stale battery and EV minimum-then-pause with frozen heat, restart and runtime reset
- [x] 5.3 Run `./scripts/lint.sh`

## 6. Docs

- [x] 6.1 `docs/BACKLOG.md` item already removed; nothing to do
- [x] 6.2 Hand the release-note line from `proposal.md` to the release author; do not edit `docs/RELEASE_NOTES.md`. Ask before touching `docs/USER_MANUAL.md` for the new keys

## Review follow-up: live heat visibility
- [x] Expose model-derived phase heat state and evaluation timestamp in status, trace and execution logs, with stale/gap/reset regression coverage.
- [x] Add shared per-phase heat meters, intervention markers, trend and freshness states to full and compact status views while keeping phase current prominent.
- [x] Explain actual heat holds, identify tolerated overloads, clarify current-target and heat-threshold setting labels, and update main and archived specs.
- [x] Verify card integration, stale snapshot behavior, unavailable and over-scale values, settings labels, lint/types and strict specs.

## Review follow-up: general protected fuse and explicit membership
- [x] Rename protected-fuse and phase-sensor UI labels, keep brief same-fuse guidance and optional explanations.
- [x] Allow adding/removing EV and battery entries without deleting normal scheduling configuration; preserve explicit empty lists and selections through save/reload.
- [x] Migrate legacy participation once, reconcile removed devices and pending state, and keep excluded devices on normal schedule and surplus handling.
- [x] Separate the optional protected rating from the planner grid rating with legacy fallback; verify configuration, migration, dispatch, UI, lint/types and strict specs.
