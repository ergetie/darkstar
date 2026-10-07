## Context

The comparison introduced by `377c71ee` fits a common recorded-boundary model over 30 days. `quality_flags` currently distinguishes recorder/backfill ownership, but not the recording method. Battery energy was historically a power snapshot multiplied by 15 minutes, then cumulative-meter energy, and is now integrated power history. A recorder row can still contain a mixture of integrated energy and snapshot fallbacks. SoC can be a live reading or a cached fallback. None of these distinctions is persisted today.

The investigation established two independent causes of rejection: a capacity value entered as usable energy despite code expecting full capacity, and incompatible recording history. The capacity wording is fixed in `a0fa4e10`; this change does not change settings. Restricting one installation's history using verified deployment evidence passed diagnostics after correcting capacity, but that is not a universal date or proof that every historical fallback is identifiable.

## Goals / Non-Goals

**Goals:**
- Persist truthful provenance alongside values and use it before choosing calibration samples.
- Retain suitable historical measured energy when installation evidence establishes compatibility.
- Preserve the existing accuracy gates and show a clear collecting-history state when safe calibration is unavailable.
- Make historical annotation explicit, local, inspectable, reversible and independent of fitted results.

**Non-Goals:**
- Changing capacity, limits, recorder energy values, loss-model equations, thresholds, planner or executor behavior.
- Reintroducing cumulative meters into the recorder, repairing financial history, fitting around a failed gate, automatic deployment-history discovery, or adding a recovery UI.
- New dependencies, persistent schema changes, automatic production writes, universal migration dates or inferred physical battery sizes.

## Decisions

### 1. Versioned provenance in existing `quality_flags`

Add a `recording` object with `schema_version: 1`, a stable energy-semantics identifier, a measurement-boundary fingerprint, recorder algorithm identifier, per-component source methods and accepted writer ownership (`recorder`/`backfill`), and SoC source/ownership. Actual method values distinguish `power_history`, `snapshot`, `disabled_zero`, `unconfigured_zero`, `derived_history` and `mixed`; verified historical measured energy uses a separate `legacy_attestation` object and never pretends to be a newly observed history reading.

The boundary fingerprint is a canonical hash of measurement entity mappings, grid meter topology, inversions, load isolation and enabled device identities. Physical input-sensor mapping changes establish a new boundary. Operational reserve limits, prices and battery capacity are not recording-method identities; capacity remains a model input and cache input. Method semantic-version changes are incompatible unless the code explicitly documents compatibility. Missing/malformed/unknown-version metadata is unknown, never implicitly current.

Capture each component's actual path at the place where integration/fallback is selected. Derived house load inherits total-load and EV/water input provenance; an aggregate containing any snapshot is mixed even when that snapshot happens to be zero. Legitimately disabled subsystems have trusted zero provenance; missing configured inputs cannot masquerade as disabled. Cached SoC is unsuitable for calibration or selected-period state anchors. Backfill records their actual method but remain ineligible under the existing source policy.

Alternative: app version alone. Rejected because one version still has per-component fallbacks and different sensor setups. No schema column is required.

### 2. Store values and their provenance together

Merge metadata according to the exact measurements that the UPSERT accepts, in the same transaction. Retained values retain their provenance. A live correction replaces provenance for overwritten measurements; a correction without provenance makes those measurements unknown rather than borrowing previous certainty. Backfill cannot relabel or overwrite retained authoritative energy or SoC. Preserve unrelated flags, especially `exclude: true`, during ordinary writes; authoritative ownership is not permission to erase exclusions. Historical attestation is invalidated for any annotated measurement that a later writer changes.

Existing battery/SoC upsert paths need particular attention: they currently use unconditional `coalesce` and can violate the intended relationship between recorder ownership and metadata. Correct those paths as needed to meet the existing Correctable Energy Storage contract, without changing unrelated storage behavior.

### 3. Select a trustworthy compatible cohort before fitting

Within the existing completed 30-day window, resolve numeric validity, provenance, ownership and exclusion flags first. Select the latest trusted boundary/energy-semantics cohort at or before the comparison cutoff that is compatible with the installation's current measurement configuration. Known snapshot/mixed essential components, cached SoC, unconfigured essential inputs, backfills and unknown history are excluded. This includes rows whose overall source is recorder but whose accepted essential components or SoC were filled by backfill. A snapshot outage does not create a new compatible method or permit fallback to an older incompatible cohort.

