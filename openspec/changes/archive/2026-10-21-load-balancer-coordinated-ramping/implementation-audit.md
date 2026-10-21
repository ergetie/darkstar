# Coordinated ramping implementation audit

All scenario rows below identify a real regression and the corresponding code path. Paths are relative to the repository root. Existing scenarios repeated by a modified requirement retain their earlier regression coverage.

Additional frontend evidence: `frontend/src/pages/settings/__tests__/LoadBalancingTab.test.tsx` renders the advanced global fields; `GiveWayListEditor.test.tsx` exercises power edits, sensor help and minimum on/off edits.

## Root cause coverage (tasks 7.x)

| Root cause | Evidence |
| --- | --- |
| 1 plan jump | `test_plan_rise_from_3_to_6_kw_is_one_step_not_a_jump` |
| 2–3 independent ramps/lagging average | `test_only_one_entry_gets_the_step_rearmost_first`, `test_lagging_average_does_not_hide_a_granted_step`, `test_ev_and_battery_never_overshoot_over_a_ramp` |
| 4 restore ignores power | `test_heater_waits_for_room_for_its_power`, `test_unknown_power_needs_the_whole_phase_free` |
| 5 shed skips charger debounce | `test_shed_waits_for_charger_pause_debounce` |
| 6 lagging measured battery blocks cut | `test_cut_with_measured_charge_below_the_cap`, engine `test_reducible_ignores_lagging_measured_charge` |
| 7 repeated sample cuts | `test_same_sample_is_not_cut_twice`, `test_severe_duplicate_sample_does_not_cut_again`, `test_measured_cut_response_allows_next_cut_before_timeout` |
| 8 battery flap/resume | `test_flapping_lengthens_the_confirm_time`, `test_resumes_at_profile_minimum_not_full_headroom` |
| 9 stale battery | `test_min_charge_then_pause_then_recover_through_confirm` |
| 10 actuator/switch wear | fast/unmeasured pacing tests; `test_write_layer_anti_wear.py`; `TestPlannedSwitches`; engine `TestWaterHeaterMinTimes` |
| 11 voltage | `test_measured_voltage_converts_watts_to_amperes`, engine `test_fresh_voltage_is_exposed_stale_one_is_not` |
| 12 sign | engine `TestPhaseSignConvention` |
| 13 futile replan | full executor ticks in `test_sustained_balancer_constraint_never_requests_replan`, real/idempotent migration tests |
| 14 observability | `test_ring_buffer_keeps_newest_ticks`, `test_decision_change_is_logged_once`, diagnostic bundle trace/failure tests |

The ten-minute battery + EV + 3.1 kW heater simulation asserts no overload longer than one 5 s sensor interval over the entire horizon, including startup and no heater cycling faster than 300 s. Planner tests cover 4 minutes remaining, the last 1/15/30/59 seconds, boundary equivalence, scaled forecasts, kW conversion and the real pipeline's `now_override` slot.

## Audit corrections

The resumed audit removed the earlier draft's full-plan fresh battery start, one-amp unknown-power tolerance, severe duplicate-cut bypass and one-minute planner floor. All increase paths (including initial starts, plan switches, resumes and 1→3 phase return) now use shared room; healthy entries spend it in reverse list order. Custom excess-PV writes cannot override a balancer shed. Phase expansion reservations cannot be settled by an unchanged one-phase measurement.

`./scripts/lint.sh` invokes forbidden `pnpm` commands, so its exact installed-tool equivalents are run directly with the cache venv and frontend node_modules bins. No dependency installation, archive or git staging/commit/push is performed.

## phase-load-balancing

Code path: `LoadBalancer.tick`, `_room_a`/`_grant_a`, `PendingLedger`, `_resolve_ev_decision`, `_resolve_battery`, `_refit_paused`, `restore_shed`, `relief_needed`; engine phase parsing/dispatch.

