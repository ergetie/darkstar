## Context

The investigation is recorded in `ops/investigations/torleif-water-2026-10/findings.md` (local, ignored evidence). Production initial-state acquisition returns zero heating progress. The recorder computes per-heater energy but the observation store drops that mapping. Solver unit tests inject progress directly, so they bypass the failing production path. Both switch and temperature control use the same binary electrical-load planner.

Separately, the solver uses a global default gap instead of each heater's configured gap. Schedule history treats the unfinished current slot as historical and can substitute a price-only row's default zero for planned heating. Torleif's roughly 60–68 W idle draw exceeds the chart's activity threshold. These are confirmed code paths; the original inputs for an exact full incident replay were not captured. Repeated mid-block locks are observed, but are not independently proven defective.

## Goals / Non-Goals

**Goals:** Correct measured progress and attribution; consistent idle filtering and load accounting; truthful per-heater comfort settings; distinct plans and actuals; regression coverage through production wiring for both control modes.

**Non-Goals:** Solver timeout investigation/tuning/status changes; changing daily minimums into caps; removing legitimate retries or anti-chatter locks; thermal tank modelling; database schema changes; new dependencies; rewriting unrelated working-tree changes.

## Decisions

### 1. Store attributable energy in existing observation metadata

Persist a versioned per-heater active-energy mapping in existing `quality_flags`, alongside component provenance and the measurement semantics/cutoff used. Reuse the store's accepted-correction/ownership rules so water values, attribution and provenance change together. A known zero for an enabled, measured heater is an explicit entry; absent attribution means unknown. Read this metadata through a store accessor shared by the initial-state/pipeline path. Do not add a table or column: metadata already supports device-specific observations and avoids a schema change.

New live and backfill writes must preserve attribution. For legacy rows, trust an existing valid per-device mapping when available. Aggregate-only energy can be assigned to one heater only when available configuration/measurement provenance establishes sole ownership for that window; the current enabled-device count alone is insufficient after configuration changes. Otherwise use available power history to reconstruct attribution, and retain unknown coverage if reconstruction is unavailable. Do not split aggregates across devices or relabel unfiltered legacy energy as filtered. No blanket rewrite of historical rows.

### 2. Share quota-window semantics between progress and constraints

Extract one local-time quota-bucket definition for both recorded progress and solver slot grouping. With deferral `h`, bucket D spans `[D at h:00, D+1 at h:00)` in the configured timezone, including real DST durations. `h=0` is the calendar day. Only the first, already-started bucket receives pre-horizon progress; later buckets retain their own full requirement. Allocate energy at boundaries without double-counting, including quarter-hour slots when fractional hours are supported.

The user selected the supported range 0–23 inclusive. Preserve numeric-hour precision already supported, enforce finite values within that range at configuration load and settings save, and align UI bounds/help. Invalid existing values such as 30 produce an actionable configuration error rather than a silent clamp or shifted interpretation. A failed settings update leaves the last valid configuration intact.

Build progress from persisted completed observations plus non-overlapping recent power history up to the first solver slot's start, so recording lag does not reset progress. This explicit horizon cutoff prevents counting an elapsed part of the current slot both as delivered progress and as part of the solver's full-slot energy. Within-slot replans retain the same cutoff; measurements inside that slot become creditable when the horizon advances. Pass the cutoff explicitly through initial-state/forecast preparation rather than letting different layers independently use wall-clock now. Carry each heater's value and coverage/source status through forecasts, pipeline and adapter. Where history/attribution is unavailable, preserve known contributions, expose/log incomplete coverage, and conservatively credit no invented energy for the missing interval. This retains controllability for heaters without power sensors; an ON command or high temperature target is not evidence of delivered electrical energy. Do not treat a sensor outage as a measured zero.

Alternative rejected: use the HA cumulative daily energy sensor. It neither matches the current power-history architecture nor reliably supplies per-heater attribution or shifted quota windows.

### 3. Normalize power once, before integrating active energy

Add per-heater `idle_power_threshold_kw`, finite and non-negative, default 0 for compatibility. Expose it with units/help in water settings; 0.10 kW is the recommended value for Torleif's roughly 0.06 kW idle draw, not a forced global default. A normalized sample below the configured cutoff becomes zero; a sample equal to the cutoff remains unchanged. Apply the same rule to history, snapshot fallback, recent progress, backfill, live disaggregation and active-state/mid-block detection. Filter samples before integration, not slot-average energy: a mixed heating/idle slot must retain its actual heating portion.