Only supported full-slot measured-energy semantics can share a cohort. Historical cumulative-meter energy can join a supported measured-energy cohort only through explicit evidence-backed legacy attestation of equivalent measurement boundaries and slot-energy meaning. Deployment date, numerical appearance or a passing calibration alone cannot establish this. A changed algorithm with materially different semantics requires a separate cohort; changing an app version without changing measurement semantics does not.

After cohort selection, apply the existing eligibility checks, contiguous same-cohort battery pairing, sample minimums, directional excitation and UTC chronological 80/20 split. Do not search windows or cohorts for the first passing answer. A newest compatible cohort that is too small returns `insufficient_data`, not an older fitted model. Selected-period rows must belong to the fitted cohort and meet provenance requirements; the period cannot silently omit unsupported slots. A prior-slot SoC anchor must be contiguous, same-boundary and independently trusted. Validate its used end endpoint independently of unused prior-slot start/energy values: snapshot energy or a cached/backfilled start does not certify or invalidate a separately live recorder-owned end. Explicit exclusions, global backfill, unsupported endpoint/header identity and invalid end values remain rejected. Battery training pairs still require fully eligible same-cohort energy rows.

Maintain all current thresholds, bounds, signed-net validation and gross billing-volume denominator. The minimum 1,000 grid samples means roughly 10.5 days of uninterrupted eligible 15-minute data when no trustworthy legacy history can be recovered. Additional exclusions or insufficient battery excitation can extend this. Unknown historical provenance is an expected collecting-history state, not evidence of hardware failure.

### 4. Explicit local legacy annotation tool

Implement `scripts/annotate_comparison_history.py` using existing Python/SQLite/JSON facilities. It takes an explicit local database path and a JSON manifest with version, database/affected-row identity, timezone-aware half-open intervals, dispositions (`exclude_from_comparison` or `verified_measured_energy`), compatible boundary/semantics, supported historical methods, and evidence references/digests. Inclusion evidence must establish configured measurement paths, full-slot energy semantics, boundary compatibility and relevant fallback treatment; deployment evidence alone can establish a transition/exclusion but cannot certify every reading as measured energy. Unresolvable intervals stay unknown. Real observations and credentials do not belong in committed artifacts.

Dry run is the default and reports affected counts, current classifications, conflicts, and expected cohort eligibility without changing the database. Inclusion is never generated by testing dates until the model passes. Evidence is operator-supplied and reviewable; the tool validates its schema, local references/digests and identity but does not claim that a file digest proves its contents are true. Numerical diagnostic validation is a separate check after provenance classification.

`--apply` requires an explicit reviewed manifest and exclusive/local maintenance use. Create a SQLite backup first, compare preimages, and atomically update only comparison-owned metadata in `quality_flags`. Preserve all energy, price, SoC, source, exclusion and unrelated metadata fields. Do not relabel known snapshots as measured energy, promote backfills, overwrite observed modern provenance, or infer sources from decimal precision. Reject ambiguous/overlapping intervals, wrong database identities and stale preimages. Applying an identical manifest is idempotent. Emit a small audit/undo file containing metadata preimages and evidence digest; rollback restores only comparison-owned keys when matching postimages remain unchanged. A whole-database backup is a recovery option, not the default rollback operation.

The script has no SSH/HA write capability and never runs automatically at startup. Running it on production later needs explicit authorization; this plan authorizes creating/testing the tool only. For this installation, build any proposed manifest from verified deployment/sensor/history evidence during implementation; report any interval whose inclusion cannot be proved. Do not promise a verified result from the earlier diagnostic. A configured-loss estimate is available only when the selected period independently meets the explicit estimate eligibility rules.

Alternative: universal start date, automatic retroactive labelling or blindly deleting old observations. Rejected because deployments, sensor boundaries and fallback history differ between installations.

### 5. Immediate configured-loss estimate and verified upgrade

When the strict calibrated model is unavailable or fails numeric gates, calculate a separate estimate only for a complete selected period with finite nonnegative energy, finite prices, valid installation battery limits and a trustworthy or explicitly assumed legacy state anchor. Use the planner AC-bus convention (`GridModel(1, 1)`) and the configured charge/discharge efficiencies. Do not infer an inverter loss, capacity, date or missing energy/price/SoC. Known exclusions, backfills, snapshot/mixed essential measurements, cached SoC and unsupported modern provenance remain ineligible. Legacy recorder rows without recording metadata may be used as assumed estimate inputs; this does not attest or promote them for calibration. The explicitly registered initial schema-v1 boundary encoding that omitted `battery_soc` may also be assumed for estimates only when its fingerprint exactly matches the current canonical configuration with that one field removed, all other component identities/methods are supported, and end SoC is live. It cannot prove the historical SoC sensor mapping, so it remains rejected by strict calibration. Arbitrary boundary changes or unsupported methods are never compatible. Estimates expose bounded counts of assumed legacy recording and SoC-mapping slots; no metadata is rewritten.

