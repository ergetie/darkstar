# Verification report

**Implementation status: complete and archived.** The prior final implementation review recorded 22/22 tasks and passed the full checks (2,758 Python and 517 frontend tests). A post-archive contract audit expanded the specs to 22 requirements and 91 scenarios by including pre-existing API, Grid and baseline requirements; this spec-only expansion awaits a fresh independent review.

## Production-history evidence

On 2026-10-07, a fresh SQLite backup was created from `/opt/darkstar/data/planner_learning.db` after opening the production source with `mode=ro`. Production runtime configuration reports battery capacity `27 kWh`, minimum SoC `15%`, and maximum SoC `100%`. The local user-edited capacity remains `34.2 kWh`; it was not changed.

The production copy contains 32,522 observations from `2025-11-03T19:45+01:00` through `2026-10-09T00:00+02:00`. It has 11,092 rows with only `source=recorder`, 21,430 rows without valid flags, and no `recording` metadata or legacy attestations. The development mirror had the same row count and date extrema, but 11,089 recorder-only rows and one row with observed metadata; it was not treated as an authoritative production snapshot. The source maximum is later than the review date, so the comparison window was explicitly ended at the current local completed-slot boundary, `2026-10-07T06:15+02:00`.

The production-data fit returned `insufficient_data / unverified_history`: 2,880 rows considered, zero eligible, and 2,880 excluded as unknown provenance. No factors or holdout diagnostics were available. Deployment history identifies a battery snapshot-to-cumulative-meter transition on 2026-09-18 and all-power-history recording from 2026-10-05, but row-level component acceptance, EV/water paths, fallback treatment, and live SoC history cannot be recovered from the stored metadata. No historical interval was certified for inclusion.

## Local annotation exercise

A conservative exclusion dry run on the disposable production copy covered observations before the known non-snapshot-shaped transition at `2026-09-18T22:00+02:00`. It affected 30,593 unknown rows and reported no conflicts. Apply changed only comparison metadata; the full numeric measurement digest was unchanged. During the temporary annotation, the current 30-day result remained `insufficient_data / unverified_history` with zero eligible rows (1,119 explicitly excluded, 1,761 unknown), and no factors or holdout diagnostics. Undo restored all 30,593 annotations; all 32,522 parsed quality-flag objects were semantically identical to their pre-apply state. The SQLite backup and detailed audit were removed after verification. Production was never annotated.

No inclusion annotation was attempted. The deployment evidence is insufficient to establish the required per-component and SoC claims, so older history remains unverified rather than being inferred from dates or fit results.

## UI evidence

The installed Chromium runner captured Dashboard collecting-history, unsupported-period, and accuracy-failure states at 1440px and 390px widths in light and dark themes, plus the Design System cost-chart fixtures at both widths and themes. There were zero browser page errors. Actual electricity costs remained visible and no battery-comparison amounts appeared in unavailable states. Design System cards fit within their 342px mobile section; the page reports 408px scroll width at a 390px viewport, an existing page-level overflow outside these card fixtures.

Temporary screenshots and machine-readable capture results were kept under `/tmp/provenance-*` only; they contain test fixtures, not production observations.

## Independent reviewer handoff — 2026-10-07

The user approved a new policy during independent verification: show an explicitly labelled estimate based on configured losses immediately, and replace it with a verified result after the existing calibration checks pass. The policy has now been amended into the proposal, design, delta requirements and tasks, and implemented below. This handoff predates the fresh final verification below; its pending items have since been implemented and re-reviewed.

The independent review fixed these defects within the original approved scope:

- Observation upserts now retain schema, boundary, semantics and algorithm identity per accepted/retained component. A partial current correction cannot elevate an untouched unsupported algorithm. SoC start/end provenance is stored independently; a live end correction cannot certify a retained cached/unknown start. Incoming and existing exclusions survive.
- Read-side attestation validates its complete numeric preimage, including SoC/prices, and rejects manual changes. Observed component/end-SoC identities are checked independently of the row summary. Unsupported latest schema/method metadata cannot select an older fitted cohort.
- Cache identity binds canonical candidate-window numerical values as well as provenance/cohort/configuration. Key preparation, cohort processing and fitting execute in worker threads. Missing-period diagnostics use the actual bounded cohort classification rather than unmatched counts.
- The local annotation tool fails closed on malformed/opaque quality metadata; dry-run eligible counts use provenance and numeric eligibility. Undo refuses keys outside comparison ownership. Ownership/preimages are rechecked under the SQLite write lock, backups use exclusive private creation, and a complete audit plus its directory entry are fsynced before commit. Failure removes the tool's partial audit and rolls back metadata.
- Missing enabled load sensors no longer produce trusted derived-history zero metadata; sanitised spike zeros are unknown. Backfill aggregate gaps/derived load paths retain truthful mixed provenance.
- Collecting-history UI copy explains that learning history is needed even when viewing today. This wording had a focused test at handoff; the fresh final verification below completes estimate/verified UI and visual checks.

