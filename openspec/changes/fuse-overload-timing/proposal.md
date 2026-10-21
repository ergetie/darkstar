## Why

The load balancer reacts to an overloaded phase with fixed, unrelated timers: the house battery's grid charging is cut the moment a phase goes over the fuse rating, the EV charger waits `load_balancing.pause_debounce_s` at its floor before pausing (or pauses at once above `load_balancing.severe_overload_percent`), shed loads and the battery come back on fixed timers (`ramp_up_window_s`, `resume_delay_s`). A real fuse does none of this: it tolerates a small overload for a long time and a big one for a very short time, and heat from repeated overloads adds up. Short peaks just above the limit (kettle, microwave) cut charging needlessly, while the balancer has no notion of how close the fuse really is to tripping. Backlog item "[Load Balancer] Proportional Overload Timing" asks for exactly this.

## What Changes

- Replace the instant battery cut and the separate EV pause delay with one time-based fuse overload model used for all loads in `executor/load_balancer.py`. Shed order is unchanged (give-way order: battery, EV, water heater by default).
- Per-phase thermal accumulation: heat builds while a phase is over its fuse rating and cools at the same rate while under it. The balancer acts on the worst phase. Applies to both fuse types; only the consequence differs (a 3-pole Typ C trips all poles, a Diazed blows that phase only).
- Fuse presets "Typ C" (default), "Diazed gG" and "Custom". Curves are in multiples of the rated current (In), so one curve per preset covers 16-35 A. Values are read from manufacturer graphs (accuracy about +/-30%) and interpolated log-log.
- New user setting "safety %": Darkstar acts when accumulated heat reaches safety% of the trip time. Default depends on the preset (Typ C 80%, Diazed 65%, Custom 80%).
- Heat is measured against `main_fuse_a` (not the target margin). Below the curve's first timed point no heat builds; from 1.0x up to it heat holds; below 1.0x it cools at the rate it built.
- Immediate cut has no fixed multiple: cut at once when the safety-scaled trip time at the current overload is shorter than one sensor reading interval.
- Missing or stale phase readings keep today's behaviour (immediate cut on a reading over the limit).
- Heat state is in memory: 0 on restart, reset when `fuse_preset`, custom points or `main_fuse_a` change.
- New config keys `fuse_preset`, `fuse_safety_percent`, `fuse_custom_points`.
- A heat-triggered reduction brings the phase down to the target margin limit so it cools; safety % valid range 50-100; settings UI warns when `executor.interval_seconds` > 15 with load balancing on.
- Restore after a cut only once the phase has cooled below 50% heat, replacing the fixed 60 s ramp timing; the ramp step size (`increase_step_a`) is kept.
- `load_balancing.pause_debounce_s` and `load_balancing.severe_overload_percent` are removed and added to the deprecated-key list in `backend/config_migration.py` (`remove_deprecated_keys`), so existing configs are cleaned on startup without errors. Release note line (for the release author, `docs/RELEASE_NOTES.md` is not touched by this change): "Load balancer: the pause delay and immediate-pause settings are replaced by a fuse model (Typ C / Diazed gG / Custom) with a safety % setting."
- Settings UI: preset select, safety %, and the two custom points when Custom is selected.
- Remove the matching item from `docs/BACKLOG.md`.

## Capabilities

### New Capabilities
- `fuse-overload-timing`: time-current fuse model, per-phase heat accumulation, presets, safety %, cut and restore rules, config keys and settings UI.

### Modified Capabilities
- `phase-load-balancing`: throttle trigger, pause rules, 1-phase relief trigger, ramp-up hold-off, battery cut and ramp-back, target margin.
- `load-balancing-settings`: graceful degradation keys and defaults.

## Impact

- Code: `executor/load_balancer.py` (`LoadBalancer._resolve_battery`, `_resolve_ev_decision`, `_degrade_at_floor`, `_severe_phases`, shed handling in `tick`), `executor/config.py` (`LoadBalancingConfig`, loader around line 539), `backend/api/routers/config.py` (`_validate_graceful_degradation_ranges`), `backend/config_migration.py` (`DEPRECATED_NESTED_KEYS`), `config.default.yaml` (`load_balancing:`), `frontend/src/pages/settings/types.ts`, `frontend/src/pages/settings/LoadBalancingTab.tsx`, `frontend/src/pages/settings/search/guides.ts`.
- Tests: `tests/executor/test_load_balancer*.py`, `tests/config/test_graceful_degradation_config.py`, `tests/executor/test_config.py`, frontend settings tests.
- Specs: `openspec/specs/phase-load-balancing/spec.md`, `openspec/specs/load-balancing-settings/spec.md`.
- Docs: `docs/BACKLOG.md` (item removed). No database change, no new dependency.