Recorded Darkstar actions and self-use counterfactual use the same grid and battery models. Existing metered cashflow remains separate. Estimate responses carry `basis: configured_losses`, an explicit estimate label, and the actual calibration status/reason; no fit or validation diagnostics are fabricated. Genuine diagnostics from an attempted fit may accompany the estimate with their actual passing/failing status. Once strict calibration passes, return the verified calculation automatically with `basis: calibrated` and real diagnostics. A verified result is a model that passed defined checks, not proof of exact counterfactual cash. Cache identity includes configured efficiencies and the comparison method version.

### 6. Cache, diagnostics and UI

Bump the comparison method version. Add cohort identity and a canonical digest of selected-window comparison provenance to fit-cache identity, so metadata-only annotation/rollback invalidates a fit even when the latest slot and main SQLite file mtime remain unchanged under WAL. Keep bounded caching and worker-thread fitting.

Expose a separate additive `history` diagnostic block with cohort identifier/start, considered/eligible counts and exclusive exclusion counts by reason. It exists even when no fit can be attempted. Do not expose entity names, evidence paths or observation values. Retain the strict calibration statuses and reasons, including `insufficient_compatible_history`, `unverified_history`, `unsupported_period_measurements`, and `unreliable_model`. The comparison response may separately have `status: estimated` and `basis: configured_losses` when the complete selected period is estimate-eligible; preserve the underlying calibration status/reason and include only genuine fit diagnostics.

Grid and Grid & Financial copy label configured-loss estimates and calibrated results distinctly, and distinguish collecting reliable history from accuracy failure and unsupported selected periods. A valid configured-loss estimate remains visible with its calibration reason; when selected-period inputs fail estimate eligibility, no comparison amounts or lines appear. Actual cost remains visible and the legacy baseline is never substituted. Update API types and representative Design System fixtures only as necessary for these states.

## Risks / Trade-offs

- [Unlabelled history cannot always be recovered] → Explain the collecting-history state and keep the 1,000/200 minimums; verified local annotation is optional.
- [Operator attestation can be mistaken] → Require reviewable evidence and identity checks, keep attestation visibly distinct from observed provenance, preserve all numeric validation gates, and support rollback.
- [A provenance merge can falsely certify retained values] → Test partial corrections, zero measurements, backfill collisions, SoC ownership, exclusion preservation and attestation invalidation.
- [Filtering creates gaps or biased battery pairs] → Require contiguous same-cohort pairs and full selected-period coverage; select provenance before inspecting fit outcomes.
- [Configuration or metadata changes leave cached results] → Include boundary, model configuration and canonical provenance digest; test WAL metadata-only writes and undo.
- [Legacy measured methods are not always physically equivalent] → Require explicit supported semantics and evidence-backed boundary compatibility; reject unverifiable imports instead of broad automatic compatibility.

## Migration Plan

1. Ship provenance recording and read-side enforcement together, with estimate, verified and unavailable-state copy and regression coverage. A calibration failure alone does not suppress an otherwise eligible configured-loss estimate. No schema migration or automatic history rewrite.
2. Verify fresh recorder rows and backfill/partial-write behavior on a disposable local database. Run all required checks and UI state verification.
3. On a fresh read-only-source local production copy, prepare a dry-run evidence manifest. Validate full configured capacity without altering it. Compare the unannotated and reviewed-annotation diagnostics, including selected-period checks; retain an audit and undo path.
4. If legacy inclusion evidence is insufficient, report that outcome and allow new eligible history to accumulate. Neither failing nor passing estimates justify changing provenance claims.
5. Later production annotation is a separately authorized operational action after reviewing the concrete dry run. Roll back metadata with postimage guards, or roll back application code; keep the new metadata compatible with old readers.

## Open Questions

No product-policy decision is required to implement this plan. The amount of recoverable legacy history is an evidence question to resolve on the local copy; implementation must report insufficient evidence rather than invent a global cutoff or weaken validation.