Validation after these fixes: targeted backend/provenance/annotation/storage/cache/API/recorder suites **125 passed in 22.68s**, with no warning summary; Pyright **0 errors, 0 warnings, 0 informations**; changed Python paths Ruff **All checks passed!**. Logs: `/tmp/provenance-review-targeted-final.log`, `/tmp/provenance-pyright-review.log`. No final full checks were launched because the user approved the policy amendment before this review completed. The earlier visual/production evidence above remains evidence for the original unavailable states, not for the new estimate policy.

The pre-policy delta contained **11 requirements and 45 scenarios** across five capabilities. After the estimate policy amendment, the first implementation audit mapped 14 requirements and 57 scenarios across five capabilities. A post-archive contract audit found additional pre-existing API, command-bar, baseline and Grid & Financial requirements that contradicted estimate fallback behavior. The amended archived deltas and main specs now cover **22 requirements and 91 scenarios across seven capabilities**; the supplement below maps the additional 8 requirements and 34 scenarios.

### Historical implementation handoff

1. Amend proposal/design/delta specs/tasks for estimated-then-verified policy. Keep the 1,000-grid/200-pair, excitation, bounded efficiencies and numeric gates intact for verified calibration. Historical provenance must never be promoted merely to obtain an estimate.
2. Implement a distinct configured-loss estimate: the existing planner AC-bus convention is `GridModel(1, 1)` with configured charge/discharge efficiencies, full capacity and existing limits. Reconstruct both recorded Darkstar actions and simulated self-use with identical assumptions; preserve actual metered cash flow separately. Label the basis explicitly and expose the strict calibration's actual status/reason rather than inventing successful diagnostics.
3. Keep complete contiguous completed-period coverage, finite nonnegative energy, finite prices/SoC and valid finite capacity/limits/factors. Preserve exclusions and reject known backfills/snapshots/cached SoC. Legacy unknown provenance may be an explicitly assumed estimate input only; it must remain calibration-ineligible. Retain the EV discharge prohibition.
4. Reuse the existing economic arithmetic and `simulate_self_use`, but refactor the builder's serialization/validation boundary: `build_comparison` currently requires real `FitDiagnostics`, applies selected-period accuracy gates, emits `status=available/reason=validated` and serializes calibration unconditionally. Passing invented diagnostics or silently bypassing gates would misrepresent an estimate. Keep an explicit strict verified path and separate configured-estimate acceptance policy.
5. Add real SQLite-WAL apply/undo/cache coverage (current cache regressions cover metadata/numeric/config/TTL identity and worker threads), measure actual cache miss/hit and event-loop responsiveness, verify independent trusted/assumed anchors and new API/UI state transitions, and repeat affected Dashboard/Design System captures across mobile/desktop and light/dark.
6. Run final `./scripts/lint.sh` (includes full pytest and frontend checks/tests), strict OpenSpec validation, inspect all diffs, finish task 5.3 and rerun independent verification to genuinely clean. Preserve the unrelated 18-line `docs/BACKLOG.md` edit; do not archive, stage, commit, push, change configuration, modify planner/executor, or touch production/runtime data.

Focused collecting-copy frontend verification: `pnpm test src/components/CommandDomains.test.tsx` — **1 test file passed, 13 tests passed**, duration **770ms**, with no warning/error output. Log: `/tmp/provenance-review-frontend-targeted.log`. The previous **125-pass** targeted result covers seven Python test paths listed in the command log; no production data/configuration was changed by the independent reviewer.


## Configured-loss estimate implementation — 2026-10-07

The approved estimate-then-verified policy is reflected in the proposal, design, calibration, API, baseline, command-bar and Grid & Financial delta requirements and task list. The strict fitted path retains its existing cohort, 1,000-grid/200-pair, directional excitation, holdout, selected-period and cache safeguards. A separate estimate builder shares the same economic arithmetic but uses `GridModel(1, 1)` and the installation-configured charge/discharge efficiencies. Recorded Darkstar actions and simulated self-use use that same model. Estimates require complete contiguous valid inputs and a valid start/end state; explicit exclusions, backfills, known snapshots/mixed components, cached SoC and unsupported modern provenance remain rejected. Unknown legacy recorder rows may appear only under the configured-loss basis, never enter the fit cohort or receive attestation. API estimates expose the real calibration status/reason and only real diagnostics. Cards and charts identify estimate versus verified bases; actual metered costs remain separate.

Strict and estimated SoC anchors are tracked independently. A legacy-only contiguous prior SoC can support an estimate without satisfying verified calibration; a modern unknown/cached endpoint cannot be promoted by an unrelated live end reading. Synthetic regression coverage includes legacy input estimates, unsupported provenance, invalid prices, real diagnostics beside a failed-fit estimate, legacy-prior versus verified anchors, strict verified output, and frontend basis copy.

