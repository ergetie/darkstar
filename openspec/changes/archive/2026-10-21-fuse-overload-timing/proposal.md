## Why

The load balancer reacts to an overloaded phase as soon as a reading is over the fuse rating (the instant `relief_needed` trigger from `load-balancer-coordinated-ramping`): the house battery's grid charging is cut at once, the EV charger waits `load_balancing.pause_debounce_s` at its floor before pausing (or pauses at once above `load_balancing.severe_overload_percent`), and increases and restores wait on `ramp_up_window_s`. A real fuse does none of this: it tolerates a small overload for a long time and a big one for a very short time, and heat from repeated overloads adds up. Short peaks just above the limit (kettle, microwave) cut charging needlessly, while the balancer has no notion of how close the fuse really is to tripping. Backlog item "[Load Balancer] Proportional Overload Timing" (already removed from `docs/BACKLOG.md`) asks for exactly this.

## What Changes

- Make a time-based fuse heat model the implementation of the pluggable `relief_needed` trigger in `executor/load_balancer.py`. It is the only place overload is detected; the ledger, shared room gate, step pacing, fresh-sample guard and give-way order (battery, EV, water heater by default) are unchanged.
- Per-phase thermal accumulation: heat builds while a phase is over its fuse rating and cools at the same rate while under it. The balancer acts on the worst phase. Applies to both fuse types; only the consequence differs (a 3-pole Typ C trips all poles, a Diazed blows that phase only).
- Fuse presets "Typ C" (default), "Diazed gG" and "Custom". Curves are in multiples of the rated current (In), so one curve per preset covers 16-35 A. Values are read from manufacturer graphs (accuracy about +/-30%) and interpolated log-log.
- New user setting "safety %": Darkstar acts when accumulated heat reaches safety% of the trip time. Default depends on the preset (Typ C 80%, Diazed 65%, Custom 80%).
- Heat is measured against `main_fuse_a` (not the target margin). Below the curve's first timed point no heat builds; from 1.0x up to it heat holds; below 1.0x it cools at the rate it built.
- Relief amount is the reading minus the target margin limit, so a cut brings the phase below 1.0x and it cools. Immediate cut has no fixed multiple: urgent relief when the safety-scaled trip time at the current overload is shorter than `executor.interval_seconds`.
- The charger pause delay and the severe-overload threshold go away: at its floor a charger pauses (or requests 1-phase relief) as soon as the trigger calls for relief. A shed load waits for the entries above it only through the existing pending-relief rule.
- Stale or missing phase readings bypass the model: heat is frozen and the existing stale fail-safes (EV and battery to minimum, pause after `resume_delay_s`) apply.
- Heat state is in memory: 0 on restart, reset when `fuse_preset`, custom points or `main_fuse_a` change.
- New config keys `fuse_preset`, `fuse_safety_percent`, `fuse_custom_points`; safety % valid range 50-100.
- Increases and restores (EV ramp-up, battery cap raise after a reduction, shed-load restore including water heater) additionally wait until the worst phase has cooled below 50% heat; room gate, pacing, `resume_delay_s` and `min_off_s` still apply. `ramp_up_window_s` stays only as the averaging window; `increase_step_a` is kept.
- `load_balancing.pause_debounce_s` and `load_balancing.severe_overload_percent` are removed and added to the deprecated-key list in `backend/config_migration.py` (`remove_deprecated_keys`), so existing configs are cleaned on startup without errors. Release note line (for the release author, `docs/RELEASE_NOTES.md` is not touched by this change): "Load balancer: the pause delay and immediate-pause settings are replaced by a fuse model (Typ C / Diazed gG / Custom) with a safety % setting."
- Settings UI: preset select, safety %, and the two custom points when Custom is selected. Include a live characteristic graph in Overload Handling for every preset: logarithmic current-multiple and time axes, estimated fuse trip time and the safety-scaled cold-start Darkstar threshold, updating on unsaved edits. Explain retained heat, tick timing, graph-derived ±30% accuracy and anchor assumptions. The existing slow-tick warning is kept.

## Capabilities

### New Capabilities
- `fuse-overload-timing`: time-current fuse model as the default relief trigger, per-phase heat accumulation, presets, safety %, cooled restore condition, config keys and settings UI.

### Modified Capabilities
- `phase-load-balancing`: pluggable trigger contract, throttle, pause, 1-phase relief, shed timing, ramp-up hold-off, battery cut and ramp-back, shed restore, target margin.
- `load-balancing-settings`: graceful degradation keys and defaults.
- `config-migration`: removal of the two deprecated keys.

## Impact

- Code: `executor/fuse_model.py` (new), `executor/load_balancer.py` (trigger contract and wiring, removal of debounce/severe code, cooled gate in EV and battery ramp-up and `restore_shed`), `executor/engine.py` (pass `executor.interval_seconds` to the balancer, lines ~401 and ~536), `executor/config.py` (`LoadBalancingConfig`, ranges, loader), `backend/api/routers/config.py` (`_validate_graceful_degradation_ranges`), `backend/config_migration.py` (`DEPRECATED_NESTED_KEYS`), `config.default.yaml` (`load_balancing:`), `frontend/src/pages/settings/types.ts`, `frontend/src/pages/settings/LoadBalancingTab.tsx`, `frontend/src/pages/settings/search/guides.ts`.
- Tests: `tests/executor/test_load_balancer*.py`, `tests/config/test_graceful_degradation_config.py`, `tests/config/test_coordinated_ramping_config.py`, `tests/executor/test_config.py`, `tests/executor/test_ev_measured_draw.py`, `tests/executor/test_ev_surplus_engine.py`, frontend settings tests.
- Specs: `openspec/specs/phase-load-balancing/spec.md`, `openspec/specs/load-balancing-settings/spec.md`, `openspec/specs/config-migration/spec.md`.
- Docs: none required by this change (`docs/USER_MANUAL.md` may need the new keys; ask first, per AGENTS.md). No database change, no new dependency.

## Review follow-up
Expose live estimated per-phase heat, truthful heating/cooling/holding and stale state, sample freshness and heat-hold explanations in full and compact status cards. Clarify the current-target and heat-threshold setting labels and use a compact responsive graph with optional technical detail.

## Protected-fuse follow-up
Use general protected-fuse terminology and make EV/battery give-way membership optional. Preserve existing participation on upgrade, then respect explicit selections across reload/restart while retaining normal scheduling for excluded devices. Keep physical-boundary guidance brief with optional detail.
