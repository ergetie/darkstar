# Tasks: Load Balancing Completion

## 1. Config schema & migration

- [x] 1.1 Add `give_way_order[]`, `notify_interventions`, `replan_after_throttled_s` to `executor/config.py` (`LoadBalancingConfig`); remove `charger_priority` and `loads[].priority` from parsing; add self-healing of `give_way_order` on config load (append missing chargers after last charger entry, append missing shed loads at end, drop dangling/retyped references with logged warning)
- [x] 1.2 Write the startup migration in `backend/config_migration.py`: build `give_way_order` from `charger_priority` (fallback `ev_chargers[]` position) + `loads[].priority` ascending, drop both old keys; idempotent and logged
- [x] 1.3 Update `config.default.yaml` comments/example for the new schema (give-way list, notify toggle, replan threshold)
- [x] 1.4 Unit tests in `tests/config/`: migration (both old fields, one old field, ties, missing devices, idempotency), self-healing (new charger appended, retyped charger dropped, missing shed appended)

## 2. Validation

- [x] 2.1 Update startup validation: `loads[]` no longer requires/accepts `priority`; `type: current` charger in `loads[]` error message now points to the give-way list; `give_way_order` references validated
- [x] 2.2 Add non-blocking warning: `load_balancing.enabled` with `executor.interval_seconds > 15` (names both keys, recommends ≤ 15 s), surfaced through the existing validation-feedback path so the UI can render it
- [x] 2.3 Add non-blocking warning: `type: current` charger without `soc_sensor` (names the charger and the progress-tracking consequence)
- [x] 2.4 Validation tests in `tests/config/test_config_validation.py` for both warnings and the updated errors

## 3. Balancer resolver rewrite

- [x] 3.1 Rework `executor/load_balancer.py` `tick()`: replace the two-tier gate (`ev_at_floor_or_paused`) with the top-down `give_way_order` resolver — charger entries throttle toward floor then pause (position-aware pausing per spec), shed entries switch off, each entry gives way fully before the next is touched
- [x] 3.2 Implement exact reverse-order restore across the whole list (last to give way restores first), keeping existing resume delay + margin gating per entry
- [x] 3.3 Update `executor/engine.py` `_run_load_balancer` to build ordered inputs from `give_way_order` (drop priority-map plumbing); keep status payload shape with per-charger and per-shed entries
- [x] 3.4 Update balancer unit tests (`tests/executor/test_load_balancer.py`): default/migrated order reproduces old two-tier behavior tick-for-tick; new cases — shed-above-charger order, position-aware pause (charger not paused while higher-listed shed can give way), multi-charger ordering by position
- [x] 3.5 Update `tests/executor/test_load_balancer_e2e_dry_run.py` to the new schema with a default order and confirm unchanged end-to-end behavior; add one e2e case with a shed entry ordered above the charger

## 4. Early replan after sustained throttling

- [x] 4.1 Track per-charger continuous balancer-constrained duration in the executor (setpoint below planner target or paused, while the slot plans charging; planner-intended low targets excluded); reset on target reached / slot stops planning charge / trigger fired
- [x] 4.2 Fire one replan through the existing plug/unplug replan mechanism when duration exceeds `replan_after_throttled_s`; rate-limit to one balancer-triggered replan per planner interval
- [x] 4.3 Tests: fires at threshold, respects rate limit, resets on recovery, ignores planner-intended reductions

## 5. Intervention notifications

- [x] 5.1 Hook balancer state transitions (shed, pause, stale-fallback only) to the existing dispatcher/`backend/notify.py` path, gated by `notify_interventions`, one notification per transition with the human-readable reason
- [x] 5.2 Tests: shed/pause/stale notify once, throttle/ramp transitions never notify, toggle off suppresses all

## 6. Give-way list UI

- [x] 6.1 Build a reusable `OrderedListEditor` component (drag reorder + always-available up/down buttons, caller-rendered row content) with component tests
- [x] 6.2 Replace the "Dynamically Throttled Chargers" + "Shed as Last Resort" sections in the Load Balancing tab with one give-way list bound to `give_way_order`: auto-listed charger rows (read-only except position; name, phases, capability line "Throttle max → min A, then pause", link to EV tab), add/remove shed rows (device picker offering only binary chargers, phases, capability line "Switch off"), plain-language top-down copy; remove all numeric priority fields (`ChargerPriorityEditor`, priority column in `BalancedLoadsEditor`)
- [x] 6.3 Update settings form plumbing (`types.ts`, `logic.ts`, `utils.ts`, `useSettingsForm`, API types in `lib/api.ts`) for the new schema
- [x] 6.4 Render the slow-tick inline warning in the Load Balancing tab when enabled with `executor.interval_seconds > 15`
- [x] 6.5 Add the notifications toggle field to the Load Balancing settings section
- [x] 6.6 Frontend tests: reorder persists order, charger rows not removable, shed add/remove, warning visibility

## 7. EV tab clarity

- [x] 7.1 Rename the option label to "Dynamic current (adjustable amps)" in `EntityArrayEditor` (config value `current` unchanged) and render the consequence explainer while selected (planner-set amps, automatic give-way membership + link, PV-surplus eligibility)
- [x] 7.2 Show the inline no-SoC-sensor warning on `type: current` chargers without `soc_sensor`
- [x] 7.3 Tests for explainer visibility and no-SoC warning

## 8. Truthful-when-quiet UI

- [x] 8.1 Add the freshness indicator to `LoadBalancerStatusCard` ("updated Xs ago" from the live-metrics payload timestamp, continuously updating, stale styling when age materially exceeds the tick interval); show raw per-phase measurement as secondary text
- [x] 8.2 Add the execution history explainer header: last tick time and outcome (from executor status) plus the change-only + heartbeat recording policy copy
- [x] 8.3 Tests: freshness indicator updates and flags staleness; history header renders last tick info

## 9. Docs & wrap-up

- [x] 9.1 Mark the "Unified Priority List for All Balanced Loads" backlog item as promoted to this change in `docs/BACKLOG.md`
- [x] 9.2 Run full backend + frontend test suites and `scripts/ci_local.sh`; verify end-to-end against the live dev backend (reorder → save → status reflects order; freshness indicator live at 5 s tick)