Focused verification: `tests/test_battery_comparison.py`, `tests/api/test_battery_comparison_api.py`, `tests/api/test_battery_comparison_cache.py`, `tests/test_comparison_history.py`, and `tests/backend/test_measurement_provenance.py` — **91 passed**; changed Python paths Ruff — **All checks passed**; Pyright — **0 errors, 0 warnings, 0 informations**; frontend `CommandDomains` and `CostSeriesChart` — **18 passed**; frontend `tsc --noEmit` — passed; `OPENSPEC_TELEMETRY=0 openspec validate --all --strict` — **118 passed, 0 failed**. Fresh final verification below supersedes this implementation handoff and records the completed checks, performance, visuals and requirement audit. No production DB, local config, schema, dependency, planner or executor was changed.


## Fresh final independent verification — 2026-10-07

All final checks passed. **Ready for archive.**

| Dimension | Final result |
|---|---|
| Completeness | 22/22 tasks; 22/22 current amended requirements mapped to the implementation |
| Correctness | 91/91 current scenarios mapped; strict verified gates preserved |
| Coherence | Provenance, metadata maintenance, configured estimates, verified upgrade and existing economics follow the approved design |
| Review issues | CRITICAL: 0; WARNING: 0; SUGGESTION: 0 within this change |

Implementation, scoped regressions, full checks and visual/performance evidence were complete before archive. The initial independent reviewer read five amended deltas, proposal/design/tasks and affected main specs, and mapped **14 requirements / 57 scenarios**. The post-archive audit below expands the contract sync to **22 requirements / 91 scenarios** by clarifying the already-implemented estimate policy in every affected existing contract. That expansion is pending the fresh independent spec-only review. None of the original fit gates was changed or replaced by synthetic diagnostics.

### Corrections completed in the fresh review

- Incoming `exclude: true` now survives an existing false flag; changed price preimages invalidate legacy attestation alongside energy/SoC corrections.
- Naive stored timestamps retain their missing timezone for comparison rejection; actual metered localization/accounting stays compatible. Cache latest-observation selection ignores naive timestamps safely.
- The public estimate builder enforces its own provenance guard. The only additional boundary assumption is the registered initial schema-v1 encoding that omitted `battery_soc`: every other configured path must match exactly, methods/component identities must remain supported, and live SoC must be valid. It stays calibration-ineligible and receives no metadata rewrite. Changed unrelated sensors or unsupported algorithms are rejected.
- SoC anchors validate the endpoint actually used. The 18-case prior-anchor regression accepts live current-boundary recorder-owned ends independently of unused prior starts/energy, rejects wrong/cached/backfilled ends, exclusions, global backfill, unsupported headers/algorithms/boundaries, non-finite end values and non-contiguity, and keeps unknown-legacy/earlier-encoding anchors estimated only. Selected-period row eligibility remains strict.
- Backfill metadata reflects enabled but unset aggregate inputs and sanitized spikes; recorder/backfill all-disabled device lists produce disabled-zero provenance. Backfills remain ineligible.
- Card/chart basis labels agree, including older `available` fixtures without a basis. Non-finite/missing savings or comparison points are withheld without assertions or crashes. Positive, negative and zero estimates render consistently. Verified copy explains that only the model passed accuracy checks and the counterfactual remains an estimate; estimate copy exposes learning/failure state and legacy input assumptions.

### Current development result and performance

A read-only SQLite URI was used against the existing development database with the unchanged **34.2 kWh** configured full capacity. The initial Today diagnostic found **27/27** expected completed slots through **06:45**, with 26 estimate-eligible rows and one modern row rejected solely for its earlier SoC-omitting fingerprint encoding. All eight component paths on that row were measured/derived history and its SoC was live. Matching the registered earlier encoding fixed the implementation-format blocker without rewriting history or accepting arbitrary boundary changes.

The actual running development HTTP API subsequently returned `estimated / configured_losses`, first **1.048 kr** estimated saving through **06:45**. After the next completed observation arrived, the final-code read-only/API snapshot through **07:00** returned **0.900 kr**, Darkstar modeled comparison **25.871 kr**, self-use modeled comparison **26.771 kr**, and actual gross-metered cash flow **6.006 kr** separately. Calibration remained `insufficient_data / insufficient_compatible_history`: 2,880 considered, four eligible; no fit diagnostics were invented. Selected-input assumption counts were 23 legacy recorder slots and one earlier SoC-mapping slot. The live HTTP response matches; the normal development watcher reloaded without manual restart or process termination.

