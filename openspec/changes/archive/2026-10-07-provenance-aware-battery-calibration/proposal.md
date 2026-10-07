## Why

Battery comparison calibration currently combines observations labelled only `source: recorder`, even when the recorder changed from instantaneous battery power estimates to measured slot energy. Mixing those measurement regimes can teach false losses and reject an otherwise explainable installation; unknown history and snapshot fallbacks must be distinguished from trustworthy measured energy.

## What Changes

- Record versioned measurement provenance for every energy component and live/cached SoC, including snapshot fallbacks and disabled subsystems, in existing observation quality metadata.
- Select a compatible calibration cohort before fitting. Exclude known snapshot estimates, backfills and unverified legacy history, preserve chronological holdout validation, and require sufficient trustworthy data.
- Provide an immediate explicitly labelled configured-loss estimate from complete usable selected-period data, then replace its basis with a verified fitted model when strict calibration gates pass. Preserve the original calibration state and reason alongside estimates.
- Provide a local, dry-run-first history annotation tool for installation-specific evidence. It can mark verified legacy measurement regimes and exclusions without rewriting energy, prices or SoC; ambiguous intervals remain unknown.
- Expose the selected cohort and exclusion counts through additive comparison diagnostics, with plain unavailable reasons distinguishing insufficient trustworthy history from failed accuracy checks.
- Keep the existing verified model, efficiency bounds, sample minimums, accuracy gates, full-capacity interpretation, recorded EV/water timing and EV discharge restriction. Estimates use the explicit planner AC-bus convention and configured battery efficiencies, and are never described as verified.

## Capabilities

### New Capabilities

- `comparison-history-provenance`: Audited, reversible local annotation of historical measurement regimes using explicit installation evidence.

### Modified Capabilities

- `energy-recording`: Persist actual per-component recording methods and SoC source, and preserve their relationship to stored measurements during corrections/backfills.
- `battery-comparison-calibration`: Fit only a compatible trusted cohort, validate provenance and preserve existing accuracy policy and bounded caching.
- `energy-totals-api`: Add cohort/exclusion diagnostics and provenance-specific unavailable reasons without changing actual accounting or legacy API fields.
- `command-bar`: Explain when trustworthy history is still being collected or a selected period contains unsupported measurements, label estimate versus verified results, and preserve valid estimates alongside calibration reasons.
- `no-darkstar-baseline`: Permit the separate configured-loss estimate when strict calibration is unavailable, while retaining strict verified gates and rejecting invalid selected periods.
- `grid-financial-wear-display`: Display either eligible comparison basis in the comparison card/chart and retain actual metered accounting.

## Impact

Recorder, shared slot-energy helpers, observation upserts, backfill provenance, comparison fitting/cache/API, Grid domain estimate/verified/unavailable copy, the Grid & Financial comparison card/chart, tests and a local history annotation script. Use `quality_flags`; no database schema migration or new dependency. No automatic production writes, configuration changes, universal dates/capacities, numerical-history repair or new settings screen. The capacity tooltip correction is already committed as `a0fa4e10`; the comparison foundation is `377c71ee`.
