## Context

Verified in the current code (`executor/load_balancer.py`, 1387 lines, pure decision logic, `LoadBalancer.tick(now, grid_current_a, grid_current_updated_at, entries)`):

- Battery cut: `LoadBalancer._resolve_battery` cuts grid-charge cap as soon as the binding headroom is negative (`binding < 0`), with no delay; it only waits when `hold_for_relief` and no severe phase.
- EV pause delay: `_degrade_at_floor` holds the floor for `config.pause_debounce_s` (tracked in `_ev_overload_since`) before 1-phase relief or `_pause_charging`.
- Immediate pause: `_severe_phases` compares readings with `main_fuse_a * severe_overload_percent / 100`; used in `_resolve_ev_decision` (hold-for-relief branch), `_degrade_at_floor`, and `_resolve_battery`.
- Ramp-back: `ramp_up_window_s` (default 60) is both the rolling-average window (`_update_samples`, `averaged_current_a`) and the hold-off after a reduction (`_ev_reduced_at`-style state, `_battery_reduced_at`). Ramp step is `increase_step_a` (default 1).
- Shed loads: restored after `resume_delay_s` (default 120) plus margin check in `tick`.
- Stale handling: `_is_stale` with `sensor_stale_after_s` (default 30); EV `stale_fallback`, battery holds cap.
- Config: `executor/config.py` `LoadBalancingConfig` (`pause_debounce_s` line ~263, `severe_overload_percent` ~265, loader ~539-559); `config.default.yaml` `load_balancing:` (lines ~329-355; `pause_debounce_s` 334, `severe_overload_percent` 335); validation `backend/api/routers/config.py` `_validate_graceful_degradation_ranges` (~line 627); UI `frontend/src/pages/settings/types.ts` (~1375, ~1393), `frontend/src/pages/settings/LoadBalancingTab.tsx`, search guides `frontend/src/pages/settings/search/guides.ts` (lines 38, 129).
- Sensor timestamps: `executor/engine.py` builds `grid_current_updated_at` (~lines 2789-2856).

## Goals / Non-Goals

**Goals:** one time-current model for every load; heat accumulation per phase; presets; safety %; cooling-based restore.
**Non-Goals:** changing give-way order, planner behaviour, per-phase planning (separate backlog item), or the EV phase-switching logic; editing `docs/RELEASE_NOTES.md`; migration of removed keys.

## Decisions

1. **New pure module** `executor/fuse_model.py`: preset curves, log-log `trip_time_s(multiple)`, and a per-phase `HeatTracker` (`update(phase, current_a, now)`, `heat(phase)`, `reset()`). `LoadBalancer` owns one tracker and updates it at the start of `tick` from the same per-phase currents used for headroom (already converted by `power_to_current_a` for power-mode sensors).
2. **Reference is `main_fuse_a`**: multiple `m = current / main_fuse_a`. `target_margin_percent` is only the ramp-up/restore target.
3. **Heat rules**: let `start` be the first timed point of the curve (Typ C 1.13x, Diazed 1.25x, Custom the lower point). `m >= start`: `heat += dt / T(m)`, remember the build rate. `1.0 <= m < start`: hold. `m < 1.0`: `heat -= dt * last_build_rate`, floored at 0. `dt` is the real time since the previous tick.
4. **Curve anchors are assumptions**: Typ C 1.13x treated as 1 h and 5x as 0.1 s; Diazed 1.25x treated as 4 h, extended above 4x along the last segment slope. All values read from graphs, +/-30%.
5. **Action rule**: a phase "must reduce" when `heat >= safety/100` or `T(m) * safety/100 < executor.interval_seconds`. This replaces the `binding < 0` trigger in `_resolve_battery` (also under `hold_for_relief`), the `pause_debounce_s` check and `_severe_phases` in `_degrade_at_floor` / `_resolve_ev_decision`, and the shed trigger in `tick`. The reduction target is the target margin limit (`main_fuse_a` x `target_margin_percent`), so the phase falls below 1.0x and cools; otherwise the restore rule (heat below 50%) could never fire.
6. **Reading interval** is `executor.interval_seconds` (executor/config.py default 300; `config.default.yaml` default 60; config.default.yaml lines 322-324 advise 15 s or less when load balancing is on). Not measured.
7. **Restore**: the hold-offs based on `ramp_up_window_s` (`_battery_reduced_at` and the EV equivalent) become "worst phase heat below 50%". `ramp_up_window_s` stays only as the averaging window; `increase_step_a`, `resume_delay_s` and `resume_confirm_s` stay.
8. **Stale / missing**: bypass the model, keep the current behaviour (immediate cut on an over-limit reading); heat for that phase is frozen.
9. **Lifecycle**: heat is in memory only, 0 on restart; the balancer resets the tracker when `fuse_preset`, custom points or `main_fuse_a` differ from the values the tracker was built with.
10. **Config keys**: `load_balancing.fuse_preset` (`typ_c` | `diazed_gg` | `custom`, default `typ_c`), `fuse_safety_percent` (50-100, unset means 80 / 65 / 80 by preset), `fuse_custom_points` (two points, `overload_percent` 101-1000, `time_s` 0.5-86400, higher overload must have the strictly shorter time; prefill 130 % / 1200 s and 300 % / 4 s). Validation in `executor/config.py` and `backend/api/routers/config.py`.
11. **Removed keys**: add `pause_debounce_s` and `severe_overload_percent` to `DEPRECATED_NESTED_KEYS["load_balancing"]` in `backend/config_migration.py` next to `charger_priority`, with a comment naming this change. `remove_deprecated_keys` deletes them, logs each removal and sets the changed flag; the existing startup path then performs the atomic write with backup. Remove them from `config.default.yaml`, `executor/config.py`, `_validate_graceful_degradation_ranges`, `frontend/src/pages/settings/types.ts`, `search/guides.ts` and the tests.
12. **UI**: a warning (design-system styled) when load balancing is enabled and `executor.interval_seconds` > 15, explaining coarse timing and earlier cuts; plus preset select, safety % (placeholder shows the preset default), two custom points shown only for Custom, per `docs/design-system/AI_GUIDELINES.md`.
13. **Specs**: delta specs MODIFY the affected requirements of `phase-load-balancing` and `load-balancing-settings` (full requirement text, so they sync cleanly).

## Risks / Trade-offs

- Curve accuracy is about +/-30%; Typ C uses the fastest band edge on purpose and the safety % covers the rest.
- With `executor.interval_seconds` at 60 (config.default.yaml) or 300 (code default) the heat integration is coarse and the immediate-cut region is wide; the existing 15 s advice matters more now.
- A stale sensor on an overloaded phase gives no heat information; the fallback is deliberately conservative.
- Many tests pass `pause_debounce_s=0` to `make_lb` and need editing.
- The tick uses sampled currents; heat is an approximation of the real thermal state.

## Open Questions

1. **Interval warning source**: the settings form must read `executor.interval_seconds` alongside `load_balancing`; confirm the form already has both values. Recommended: use the loaded config values.
2. **Diazed above 4x and Typ C 3x to 5x**: extension and the 0.1 s anchor are my assumptions. Recommended: keep, confirm.
3. **Custom point ranges** (101-1000 %, 0.5-86400 s) are proposals. Recommended: keep.
4. **Tracker reset on custom-point change** goes slightly beyond the requested preset / `main_fuse_a` reset. Recommended: keep.