Final-code estimate endpoint timings: cache miss **0.082325 s**, hit **0.058542 s**, 22 independent event-loop heartbeat ticks, maximum heartbeat gap **0.019201 s**. A separate genuine-fit synthetic 1,200-row measured cohort returned `available` with 960/240 grid train/holdout observations and 959/240 battery train/holdout pairs: miss **0.057701 s**, hit **0.031061 s**, maximum heartbeat gap **0.020780 s**. A configured-efficiency change invalidated the cached object; the cache retained two entries. The real SQLite-WAL regression applies and undoes inclusion metadata with unchanged main-file mtime/size, switches eligible counts 0→2→0, and also invalidates on a numeric correction with unchanged latest timestamp/main-file identity. TTL/16-entry bounds and off-loop fitting are separately tested.

Aggregate logs: `/tmp/provenance-dev-api-final-result.json`, `/tmp/provenance-live-api-final-result.json`, `/tmp/provenance-fit-perf-final-result.json`. Temporary timing databases were removed by their context manager. This review made no direct writes to development observations/configuration or production; the running development recorder continued recording normally.

### Fresh visual verification

Installed Chromium captured **36 cases / 56 screenshots**: Dashboard estimated positive/negative, verified positive/negative, collecting, unsupported, accuracy failure and no-battery across 1440px/390px and dark/light; Design System fixtures in both views at both sizes/themes. There were **zero browser page errors** and **zero Dashboard card overflows**. Visually inspected representative mobile/desktop, light/dark, positive/negative, unavailable and Design System captures. Actual costs remain visible; unavailable states have no saving/control/lines, and legacy 999-kr fixture savings never appear. Comparison endpoints/cards use the same active basis. Mobile Design System sections are 342px within the 390px viewport; existing page-level body width is still 408px outside these fixtures, unchanged by this work.

Capture result: `/tmp/provenance-estimate-visual-summary.json`; detailed fixture-only evidence `/tmp/provenance-estimate-visual-results.json`; screenshots `/tmp/provenance-estimate-dashboard-*` and `/tmp/provenance-estimate-design-*`. No observation rows or credentials enter screenshots/artifacts.

### Validation and scope

The fresh targeted regression run passed **146 tests in 43.91s** across pure calibration, API/18-anchor matrix, recorder and backfill. Earlier fresh annotation/storage/cache regressions passed 110 tests plus the corrected real-WAL test (**1 passed in 0.49s**). Focused frontend: **2 files / 26 tests passed**. Changed paths Ruff: **All checks passed!**; Pyright: **0 errors, 0 warnings, 0 informations**. The first full check run was intentionally interrupted (exit 130) when the final metadata/anchor defects were identified; it is not counted as a passing verification. The final fixed-snapshot `./scripts/lint.sh` exited **0** with these verbatim results:

```text
All checks passed!
208 files left unchanged
0 errors, 0 warnings, 0 informations
2758 passed, 2762 warnings in 400.99s (0:06:40)
 Test Files  56 passed (56)
      Tests  517 passed (517)
   Duration  3.70s (transform 3.86s, setup 5.69s, import 11.65s, tests 14.93s, environment 23.69s)
✅ All checks passed!
Totals: 118 passed, 0 failed (118 items)
```

Frontend format completed with listed files unchanged, ESLint passed with `--max-warnings 0`, and TypeScript `tsc --noEmit` passed. Strict OpenSpec validation and `git diff --check` passed after the final artifact updates. There were no failed or skipped tests reported. Full log: `/tmp/provenance-fresh-final-checks.log`; strict validation: `/tmp/provenance-fresh-openspec.log`.

The 2,762 full-pytest warnings are existing PuLP deprecations in unchanged planner/solver paths. Their distinct messages are retained verbatim rather than suppressed or changed outside this scope:

```text
DeprecationWarning: LpVariable.dicts is deprecated; use prob.add_variable_dicts(...) for PuLP 4.0 compatibility.
DeprecationWarning: Constructing LpVariable(name, ...) directly is deprecated; in PuLP 4.0 use prob.add_variable(name, lowBound, upBound, cat=...). Variables are then attached to the model when created.
DeprecationWarning: PULP_CBC_CMD is deprecated and will be removed in PuLP 4.0. Install CBC with `pip install pulp[cbc]` and use COIN_CMD instead.
DeprecationWarning: Using LpProblem.constraints as a dict mapping is deprecated; in PuLP 4.0 constraints are returned by prob.constraints() as a list. Use get_constraint_by_name(name) or iterate prob.constraints() and compare constraint names.
```

No new dependency, schema migration, installation date/capacity constant, automatic annotation, planner/executor change, local configuration change, runtime observation rewrite, production annotation, staging, commit or push entered this change. The existing 18-line `docs/BACKLOG.md` edit is unrelated, unchanged and must be excluded from a future commit. The user-retained rollback `/tmp/darkstar-dev-before-prod-20261006-202102.db` and existing `data/planner_learning.db` remain intact. Evidence does not support inclusion of old production history; deployment dates do not establish per-row methods/fallbacks/SoC. Metadata undo is guarded and retains unrelated later flags; its whole-database backup is an emergency option, not automatic rollback of later runtime measurements.