Use filtered active energy for `water_kwh` and per-device energy. Subtract only that energy from household consumption, leaving idle consumption in base load. Metered grid energy remains unchanged. Preserve units (W versus kW), provenance, fallback behavior and accepted corrections. No second raw-energy column is needed for balancing. Historical values without these semantics remain identifiable as legacy rather than being silently filtered by average.

### 4. Use per-device gaps and retain justified continuity

The existing O(T) soft-gap recurrence uses `heater.max_hours_between_heating` as its deadband; shared settings control enablement and comfort weight only. Keep the existing horizon-start counter behavior. `enable_top_ups: false` and vacation disable gap terms; comfort level changes the weight, not the gap. Allow settings above 24 hours (including Torleif's 28) consistently in UI/backend.

Credit measured progress before constructing the first quota constraint. Keep existing per-device remaining-block locks and their observability, with activity detection using filtered power. Meeting a quota removes only its outstanding minimum: it does not cancel a genuine current block or prohibit comfort top-ups. Missed/undelivered heating can still be retried. Replays must distinguish quota-driven energy, forced continuity and comfort terms; do not infer a lock bug from extended heating alone.

### 5. Gate actual overlays by slot completion and component evidence

Keep the schedule plan available independently of actual values. A slot is complete only when its end is at or before now. Current/future slots retain planned water and per-device entries; available current telemetry is separate and never replaces the plan. For completed slots, require water-component measurement provenance before presenting an actual (integrated or explicitly labelled snapshot estimate). Price-only/default rows and unknown fields are unavailable, not measured zero. Measured zero is valid and visible as zero.

Use the existing provenance parser/legacy attestation support where it establishes water measurements. Legacy rows without support retain prices and plans but expose actual water as unavailable; recover from history only through the normal recording/correction path. Do not certify a legacy row merely because it has a water column or a timestamp. Keep aggregate/per-device actuals consistent; where only the aggregate is supported, leave the per-device actual unavailable. Make the chart/details consume plan and actual consistently without inventing idle heating or erasing the plan. Preserve existing API consumers with additive actual availability/source fields where necessary.

Alternative rejected: adjust the frontend activity threshold alone. That hides the symptom while leaving progress and load isolation incorrect.

### 6. Test the source-to-solver path, then replay controlled cases

Add a regression that writes recorder-shaped data through the real observation store, reads production initial state and passes it through forecasts/pipeline/adapter to the solver. Parameterize switch and temperature control. Include quota met/partial, unavailable readings, per-device isolation, restart, within-slot replan, recording lag, quota rollover and DST. Preserve existing executor command/shadow/idempotence tests.

Use deterministic small solver fixtures with fixed inputs, isolated quota-only cases and separate comfort/lock cases. Demonstrate the pre-fix failure without committing broken production code; compare baseline and fixed code using a fixture or isolated checkout. Archive-derived replays must identify missing inputs and keep the invalid original deferral value separate from a normalized, valid replay input. Do not call a synthetic replay an exact incident reproduction. Assert outcomes and energy accounting, not exact tie-dependent slot selections. Record comparison results in change-local artifacts, not `docs/`.

## Risks / Trade-offs

- Missing/legacy attribution → recover from history when possible, preserve coverage uncertainty and never fabricate device totals.
- Snapshot estimates and incomplete history can overstate/understate progress → label sources, avoid overlap, and test fallback/partial coverage explicitly.
- Existing deferral 30 is invalid → actionable validation and deliberate operator correction; no automatic runtime-config edits.
- Cutoff 0 preserves idle counting until configured → expose clear units/recommended setting; test 0.10 kW with Torleif-like readings.
- Soft quotas, comfort and locking can still heat at expensive times → isolate each reason in tests and avoid promising heating caps.
- Original incident lacks full solver inputs → bound conclusions to deterministic regressions and documented archive-derived evidence.

## Migration Plan

Implement with existing storage and additive metadata/API fields. Defaults retain cutoff 0; operators explicitly configure an appropriate threshold and correct out-of-range deferral before restart. Do not edit the user's `config.yaml` or diagnostics. Read old observations conservatively and let subsequent recording/backfill writes acquire the new semantics. Verify existing configurations within range and existing schedule consumers remain compatible. Rollback code without a schema rollback; older code can ignore added metadata, but reintroduces the known progress/overlay defects.

## Open Questions

No blocking product decisions remain. Solver timing is intentionally deferred until this change has been implemented and verified.
