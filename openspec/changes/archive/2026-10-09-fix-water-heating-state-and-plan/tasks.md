## 1. Configuration and shared boundaries

- [x] 1.1 Add one timezone-aware quota-window helper used by solver grouping and progress reads; test midnight, 6-hour deferral, fractional boundaries and DST without double allocation.
- [x] 1.2 Validate finite `water_heating.defer_up_to_hours` within 0–23 at config load and settings save; add actionable errors and atomic-save tests, including existing value 30 and accepted endpoints.
- [x] 1.3 Add finite non-negative per-heater `idle_power_threshold_kw` with default 0 in configuration/defaults and frontend types; preserve valid older configurations.

## 2. Active heating measurement and persistence

- [x] 2.1 Implement shared unit-aware active-power normalization; test 60 W idle, equality at the cutoff, W/kW equivalence and a mixed idle/heating slot with cutoff 0.10 kW.
- [x] 2.2 Apply normalization to water history integration, snapshot fallback, backfill, live disaggregation and activity detection; verify base load retains idle energy and controllable energy is subtracted exactly once with grid readings unchanged.
- [x] 2.3 Persist versioned per-heater active-energy attribution/source/semantics in existing observation metadata; test store round-trip, measured zeros, restart and accepted corrections without schema changes or loss of unrelated flags.
- [x] 2.4 Add store reads for per-device interval energy and coverage; recover legacy attribution from supported ownership/history where possible and test ambiguous multi-device and changed-configuration cases without fabricated allocation.

## 3. Production progress and replanning

- [x] 3.1 Pass the first solver slot's start as the progress cutoff through production state acquisition; combine stored data and non-overlapping recent history before that cutoff, including recorder lag and unknown coverage.
- [x] 3.2 Wire attributable per-heater progress and coverage through HA initial state, forecasts, pipeline and adapter; remove the effective hardcoded-zero path while preserving control for heaters without power sensors.
- [x] 3.3 Credit progress only against the matching first quota bucket; add rollover, within-slot replan, horizon-advancement, restart, per-device isolation and unavailable-history tests.
- [x] 3.4 Add a store-to-initial-state-to-pipeline/adapter/solver regression for switch and temperature control; demonstrate the baseline's zero-progress failure and correct outstanding quota after the fix.
- [x] 3.5 Verify completed quota creates no new quota demand, partial/missed heating remains retryable, genuine mid-block locks remain intact and below-cutoff idle cannot create a lock; keep executor shadow/idempotence/control tests passing.

## 4. Per-heater comfort and settings

- [x] 4.1 Use each heater's maximum gap in the existing soft-gap recurrence; test independent 28-hour/8-hour deadbands and retain top-ups-off, vacation, horizon-start and comfort-weight behavior.
- [x] 4.2 Update settings bounds/help for deferral 0–23, maximum gaps above 24 and per-heater idle cutoff with explicit kW units; explain cutoff 0 compatibility and the 0.10 kW example. Follow the existing design system.
- [x] 4.3 Add settings validation/rendering tests covering valid long gaps, invalid/non-finite inputs, persisted cutoff and unchanged comfort ceilings.

## 5. Plan and actual presentation

- [x] 5.1 Gate completed-slot overlays by slot end rather than slot start; keep current/future planned aggregate/per-device water and grid values intact and retain plans separately for completed-slot comparison.
- [x] 5.2 Require supported water-component measurement provenance for actual overlays; distinguish unknown, integrated zero and snapshot estimates, including explicit legacy evidence and aggregate-only attribution.
- [x] 5.3 Update API types/chart/details as needed to consume separate plans and actual availability/source without interpreting null as zero or showing below-cutoff idle as actual heating.
- [x] 5.4 Add API and chart regressions for the 18:56/current-18:45-slot case, price-only placeholders, 19:00 completion, genuine zero, unknown legacy measurements, snapshot estimates and per-device consistency.

## 6. Before/after evidence and verification

- [x] 6.1 Build deterministic small replay fixtures for both control modes: zero/partial/completed progress, missed delivery, repeated replans, comfort enabled/disabled and active/idle block state. Assert energy and cause-specific outcomes rather than tie-dependent slot positions.
- [x] 6.2 Run baseline versus fixed comparisons, plus an archive-derived Torleif replay with clearly documented missing inputs and explicit valid deferral; record results in this change directory without committing diagnostics, databases, secrets or runtime config.
- [x] 6.3 Run focused recorder/store/progress/solver/overlay/frontend tests and the required `./scripts/lint.sh`; resolve failures and validate the OpenSpec change. Keep solver timing/tuning/status work deferred.