### Requirement and scenario mapping

Each row below records implementation/handling plus regression or direct verification evidence. The amended estimate path is a distinct fallback; unavailable-state scenarios apply when no usable estimate exists and original calibrated gates remain strict.

### battery-comparison-calibration — 5 requirements / 24 scenarios

| Requirement | Implementation evidence |
|---|---|
| Calibration uses installation observations without changing operation | backend/battery_comparison.py:65 (GridModel/BatteryModel), :986 (fit_calibration); backend/api/routers/energy.py:500 (_baseline_battery) |
| Calibration validates independent observations and sufficient excitation | backend/battery_comparison.py:550 (numeric eligibility), :894 (contiguous pairs), :921/:943 (bounded excitation fit), :986 (UTC split/gates); :1106 (independent endpoint provenance); backend/api/routers/energy.py selected-period and prior endpoint validation |
| Calibration work is bounded and does not block async requests | backend/api/routers/energy.py:46 (_cached_fit_key), :104 (_calibrated_fit); 900s TTL/16 entries; provenance plus full numerical digest/config identity |
| Compatible cohort selection precedes numerical fitting | backend/battery_comparison.py:612 (trusted_row_provenance), :709 (_cohort_selection); explicit compatibility registry before fitting |
| Immediate configured-loss estimates remain distinct from verified calibration | backend/battery_comparison.py:239 (distinct build_estimated_comparison), :266 (shared arithmetic), :502 (estimate eligibility); backend/measurement_provenance.py:77 (registered earlier encoding); backend/api/routers/energy.py estimate/verified dispatch and assumption diagnostics |

| Scenario | Regression / verification evidence |
|---|---|
| Different sensor boundaries | tests/test_battery_comparison.py::test_ac_like_unity_and_deye_like_synthetic_boundaries_fit_independently |
| Unsupported measurements | tests/test_battery_comparison.py::test_holdout_corruption_rejects_fit_without_training_leakage |
| Full capacity is installation-specific | tests/api/test_battery_comparison_cache.py::test_numeric_correction_with_unchanged_file_identity_invalidates_cache; read-only development API at configured 34.2 kWh; capacity supplied to every SoC conversion |
| Too little history | tests/test_battery_comparison.py::test_unknown_legacy_rows_are_never_certified_by_a_good_fit; tests/api/test_battery_comparison_api.py::test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields; explicit 1000/200 checks in fit_calibration |
| Unobserved conversion direction | tests/test_battery_comparison.py::test_unobserved_grid_direction_is_rejected; test_proportional_simultaneous_battery_flows_are_unidentifiable |
| Withheld errors fail | tests/test_battery_comparison.py::test_holdout_corruption_rejects_fit_without_training_leakage |
| Historical regime differs | tests/api/test_battery_comparison_api.py::test_period_model_failure_uses_estimate_and_preserves_period_failure; test_unsupported_period_inputs_are_reported_even_when_fit_needs_history |
| Negative prices and almost-zero net costs | tests/test_battery_comparison.py::test_calibration_fits_bounded_shared_model_and_negative_price_data; test_overlap_does_not_fail_net_cost_calibration |
| Unknown legacy history | tests/test_battery_comparison.py::test_unknown_legacy_rows_are_never_certified_by_a_good_fit; test_unsupported_latest_schema_does_not_fall_back_to_old_fit |
| Unsupported initial state | tests/api/test_battery_comparison_api.py::test_prior_anchor_uses_only_its_independent_end_identity (18 variants); test_modern_start_endpoint_cannot_borrow_live_end_certainty |
| Configuration changes | tests/api/test_battery_comparison_cache.py::test_fit_cache_runs_off_loop_and_invalidates_for_config_and_end; test_numeric_correction_with_unchanged_file_identity_invalidates_cache; synthetic configured-efficiency-change timing probe |
| Concurrent energy request | tests/api/test_battery_comparison_cache.py::test_fit_cache_runs_off_loop_and_invalidates_for_config_and_end; genuine-fit and read-only-estimate heartbeat timing probes |
| Metadata-only change under WAL | tests/test_comparison_history.py::test_real_wal_annotation_undo_and_numeric_correction_change_cache_identity |
| Recording method changed | tests/test_battery_comparison.py::test_snapshot_fallback_is_excluded_before_the_fit_split |
| Current cohort too small | tests/test_battery_comparison.py::test_newest_algorithm_cohort_does_not_fall_back_to_older_supported_cohort; test_exclusion_counts_include_rows_from_an_older_incompatible_boundary |
| Configuration changes the measurement boundary | tests/backend/test_measurement_provenance.py::test_battery_soc_mapping_changes_measurement_boundary; tests/test_battery_comparison.py::test_cached_soc_and_changed_sensor_boundary_are_not_current_cohort_rows |
| Compatible semantic version | tests/test_battery_comparison.py::test_attested_legacy_and_observed_measured_energy_share_registered_cohort; compatibility registry has no application-version input |
| Fallback during a completed period | tests/api/test_battery_comparison_api.py::test_unsupported_period_inputs_are_reported_even_when_fit_needs_history |
| Usable legacy period before calibration | tests/api/test_battery_comparison_api.py::test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields |
| Verified model becomes available | tests/api/test_battery_comparison_api.py::test_available_api_comparison_reconciles_summaries_and_points; tests/test_battery_comparison.py::test_calibration_fits_bounded_shared_model_and_negative_price_data |
| Unsupported provenance stays rejected | tests/test_battery_comparison.py::test_estimate_builder_itself_rejects_known_unusable_provenance (5 variants); tests/api/test_battery_comparison_api.py::test_modern_start_endpoint_cannot_borrow_live_end_certainty |
| Invalid estimate inputs | tests/test_battery_comparison.py::test_configured_estimate_rejects_invalid_model_configuration; test_configured_estimate_returns_amounts_without_synthetic_calibration_diagnostics; tests/api/test_battery_comparison_api.py::test_naive_selected_timestamp_cannot_become_an_assumed_estimate |
| Estimate does not certify history | tests/api/test_battery_comparison_api.py::test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields; test_earlier_soc_fingerprint_is_assumed_only_for_estimates; fit selection excludes legacy unknown inputs |
| Earlier SoC boundary encoding | tests/api/test_battery_comparison_api.py::test_earlier_soc_fingerprint_is_assumed_only_for_estimates (earlier encoding, changed unrelated sensor, unsupported algorithm); test_prior_anchor_uses_only_its_independent_end_identity |

