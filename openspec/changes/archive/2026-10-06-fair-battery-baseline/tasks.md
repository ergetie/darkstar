## 1. Shared calibration model

- [x] 1.1 Add pure recorded-boundary grid/battery model types and functions with independently applied inverter/storage factors, bounded [0.80, 1.00] fitting at 0.002 resolution, and immutable fit diagnostics.
- [x] 1.2 Implement 30-day completed-observation selection, quality filtering, contiguous SoC-pair extraction, chronological training/holdout split, sample/excitation requirements, identifiability rejection and the specified validation gates.
- [x] 1.3 Add bounded in-memory calibration caching and perform numerical fitting outside the async event-loop thread; key/invalidate fits using database identity, battery/sensor config, method version and completed-observation boundary.
- [x] 1.4 Add meaningful calibration tests for DC-like and AC-like synthetic recordings, independent holdout failure, negative prices, missing/excluded/backfilled records, unobserved flow directions and cache/config invalidation.

## 2. Fair battery comparison

- [x] 2.1 Add a validated self-use simulation applying the shared model, separate configured power/SoC limits and calibrated storage factors; keep recorded EV/water demand, allow house/water-only discharge, and supply EV energy through grid or PV remaining after non-EV demand.
- [x] 2.2 Implement shared measured starting energy, completed-slot coverage, UTC/DST ordering and explicit rejection of gaps, missing essential prices/energies, missing start/end/bucket SoC and selected-period model validation failure.
- [x] 2.3 Replay recorded Darkstar battery actions through the same net-grid model and compute each side's grid cost, common wear convention, stored-energy adjustment, comparison total and cumulative points using one period reference price.
- [x] 2.4 Add simulation/accounting tests for identical-action zero saving, PV conversion losses, separate power limits, battery bounds, EV/water timing, EV-only full-battery/mixed house-EV/PV-surplus-to-EV cases, no grid-charge/battery-export, overlap fairness, stored-energy signs/negative prices and endpoint reconciliation.

## 3. Additive API integration

- [x] 3.1 Extend `get_cost_series` observation reads and return `battery_comparison` status/reason, through-time, diagnostics, available summaries and separate comparison points; retain legacy baseline compatibility and all actual metered amounts.
- [x] 3.2 Add API regression coverage for unchanged actual/legacy fields, available/unavailable states, incomplete current slots, local-hour/day bucketing across DST, calibration cutoff and final-summary/point/saving reconciliation.

## 4. User-facing comparison

- [x] 4.1 Extend cost-series types and Grid domain to show actual electricity cost plus separately labeled estimated battery savings and comparable economic totals; add readable unavailable states without legacy fallback.
- [x] 4.2 Add distinct Actual/Comparison chart views, paired economic comparison lines, completed-through time and accessible adjustment/assumption explanation; remove claims of full or necessarily conservative savings.
- [x] 4.3 Update chart/Grid domain tests and Design System fixtures for available, unavailable, negative-saving and no-battery states, including final endpoint agreement and clear actual-versus-estimated labels.

## 5. Verification

- [x] 5.1 Validate the implemented calibration and comparison read-only against the available Fronius recording; retain aggregate results and validation failures in change verification, with no production data/secrets committed. Verify Deye-like boundary behavior through synthetic regression fixtures; do not claim validation against an unavailable production snapshot.
- [x] 5.2 Run focused backend/frontend checks, measure calibration cache-hit/miss response times and confirm numerical work does not block the event loop, then run `./scripts/lint.sh`.
- [x] 5.3 Visually verify Dashboard and Design System on desktop/mobile and light/dark themes, with available/unavailable/no-battery states; record evidence and resolve any misleading labels or mismatched comparison totals before marking implementation complete.
