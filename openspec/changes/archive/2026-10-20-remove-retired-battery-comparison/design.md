# Design

## Context

See proposal.md for motivation. `backend/battery_comparison.py` mixes two groups: recorded-observation provenance helpers that are live, and the retired self-use replay / calibration code that is dead. Live import paths: `backend/learning/store.py` (observation range used by `api/routers/schedule.py`) and `backend/comparison_history.py` (used by `scripts/annotate_comparison_history.py`).

## Goals / Non-Goals

**Goals:**
- Remove every symbol with no production consumer; rename the slimmed module to match its remaining purpose and update its live consumers.
- Keep test coverage of the retained provenance and eligibility rules.

**Non-Goals:**
- Changing `grid_only_comparison.py`, the daily battery benchmark, or any UI/API output.
- Touching stored observation data or comparison-history annotations.

## Decisions

- **Slim `backend/battery_comparison.py`.** Retained: `RecordedObservation`, `_finite_nonnegative`, `_finite_price`, `_valid_soc`, `_flags`, `calibration_eligible`, `_REQUIRED_COMPONENTS`, `_LEGACY_METHODS`, `_ENERGY_COMPATIBILITY_REGISTRY`, `_OBSERVED_ALGORITHMS`, `_LEGACY_COMPATIBILITY`, `_measured_energy_cohort`, `trusted_row_provenance`, `observation_value_digest`. Everything else is removed (simulation models, comparison builders, run splitting, cohort selection, fitting, SoC-endpoint trust, `history_coverage`, `METHOD_VERSION`, `FIT_*`, `SLOT`).
- **Then rename it to `backend/observation_provenance.py` (`git mv`), with its test file to `tests/test_observation_provenance.py`.** After removal the module only holds recorded-observation provenance and eligibility helpers, so the old name misleads and invites re-adding comparison code. Rename happens after the deletion so history shows removal and move as separate steps. Importers updated: `backend/learning/store.py`, `backend/comparison_history.py`, `tests/ml/test_learning_engine.py`. No compatibility shim; there are no other importers. Alternative: keep the old name for a pure-deletion diff; rejected because the leftover name no longer describes the contents.
- **Specs:** remove the four `command-bar` requirements describing the retired self-use comparison; `grid-financial-wear-display` already owns the Grid domain display. `comparison-history-provenance` and `energy-recording` describe the retained provenance/eligibility rules and stay unchanged.
- **Delete `backend/baseline.py` outright.** Only tests import it.
- **Tests:** delete `tests/test_battery_comparison_segmentation.py` and `tests/backend/test_baseline.py`; in `tests/test_battery_comparison.py` delete dead-only tests, keep the three tests that only use live symbols, rewrite the two mixed tests (`test_retained_cached_start_soc_is_not_certified_by_live_end_soc`, `test_malformed_provenance_values_are_unknown_without_crashing`) to assert only through `calibration_eligible` / `trusted_row_provenance`. Keep `recording()` and `trusted_flags()` helpers (the learning-engine test imports `recording()`), rewriting `recording()` if it depends on removed models.
- **Comparison-history test:** replace the `fit_calibration(...).history["eligible_count"]` check with a count of rows passing `calibration_eligible`, preserving the intent (annotation undo keeps eligibility).
- **No permanent absence tests or guards for the retired feature.** Once the code is deleted nothing can emit `baseline`, `baseline_*` or `battery_comparison` or run a self-use replay, so tests and runtime checks that only assert their absence have no lasting value; they only keep the dead names alive in the codebase. Removed:
  - `tests/api/test_battery_comparison_api.py:107-114` (the `fail` helper, `import backend.baseline`/`backend.battery_comparison`, both `monkeypatch.setattr` calls). The test at :91-93 is renamed to `test_request_reads_only_selected_period_and_does_not_write` and its now-unused `monkeypatch` parameter dropped; the single-select, period-bound and `before == after` checks stay. The file is renamed (`git mv`) to `tests/api/test_grid_only_comparison_api.py` and its docstring (:1) changed to describe grid-only API tests without "retired". Its other `not in` assert (:195, `saving_sek` absent on unavailable) is live grid-only contract and stays.
  - `tests/api/test_energy_cost_series.py:82-84` (`"baseline"`, `"battery_comparison"` and per-point `baseline_cumulative_net_cost_sek` absence). Other `not in` asserts in that file (:151-153, :160, :209) check the live grid-only contract and stay.
  - `frontend/src/lib/api.ts:789` (`if ('baseline' in value || 'battery_comparison' in value) return invalidCostSeries()`) and `:793` (`if (Object.keys(raw).some((key) => key.startsWith('baseline_'))) return invalidCostSeries()` inside the `value.points.map`). Nothing else reads these keys; the remaining validation (record/period/bucket at :786, points array at :790, per-point timestamp and finite amounts at :792-801, `grid_only_comparison` checks after) is unchanged. Unknown extra keys are then ignored like any other unknown key.
  - `frontend/src/lib/api.cost-series.test.ts:125-129` (`rejects retired baseline and battery-comparison fields instead of falling back`).
  - `frontend/src/components/CostSeriesChart.test.tsx:116` (`queryByText('Without Darkstar')` absence). The tab and comparison-button absence asserts (:117-118) stay; they enforce the live "no Actual/Comparison switch" rule in grid-financial-wear-display.
  - Kept: `tests/test_grid_only_comparison.py` `not in` asserts (live contract), and the explanatory comment at `backend/api/routers/energy.py:426-427` (documents why the route reads only the selected period; reword to drop "retired" is optional and not planned).
  - Grep of `frontend/src` for `battery_comparison`, `baseline`, `self_use`, `Without Darkstar`, `configured_losses` finds no other retired-feature types or guards (remaining `baseline` hits are CSS `items-baseline`, Aurora/forecast baseline and unrelated config help).
- **Spec alignment:** the energy-totals-api requirement is renamed to "Cost series endpoint returns the grid-only comparison" and loses its retired-field absence and no-fallback clauses; the grid-financial-wear-display "Direct grid-only line" scenario drops "Without Darkstar legend". The scenario name "Preserved actual points and retired fields" is kept because OpenSpec's strict validator treats a renamed scenario as a dropped one. `grid-only-comparison` "No simulation or calibration in the financial endpoint" stays: it also forbids planner optimization and calibration caching and is still partly enforced by the single-select/no-write API test.

## Risks / Trade-offs

- [A future change re-adds a `baseline`/`battery_comparison` key] → accepted; the frontend would ignore it, and code review covers reintroduction.

- [A hidden importer of a removed symbol] → repo-wide grep for every removed name plus the full test suite and `ruff` before finishing.
- [Losing the SoC-endpoint coverage the mixed tests gave] → those rules only guarded removed code; the retained eligibility rules stay covered by rewritten tests.

## Migration Plan

Code-only deletion; no data or config migration. Rollback is a git revert.