### energy-recording — 2 requirements / 9 scenarios

| Requirement | Implementation evidence |
|---|---|
| Actual measurement provenance accompanies recorded values | backend/measurement_provenance.py:24/:90 (boundary/schema); backend/recorder.py actual integration/fallback, aggregate, disabled and sanitized paths; backend/learning/backfill.py _build_record/integrate_slots |
| Measurement metadata follows accepted corrections | backend/learning/store.py:117 (BEGIN IMMEDIATE value/metadata merge, per-component/endpoint identities, ownership, exclusions, attestation invalidation) |

| Scenario | Regression / verification evidence |
|---|---|
| One missing history entity | tests/backend/test_recorder_slot_energy.py::test_component_provenance_distinguishes_integrated_and_snapshot_values |
| Zero snapshot contributes to an aggregate | tests/backend/test_recorder_slot_energy.py::test_mixed_device_aggregate_and_base_load_keep_snapshot_provenance |
| Disabled versus unset | tests/backend/test_recorder_slot_energy.py::test_enabled_but_unconfigured_device_is_not_a_disabled_zero; test_disabled_ev_charger_and_heater_entries_are_skipped; tests/ml/test_backfill.py::test_unconfigured_enabled_device_taints_backfill_aggregate_and_derived_load; test_all_disabled_devices_have_disabled_zero_backfill_provenance |
| Cached battery charge level | tests/backend/test_recorder_slot_energy.py::test_cached_soc_is_labelled_as_cached |
| Partial authoritative correction | tests/ml/test_learning_engine.py::test_partial_live_correction_merges_only_accepted_component_provenance; test_partial_current_correction_cannot_promote_retained_unsupported_algorithm; test_partial_soc_correction_preserves_each_endpoint_and_new_exclusion |
| Backfill collision | tests/ml/test_learning_engine.py::test_store_slot_observations_backfill_does_not_overwrite_live |
| Backfill fills an unmeasured component | tests/ml/test_learning_engine.py::test_backfill_fills_missing_component_as_backfill_owned_and_refreshes_own_values |
| Existing exclusion survives | tests/ml/test_learning_engine.py::test_partial_live_correction_merges_only_accepted_component_provenance; test_incoming_exclusion_overrides_old_false_and_price_change_invalidates_attestation |
| An attested value changes | tests/ml/test_learning_engine.py::test_incoming_exclusion_overrides_old_false_and_price_change_invalidates_attestation; tests/test_battery_comparison.py::test_legacy_attestation_is_invalidated_by_manual_numeric_correction |

### comparison-history-provenance — 3 requirements / 11 scenarios