| Scenario | Regression evidence |
| --- | --- |
| EV and battery do not ramp together | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_only_one_entry_gets_the_step_rearmost_first` |
| Lagging average does not hide a granted step | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_lagging_average_does_not_hide_a_granted_step` |
| Plan step-up is gated | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_plan_rise_from_3_to_6_kw_is_one_step_not_a_jump` |
| Spending in the same tick is counted | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_restore_is_counted_in_the_ledger_for_entries_above` |
| Heater restore needs room for its power | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_heater_waits_for_room_for_its_power` |
| Unknown power uses worst case | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_unknown_power_needs_the_whole_phase_free` |
| Restore does not oscillate | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_no_oscillation_and_no_sustained_overload` |
| Charger debounce pending | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_shed_waits_for_charger_pause_debounce` |
| Duplicate reading | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_same_sample_is_not_cut_twice` |
| Cut not yet reflected | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_cut_not_yet_reflected_waits_for_response` |
| Overload persists after the response timeout | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_overload_after_response_timeout_cuts_again` |
| Lagging charge measurement | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_cut_with_measured_charge_below_the_cap` |
| Flapping battery | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_flapping_lengthens_the_confirm_time` |
| Resume amount | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_resumes_at_profile_minimum_not_full_headroom` |
| Fast actuator ramps at its own pace | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_fast_actuator_next_step_as_soon_as_settled` |
| Slow or unmeasurable actuator | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_next_step_waits_for_pacing_when_unmeasured` |
| No churn | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_fast_charger_ramps_as_soon_as_step_is_measured` |
| Overload cut ignores the interval | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_reductions_are_never_paced` |
| Water heater minimum off time | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_restore_waits_for_minimum_off_time` |
| Trigger swapped | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_swapped_trigger_changes_only_when_a_reduction_starts` |
| Measured voltage | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_measured_voltage_converts_watts_to_amperes` |
| Export phase | `tests/executor/test_coordinated_ramping_engine.py` — `test_export_phase_counts_as_zero_amps` |
| Inverted sensor | `tests/executor/test_coordinated_ramping_engine.py` — `test_inverted_sensor_import_negative` |
| Transition logged once | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_pause_transition_is_logged` |
| Buffer bound | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_ring_buffer_keeps_newest_ticks` |
| Load hovers just under the fuse limit | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_load_hovering_at_95_percent_blocks_increase` |
| Headroom recovers | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_quiet_night_ramps_to_full_planned_current` |
| One-second spike does not unwind a ramp-up decision | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_one_second_spike_does_not_pause` |
| Decrease uses the momentary reading | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_decrease_uses_the_momentary_reading` |
| Setpoint increases gated by target margin | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_increase_capped_by_momentary_headroom` |
| Restores use the averaged reading | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_shed_restore_waits_for_averaged_margin` |
| No increases without fresh averaging samples | `tests/executor/test_load_balancer_graceful_degradation.py` — `test_increases_blocked_after_startup_until_window_fills` |
| Relief after the washing machine stops | `tests/executor/test_load_balancer_battery.py` — `test_ramp_back_after_hold_off_and_never_above_plan` |
| Paused battery blocks restores above it | `tests/executor/test_load_balancer_battery.py` — `test_paused_battery_blocks_restore_of_shed_above` |
| Stale L1 while throttled | `tests/executor/test_load_balancer_coordinated_ramping.py` — `test_min_charge_then_pause_then_recover_through_confirm` |

## planner

Code path: `PlannerPipeline.generate_schedule` flooring/scaling; `KeplerSolver.solve` shared slot hours; `kepler_result_to_dataframe`; executor tick.

| Scenario | Regression evidence |
| --- | --- |
| Grid limit holds in a partial slot | `tests/planner/test_kepler_partial_slot_flows.py` — `test_grid_import_in_partial_slot_respects_the_limit` |
| Battery energy bounded by remaining time | `tests/planner/test_kepler_partial_slot_flows.py` — `test_battery_energy_bounded_by_remaining_time_and_soc_reflects_it` |
| Slot boundary unchanged | `tests/planner/test_kepler_partial_slot_flows.py` — `test_boundary_plan_is_unchanged` |
| now_override rounding | `tests/planner/test_kepler_partial_slot_flows.py` — `test_pipeline_now_override_keeps_the_in_progress_slot` |
| Sustained throttling | `tests/executor/test_coordinated_ramping_engine.py` — `test_sustained_balancer_constraint_never_requests_replan` |

## ev-target-charging

Code path: `KeplerSolver.solve` shared `slot_hours` and EV energy/surplus terms; result conversion.

| Scenario | Regression evidence |
| --- | --- |
| Replan 7 minutes into a slot | `tests/planner/test_kepler_ev_partial_slot.py` — `test_replan_7_min_into_slot_caps_ev_energy` |
| Surplus in a partial first slot | `tests/planner/test_kepler_ev_partial_slot.py` — `test_surplus_in_partial_first_slot_uses_remaining_time` |
| Replan at slot start | `tests/planner/test_kepler_ev_partial_slot.py` — `test_boundary_replan_unchanged` |
| Remaining-duration bound applies to surplus energy | `tests/planner/test_kepler_ev_partial_slot.py` — `test_surplus_in_partial_first_slot_uses_remaining_time` |
| Planned kW and other flows for the partial slot | `tests/planner/test_kepler_ev_partial_slot.py` — `test_partial_slot_reports_higher_kw_for_same_energy` |

## config-migration

Code path: `DEPRECATED_NESTED_KEYS`, `remove_deprecated_keys`, `_migrate_config`.

| Scenario | Regression evidence |
| --- | --- |
| Old config | `tests/config/test_coordinated_ramping_config.py` — `test_old_config_drops_only_the_key` |
| Fully migrated config | `tests/config/test_coordinated_ramping_config.py` — `test_full_migration_is_idempotent_and_template_does_not_readd_it` |

## diagnostics-export

Code path: `export_diagnostics`, `_get_balancer_trace`, `_write_bundle_sync`.

| Scenario | Regression evidence |
| --- | --- |
| Bundle contents | `tests/api/test_diagnostics_export.py` — `test_bundle_contents` |
| Config is exported as is | `tests/api/test_diagnostics_export.py` — `test_bundle_contents` |
| Secrets file is never included | `tests/api/test_diagnostics_export.py` — `test_bundle_never_reads_secrets` |
| Database is in the bundle | `tests/api/test_diagnostics_export.py` — `test_bundle_contents` |
| One item fails | `tests/api/test_diagnostics_export.py` — `test_bundle_survives_a_failing_balancer_trace` |
| Manifest content | `tests/api/test_diagnostics_export.py` — `test_bundle_contents` |

## ev-charge-failure-detection

Code path: `_check_ev_charge_failure`, `_request_ev_failure_replan` (independent five-minute cooldown).

| Scenario | Regression evidence |
| --- | --- |
| Failure triggers replan | `tests/executor/test_ev_charge_failure_detection.py` — `test_failure_requests_replan` |
| Recovery triggers replan | `tests/executor/test_ev_charge_failure_detection.py` — `test_recovery_requests_replan` |
| Recovery shortly after failure | `tests/executor/test_ev_charge_failure_detection.py` — `test_recovery_requests_replan` |
| Cooldown | `tests/executor/test_ev_charge_failure_detection.py` — `test_recovery_within_cooldown_is_deferred_not_dropped` |
| Recovery inside the cooldown is deferred, not dropped | `tests/executor/test_ev_charge_failure_detection.py` — `test_deferred_recovery_waits_for_power` |
| Independent of balancer rate limit | `tests/executor/test_ev_charge_failure_detection.py` — `test_balancer_rate_limit_does_not_block_failure_replan` |

## ev-charging-replan

Code path: Removed balancer-triggered replan: full-tick sustained constraint test above; plug/unplug/manual/failure paths retained.

| Scenario | Regression evidence |
| --- | --- |

## load-balancing-settings

Code path: `load_executor_config`, `_parse_load_balancing_config`, `heal_give_way_order`, config-save validators, `config.default.yaml`, `loadBalancingSections`, `GiveWayListEditor`.

| Scenario | Regression evidence |
| --- | --- |
| Existing custom load | `tests/config/test_coordinated_ramping_config.py` — `test_existing_custom_load_loads_without_new_fields` |
| Defaults documented | `tests/config/test_coordinated_ramping_config.py` — `test_shipped_coordination_defaults_are_documented` |
| grid_current key names kept for power sensors | `tests/executor/test_config.py` — `test_full_section_with_loads` |
| Grid voltage sensors and load_balancing section keys | `tests/config/test_coordinated_ramping_config.py` — `test_values_are_read` |
| Load entries and give-way order list | `tests/executor/test_config.py` — `test_full_section_with_loads` |
| Legacy priority keys migrated to give_way_order | `tests/config/test_give_way_migration.py` — `test_both_old_fields_build_full_order` |
| give_way_order self-healing on config load | `tests/config/test_give_way_migration.py` — `test_missing_shed_appended_at_end` |
| Defaults are safe | `tests/config/test_graceful_degradation_config.py` — `test_upgrade_picks_safe_defaults` |
| Fuse rating is independent of planner budget | `tests/config/test_coordinated_ramping_config.py` — `test_fuse_rating_does_not_change_planner_import_budget` |
| Existing current-sensor-only config is unaffected | `tests/executor/test_config.py` — `test_defaults_when_section_absent` |
| Power sensor configured for a phase | `tests/config/test_config_validation.py` — `test_recognized_power_unit_is_not_an_error` |
| A type: current charger cannot be added to loads[] | `tests/config/test_config_validation.py` — `test_type_current_charger_in_loads_is_error` |
| Old priority fields are migrated to give_way_order | `tests/config/test_give_way_migration.py` — `test_both_old_fields_build_full_order` |
| Newly added charger self-heals into the order | `tests/config/test_give_way_migration.py` — `test_new_charger_appended_after_last_charger_entry` |
| Charger switched back to binary drops out of the order | `tests/config/test_give_way_migration.py` — `test_retyped_charger_dropped` |


## Explicit reconciliation of earlier severe-overload scenarios

The delta also carries the complete modified EV feedback requirement so earlier severe shed-plus-EV scenarios cannot contradict the new per-phase sample guard. Severity detection and pause debounce thresholds are unchanged.

| Scenario | Code path | Regression evidence |
| --- | --- | --- |
| Stove turns on while EV charges | `_resolve_ev_decision` | `tests/executor/test_load_balancer.py` / `test_stove_spike_reduces_to_10a_or_lower` |
| Car draws below its setpoint during an overload | effective draw baseline and pool relief | `tests/executor/test_ev_measured_draw.py` / `test_reduction_and_relief_from_measured_draw` |
| Balancer never exceeds the planned charging level | planner target cap | `tests/executor/test_load_balancer.py` / `test_never_exceeds_planner_target` |
| Two chargers share an overloaded phase, higher-listed gives way first | top-down reduction pass | `tests/executor/test_load_balancer.py` / `test_higher_listed_charger_gives_way_first_and_fully_resolves_deficit` |
| Shed load ordered above a charger gives way before the charger slows | shed and pending-response guard | `tests/executor/test_load_balancer.py` / `test_shed_above_charger_gives_way_before_charger_slows` |
| Severe overload pauses the charger even while a shed load gives way | severe detection plus hard sample guard | `tests/executor/test_load_balancer.py` / `test_severe_overload_waits_for_existing_shed_response`, `test_recovery_after_severe_pause_follows_confirm_window_and_margin` |
| Single dynamically-throttled charger is unaffected by ordering | top-down pass | `tests/executor/test_load_balancer.py` / `test_single_charger_is_unaffected_by_ordering` |
| Throttle computed from effective baseline | effective draw and relief accounting | `tests/executor/test_ev_measured_draw.py` / `test_reduction_and_relief_from_measured_draw` |
| Raising the setpoint with positive headroom | `_grant_a` | `tests/executor/test_load_balancer.py` / `test_step_limited_ramp_toward_target` |
| Top-down give-way ordering | ordered reductions | `tests/executor/test_load_balancer.py` / `test_higher_listed_alone_insufficient_shares_remainder_with_next` |
| Charger holds while a shed entry above gives way | pending relief and sample guards | `tests/executor/test_load_balancer.py` / `test_non_severe_overload_during_shed_hold_keeps_hold`, `test_severe_overload_waits_for_existing_shed_response` |
| Backward-compatible behavior of give-way ordering | retained order, new guard timing | `tests/executor/test_load_balancer.py` / `test_default_order_reproduces_two_tier_behavior` |


## Final apply-check status (handoff)

- Ruff check/format: pass; final Pyright: 0 errors, 0 warnings.
- Frontend Prettier, ESLint, TypeScript: pass.
- Full frontend Vitest: 65 files / 656 tests pass.
- Initial full pytest: 3400 pass / 1 failure in 652.23 s. Resolved fixture expectation:
  `FAILED tests/executor/test_ev_keep_on.py::TestCurrentChargerKeepOnMinimumCurrent::test_load_balancer_input_uses_configured_minimum`
  `E AssertionError: assert None == 8`
  The minimum-current mapping test now sets a zero averaging window; startup-averaging protection is independently regressed.
- Final full pytest subsequently completed: **3420 passed, 4371 warnings**; see the final verified results below.
- OpenSpec change strict: pass; all strict: 129 pass / 0 fail.
- `git diff --check`: pass. No TODO/FIXME in changed capability implementation or regression files.

### Independent verification corrections

Task 7.13 now runs two ten-minute simulations from physically valid states, with no startup exclusion: a steady household with the heater initially shed and an appliance-spike variant with the heater initially on. Both flexible loads request full plans concurrently and must actually increase. Both variants must physically restore the 3.1 kW heater exactly once after at least 300 s off; the spike variant must actually shed it once. Every sensor interval from t=0 through t=600 participates in the overload assertion. The entire coordinated-ramping test file passes (58 regressions).

The new regression files were explicitly formatted; repository-wide Ruff excludes tests, so its general format check alone does not cover them.

## Independent verification scorecard

| Dimension | Result |
| --- | --- |
| Completeness | 46/46 tasks; all 14 root causes regressed |
| Correctness | All 86 delta scenarios mapped above; 27 requirement blocks including 2 intentional removals |
| Coherence | Shared room/ledger, reverse restore order, fresh-sample cut guard, adaptive pacing and common partial-slot duration retained |

A critical startup issue found during verification is fixed: water heaters previously inherited `SystemState.water_temp_target` (an unpopulated legacy scalar defaulting to 60) as their on-state. Each balanced heater now reads its own switch/temperature target, reusing the existing first-heater temperature read, and unreadable states conservatively enter the shared start/restore gate. Binary EV shed entries likewise obtain their actual switch state and derive plan intent through `_charger_should_be_on`; their initial starts now share the gate too. Custom entities already used their own real state. Regressions: `test_balanced_heater_states_are_per_device`, `test_heater_initial_start_requires_shared_room`, `test_binary_charger_start_uses_shared_room`.

No scope/design deviation was required for these fixes. No critical, warning or suggestion findings remain. Main specs remain unsynchronized: the delta's explicit import-sign convention and fresh-sample guard govern the older magnitude-only and severe-double-cut wording. No archive was performed.

A second integration issue is fixed: entries explicitly planned off no longer count as outstanding restore demand, so they cannot indefinitely block higher-listed chargers, battery or shed loads. `test_planned_off_lower_entry_does_not_block_higher_restore` checks that a higher entry actually restores and spends ledger room while the lower entry stays off. Reverse-order arbitration for entries that do want to run is unchanged.

## Changed files (38)

- `backend/api/routers/config.py`
- `backend/api/routers/system.py`
- `backend/config_migration.py`
- `config.default.yaml`
- `docs/USER_MANUAL.md`
- `executor/actions.py`
- `executor/config.py`
- `executor/controller.py`
- `executor/engine.py`
- `executor/load_balancer.py`
- `executor/override.py`
- `frontend/src/lib/api.ts`
- `frontend/src/pages/settings/__tests__/LoadBalancingTab.test.tsx`
- `frontend/src/pages/settings/components/GiveWayListEditor.test.tsx`
- `frontend/src/pages/settings/components/GiveWayListEditor.tsx`
- `frontend/src/pages/settings/search/guides.ts`
- `frontend/src/pages/settings/types.ts`
- `openspec/changes/load-balancer-coordinated-ramping/design.md`
- `openspec/changes/load-balancer-coordinated-ramping/implementation-audit.md`
- `openspec/changes/load-balancer-coordinated-ramping/specs/phase-load-balancing/spec.md`
- `openspec/changes/load-balancer-coordinated-ramping/tasks.md`
- `planner/pipeline.py`
- `planner/solver/adapter.py`
- `planner/solver/kepler.py`
- `planner/solver/types.py`
- `tests/api/test_diagnostics_export.py`
- `tests/config/test_coordinated_ramping_config.py`
- `tests/executor/test_balancer_replan_and_notify.py`
- `tests/executor/test_battery_balancer_engine.py`
- `tests/executor/test_coordinated_ramping_engine.py`
- `tests/executor/test_ev_keep_on.py`
- `tests/executor/test_load_balancer.py`
- `tests/executor/test_load_balancer_battery.py`
- `tests/executor/test_load_balancer_coordinated_ramping.py`
- `tests/executor/test_load_balancer_e2e_dry_run.py`
- `tests/executor/test_load_balancer_graceful_degradation.py`
- `tests/executor/test_write_layer_anti_wear.py`
- `tests/planner/test_kepler_partial_slot_flows.py`

## Final verified check results

- Tasks: **46/46** complete.
- Full pytest on the final production code: **3420 passed, 4371 warnings in 595.04 s (0:09:55)**, exit 0. Log: `/home/minbota/.cache/darkstar-scratch/ramping-pytest-verified-final.log`.
- Focused final verifier regressions: **58** balancer tests and **27** engine tests pass; the earlier broader planner/config/write-layer selection passed **132** before adding the final startup/arbitration cases.
- Ruff check and format: pass; all five new regression files also explicitly formatted.
- Pyright on final code: **0 errors, 0 warnings**.
- Frontend installed-tool formatting, ESLint and TypeScript: pass in apply; unchanged during verification.
- Full frontend Vitest: **65 files, 656 tests pass** in apply; unchanged during verification.
- `openspec validate load-balancer-coordinated-ramping --strict`: pass.
- `openspec validate --all --strict`: **129 passed, 0 failed**.
- `git diff --check`: pass.
- Current failures: none. Existing dependency/runtime warnings remain; no dependency changes made.
- Literal lint script intentionally replaced with installed-tool equivalents because it invokes the explicitly forbidden `pnpm` and default project venv. No archive, staging, commit, push or production access occurred.

## Sync and archive completion — 2026-10-21

All 46 tasks and all planning artifacts are complete. Synced delta requirements into eight main capabilities: phase-load-balancing, load-balancing-settings, planner, ev-target-charging, ev-charging-replan, ev-charge-failure-detection, diagnostics-export and config-migration. Preserved unrelated scenarios; reconciled the prior direction-independent headroom and measured-battery-charge bound with the explicit new signed-import and cap/import requirements. Shortened two long requirement descriptions without semantic changes so main-spec strict validation passes, and corrected the obsolete minimum-write-interval cross-reference to adaptive step pacing.

Before archive, change strict and all strict validation passed (129/129). The change is archived at `openspec/changes/archive/2026-10-21-load-balancer-coordinated-ramping/` with its metadata intact. No implementation or test changes were made during sync/archive, so the final verified test results above remain applicable.

The pending `fuse-overload-timing` change was read only and remains unmodified. Before implementation, reconcile its same-tick immediate cuts/hold-after-shed wording with the fresh-sample and bounded-response guards, retain shared-gate battery ramp and escalating resume back-off when replacing thermal hold-off, and replace pause-debounce-linked shed timing through the pluggable trigger. Strict validation checks structure, not these semantic overlaps.

After archive, `openspec validate --all --strict`: **128 passed, 0 failed** (one fewer active change); `git diff --check`: pass. The fuse-overload-timing working tree remains clean. Nothing staged, committed or pushed.
