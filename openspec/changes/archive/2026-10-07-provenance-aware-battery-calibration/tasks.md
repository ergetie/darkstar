## 1. Record and preserve actual measurement provenance

- [x] 1.1 Define the versioned provenance/legacy-attestation structures, supported method/semantics registry, canonical boundary fingerprint and validation helpers using existing dependencies and `quality_flags`.
- [x] 1.2 Capture actual per-component paths and writer ownership in the live recorder, including integrated versus snapshot zero values, disabled/unconfigured inputs, derived base load, aggregate EV/water sources and live/cached SoC; add targeted recorder regressions.
- [x] 1.3 Attach truthful method/ownership metadata to accepted backfill components while retaining backfill exclusion; test mixed-ownership rows and disabled subsystem behavior.
- [x] 1.4 Make observation upserts merge provenance with accepted values in one transaction, preserve exclusions/unrelated flags, prevent backfill overwrites of authoritative battery/SoC, and invalidate changed legacy attestations; test partial/missing/zero measurements and collisions.

## 2. Select and validate compatible calibration history

- [x] 2.1 Implement provenance-first selection of the latest supported current-boundary cohort within the existing completed 30-day window; reject known snapshots/mixed sources, cached SoC, per-component backfill ownership and unknown/unsupported metadata.
- [x] 2.2 Support only explicitly registered measured-energy compatibility and validated legacy attestation; preserve the 1,000/200 minimums, directional excitation, efficiency bounds, chronological 80/20 split and all accuracy gates without searching cutoffs for success.
- [x] 2.3 Require same-cohort contiguous battery pairs, trustworthy selected-period coverage and independently trusted initial SoC anchors; return insufficient versus incomplete versus unreliable states accurately and retain the EV-only discharge prohibition.
- [x] 2.4 Add synthetic regressions for contaminated old snapshot history, unverified legacy rows, attested compatible history, insufficient newest cohort, sensor/polarity/algorithm changes, cached SoC, fallback gaps, unchanged semantics across app releases, and future/DST boundaries.
- [x] 2.5 Bump method version and add cohort/provenance-window digest to bounded cache identity; test metadata-only WAL annotation/undo and capacity/config changes with unchanged latest timestamps, and preserve worker-thread fitting.
- [x] 2.6 Add a separate configured-loss estimate path with strict selected-period input checks; preserve every calibration gate and retain the real fit status/reason/diagnostics without synthesizing fit results.

## 3. Provide safe local historical annotation

- [x] 3.1 Implement the explicit local JSON-manifest parser and dry-run report with database/affected-measurement identity, timezone-aware half-open intervals, boundary/semantics declarations, evidence references/digests and dispositions; reject unknown versions, overlaps, stale identities and unsupported claims.
- [x] 3.2 Implement explicit apply with consistent SQLite backup, guarded preimages and atomic comparison-metadata-only changes; preserve values/ownership/exclusions, reject known snapshot/backfill promotion or modern-provenance replacement, and make repeated application idempotent.
- [x] 3.3 Implement audit/undo output and guarded metadata-only rollback that retains later unrelated flags and refuses changed measurements/postimages; ensure the script has no automatic startup or remote-write path.
- [x] 3.4 Add disposable-database tests for dry-run immutability, apply/undo, evidence failure, conflict/overlap/wrong target, transaction failure, repeated application and concurrent/stale measurement changes; verify all numeric observations are identical before/after annotations.

## 4. Explain history availability through the API and Grid domain

- [x] 4.1 Add bounded history diagnostics, exclusive exclusion counts and stable provenance-specific reasons to cost-series responses, including no-fit results; preserve amount-bearing estimate and verified states, with amounts absent only when the selected period is ineligible, and keep metered/legacy fields unchanged.
- [x] 4.2 Update frontend types, basis labels, calibration-reason copy and representative Design System fixtures to distinguish estimates, verified results, collecting trustworthy history, unsupported selected periods and numeric accuracy failure; add focused rendering/no-legacy-fallback coverage.
- [x] 4.3 Visually verify estimate, verified and unavailable states on Dashboard and Design System at desktop/mobile widths and in light/dark themes, with actual costs visible and no erroneous saving amounts.
- [x] 4.4 Identify configured-loss estimates and verified comparisons consistently in API, cards, chart and Design System fixtures; explain estimate assumptions and original calibration state.

## 5. Validate recovery evidence and complete verification

- [x] 5.1 On a fresh read-only-source local production copy, verify capacity is installation-configured and prepare an inspectable evidence-based dry run; identify which historical intervals can genuinely be attested and explicitly report unrecoverable/ambiguous history. Do not apply to production or change configuration.
- [x] 5.2 Test any reviewed annotation on the disposable local copy and compare cohort counts, factors, holdout/period diagnostics and unavailable reasons; demonstrate undo and retain an aggregate audit without observation rows or credentials. A remaining rejection is acceptable evidence, not permission to weaken checks or invent provenance.
- [x] 5.3 Check bounded cache miss/hit behavior and event-loop responsiveness with provenance processing; run final `./scripts/lint.sh`, full pytest and frontend tests, strict OpenSpec validation, and record final results and material recovery limitations.
- [x] 5.4 Re-verify all original and amended requirements/scenarios, including the pre-existing API, command-bar, baseline and Grid & Financial contracts amended for estimate acceptance/rejection and verified transition; confirm no installation-specific dates/capacities, automatic history rewrites, new dependencies/schema, planner/executor/config changes or unrelated backlog edits entered the change.