| Requirement | Implementation evidence |
|---|---|
| Historical provenance requires explicit installation evidence | backend/comparison_history.py:149/:172 (evidence/version/identity/interval validation); scripts/annotate_comparison_history.py explicit local-only CLI |
| Annotation is inspectable local metadata maintenance | backend/comparison_history.py:321 (dry run), :420 (exclusive backup, lock/preimage checks, atomic metadata, durable audit); no automatic/remote invocation |
| Annotation is idempotent and safely reversible | backend/comparison_history.py:420/:536 (idempotence and guarded comparison-key undo); read-side numerical attestation binding and canonical cache identity |

| Scenario | Regression / verification evidence |
|---|---|
| Deployment transition proves an exclusion | tests/test_comparison_history.py::test_apply_is_metadata_only_idempotent_and_undo_preserves_unrelated_flags; aggregate-only disposable production-copy exclusion exercise above |
| Verified historical energy | tests/test_comparison_history.py::test_apply_and_undo_inclusion_write_distinct_evidence_backed_attestation; tests/test_battery_comparison.py::test_explicit_legacy_attestation_makes_compatible_measured_history_eligible |
| Insufficient inclusion evidence | tests/test_comparison_history.py::test_inclusion_requires_every_evidence_claim; production deployment evidence did not establish full component/fallback/SoC claims, so no inclusion performed |
| Other installation | tests/test_comparison_history.py::test_manifest_rejects_bad_evidence_wrong_database_overlap_and_stale_measurements; boundary/capacity passed explicitly without installation dates/sizes |
| Dry run | tests/test_comparison_history.py::test_dry_run_reports_identity_and_does_not_mutate_database; test_dry_run_eligibility_respects_numeric_checks |
| Metadata-only application | tests/test_comparison_history.py::test_apply_is_metadata_only_idempotent_and_undo_preserves_unrelated_flags; test_transaction_failure_rolls_back_all_annotation_updates; test_failed_audit_durability_rolls_back_and_removes_partial_output |
| Conflicting source evidence | tests/test_comparison_history.py::test_inclusion_rejects_backfill_or_observed_modern_provenance; test_malformed_metadata_is_never_erased_by_annotation |
| Stale target | tests/test_comparison_history.py::test_manifest_rejects_bad_evidence_wrong_database_overlap_and_stale_measurements; test_annotation_rechecks_ownership_after_backup_under_write_lock |
| Apply twice | tests/test_comparison_history.py::test_apply_is_metadata_only_idempotent_and_undo_preserves_unrelated_flags |
| Safe undo | tests/test_comparison_history.py::test_undo_retains_later_unrelated_flags_and_rejects_outside_owned_keys; test_real_wal_annotation_undo_and_numeric_correction_change_cache_identity |
| New measurements after annotation | tests/test_comparison_history.py::test_undo_refuses_measurement_changes_after_annotation |

### energy-totals-api — 2 requirements / 7 scenarios

| Requirement | Implementation evidence |
|---|---|
| Comparison diagnostics explain trustworthy history coverage | backend/battery_comparison.py _cohort_selection/history_coverage exclusive counts; backend/api/routers/energy.py get_cost_series additive history/status block |
| API identifies estimate and verified comparison bases | backend/api/routers/energy.py get_cost_series distinct estimated/available bases and actual fit diagnostics; shared _build_comparison_amounts and unchanged metered accounting |

| Scenario | Regression / verification evidence |
|---|---|
| No trusted legacy history | tests/api/test_battery_comparison_api.py::test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields; strict history remains 0 and calibration insufficient_data/unverified_history |
| New cohort is collecting samples | tests/test_battery_comparison.py::test_newest_algorithm_cohort_does_not_fall_back_to_older_supported_cohort; read-only development API original calibration state preserved beside estimate |
| Unsupported selected period | tests/api/test_battery_comparison_api.py::test_unsupported_period_inputs_are_reported_even_when_fit_needs_history |
| Numeric failure remains separate | tests/api/test_battery_comparison_api.py::test_unreliable_fit_keeps_real_diagnostics_beside_estimate; test_period_model_failure_uses_estimate_and_preserves_period_failure |
| Estimate with unavailable calibration | tests/api/test_battery_comparison_api.py::test_configured_estimate_is_shown_before_calibration_and_keeps_metered_fields |
| Estimate after numeric rejection | tests/api/test_battery_comparison_api.py::test_unreliable_fit_keeps_real_diagnostics_beside_estimate |
| Automatic verified transition | tests/api/test_battery_comparison_api.py::test_available_api_comparison_reconciles_summaries_and_points; no stored mode switch/attestation is required |

### command-bar — 2 requirements / 6 scenarios

| Requirement | Implementation evidence |
|---|---|
| Grid domain explains trustworthy history availability | frontend/src/components/CommandDomains.tsx unavailable copy and actual-cost view; frontend/src/components/CostSeriesChart.tsx no unavailable/legacy comparison points |
| Grid comparison labels the active basis | frontend/src/components/CommandDomains.tsx finite amount guard, active-basis labels/reasons/model interpretation; CostSeriesChart basis-consistent point labels; frontend/src/pages/DesignSystem.tsx fixtures |

| Scenario | Regression / verification evidence |
|---|---|
| Collecting trustworthy history | frontend/src/components/CommandDomains.test.tsx::explains collecting history and unsupported periods without amounts |
| Unsupported period readings | frontend/src/components/CommandDomains.test.tsx::explains collecting history and unsupported periods without amounts |
| Model accuracy failure | frontend/src/components/CommandDomains.test.tsx::shows a plain-language unavailable state without legacy fallback; shows configured-estimate sign consistently |
| Configured-loss result | frontend/src/components/CommandDomains.test.tsx::labels configured-loss amounts as estimates and explains verification state plainly; frontend/src/components/CostSeriesChart.test.tsx::labels configured-loss comparison lines as estimates; fresh visuals |
| Verified result | frontend/src/components/CommandDomains.test.tsx::shows separate comparable totals and estimated savings, never legacy savings; describes negative saving as additional estimated cost; frontend/src/components/CostSeriesChart.test.tsx::offers a separate comparison view only when validated points are available; fresh visuals |
| Learning reason accompanies estimate | frontend/src/components/CommandDomains.test.tsx::labels configured-loss amounts as estimates and explains verification state plainly; shows configured-estimate sign consistently; fresh visuals |


## Post-archive contract audit — 2026-10-07

The prior 14-requirement / 57-scenario mapping covered the new and modified delta requirements but omitted several pre-existing requirements that still described a validated-only comparison. Those contracts contradicted the approved configured-loss estimate path. This supplemental audit amended the full requirements in the archived delta and corresponding main specs; it changes no application code and does not replace the implementation verification above.

The complete archive now contains seven capabilities and **22 requirements / 91 scenarios**: battery-comparison-calibration 5/24, energy-recording 2/9, comparison-history-provenance 3/11, energy-totals-api 3/16, command-bar 4/11, no-darkstar-baseline 2/7, and grid-financial-wear-display 3/13. The 22 implementation tasks remain complete. Task 5.4 covers the expanded contract audit.

| Newly amended requirement | Scenario coverage and existing implementation evidence |
|---|---|
| Cost series endpoint returns the without-Darkstar baseline | Nine scenarios cover estimate/verified statuses, common arithmetic and endpoints, required SoC, stored-energy lines, no-battery, unchanged metered fields and started-slot coverage. API regressions: tests/api/test_battery_comparison_api.py configured estimate, available comparison, missing initial/end SoC, and started-slot cases; implementation: backend/api/routers/energy.py response dispatch and existing no-darkstar economics. |
| Grid domain displays a consistent estimated battery comparison | Two scenarios cover configured-loss labelling, comparison/actual separation and negative additional cost. Frontend regressions: CommandDomains configured estimate and negative saving cases; CostSeriesChart configured-loss lines. |
| Battery comparison assumptions and unavailable states are understandable | Three scenarios cover unchanged EV/water timing and EV discharge rules, an unreliable calibration alongside a usable estimate, and no-battery hiding. Frontend regressions: controlled-load explanation, configured estimate with calibration reason, and no-battery cases in CommandDomains.test.tsx. |
| Baseline battery accounting uses the configured limits and efficiencies | Three scenarios preserve verified calibrated efficiencies, configured estimate separation and separate power limits. Implementation: strict calibrated simulator and build_estimated_comparison use explicitly separate model bases; API regressions cover configured estimates and verified results. |
| Baseline is unavailable without a battery | Four scenarios cover no battery, no data, strict-calibration failure with eligible estimate, and invalid/unsupported selected-period inputs. API regressions cover configured estimate, failed-fit estimate, unsupported-period rejection, and no-data/no-battery response branches. |
| Grid & Financial card shows a cost chart for the period | Five scenarios retain actual hourly/daily behavior and add estimate or verified intervals. CostSeriesChart accepts both amount-bearing bases; frontend tests cover estimate and verified views; Dashboard/Design System captures cover both bases and unavailable states. |
| Grid & Financial card compares the period with running without Darkstar | Four scenarios cover savings, negative results, stored-energy explanation and no legacy fallback. CommandDomains tests cover positive/negative estimates, basis and legacy fallback; final visual captures cover estimate and verified results. |
| Cost chart draws the without-Darkstar line | Four scenarios cover paired lines, matching totals, responsive heading/legend, and unavailable/no-battery behavior for either comparison basis. CostSeriesChart selects configured-loss and calibrated points; tests cover both bases, malformed values and no legacy lines. |

Strict OpenSpec validation after the contract sync passes 118/118, and git diff --check is clean. Application tests were not rerun because this post-archive audit changes only specifications and verification artifacts; the full application checks recorded above remain the latest code verification. No new fit, provenance, estimate, EV allocation, accounting or configuration behavior was introduced.
