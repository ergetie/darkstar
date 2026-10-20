# Proposal

## Why

The dashboard "Without Darkstar" battery comparison (a plain self-use replay priced against Darkstar's actual cost) was retired on 2026-10-08 by `ds-vs-grid-only` and replaced by `backend/grid_only_comparison.py`. Its simulation and efficiency-fitting code still ships with no live callers, and the fitting method (efficiency from per-slot SoC deltas) is unreliable with coarse SoC steps. Leaving it invites reuse of a flawed method; the `ds-vs-grid-only` design explicitly deferred this removal.

## What Changes

- Remove the dead simulation, comparison-building, run-splitting and calibration-fitting code from `backend/battery_comparison.py` (about 980 lines), keeping only the recorded-observation provenance helpers that live code still imports.
- Rename the slimmed module to `backend/observation_provenance.py` (and `tests/test_battery_comparison.py` to `tests/test_observation_provenance.py`), updating the three importers.
- Delete `backend/baseline.py`, which has no production importers.
- Remove the four stale `command-bar` requirements that still describe the retired self-use comparison (Estimate/Verified chips, configured-loss basis, "Without Darkstar" line, calibration states).
- Delete tests that only exercise removed code; rewrite the few mixed tests to use the retained symbols only.
- Remove every test assertion and runtime guard whose only purpose is to check that the retired comparison is gone: the `baseline`/`battery_comparison`/`baseline_*` absence asserts in backend API tests, the frontend `parseCostSeriesResponse` rejection of those fields and its test, the "Without Darkstar" absence assertion in the chart test, and the self-use/calibration monkeypatches in the API test. Rename `tests/api/test_battery_comparison_api.py` to `tests/api/test_grid_only_comparison_api.py`, since all its tests cover the live grid-only comparison.
- Drop the retired-field absence wording from the `energy-totals-api` and `grid-financial-wear-display` specs so specs and code agree.
- No API output, UI rendering, config or stored-data behavior changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `command-bar`: remove the retired self-use comparison requirements, already superseded by `grid-financial-wear-display` since `ds-vs-grid-only` (67bd4717). Spec cleanup only; no runtime behavior changes.
- `energy-totals-api`: rename "Cost series endpoint returns the without-Darkstar baseline" to "Cost series endpoint returns the grid-only comparison" and drop the clauses that mandate absence of `baseline`, `baseline_*` and `battery_comparison` fields and no consumer fallback to them.
- `grid-financial-wear-display`: in "Grid & Financial card shows a cost chart for the period", scenario "Direct grid-only line" no longer mentions a Without Darkstar legend (the no-view-switch rule stays).

## Impact

- Code: `backend/battery_comparison.py` (shrinks, renamed to `backend/observation_provenance.py`), `backend/baseline.py` (deleted); imports updated in `backend/learning/store.py`, `backend/comparison_history.py`, `tests/ml/test_learning_engine.py`.
- Specs: `openspec/specs/command-bar/spec.md` (four requirements removed), `openspec/specs/energy-totals-api/spec.md` (one requirement renamed and modified), `openspec/specs/grid-financial-wear-display/spec.md` (one scenario line modified).
- Frontend: `frontend/src/lib/api.ts` (two retired-field rejection lines in `parseCostSeriesResponse`), `frontend/src/lib/api.cost-series.test.ts` (one test removed), `frontend/src/components/CostSeriesChart.test.tsx` (one assertion removed). The only behavior change: a cost-series response carrying a stray `baseline`, `baseline_*` or `battery_comparison` key is no longer rejected; the backend never emits them.
- Live consumers (import path updated only): `backend/learning/store.py` (observation range used by `api/routers/schedule.py`) and `backend/comparison_history.py` (used by `scripts/annotate_comparison_history.py`).
- Tests: `tests/test_battery_comparison.py` (renamed to `tests/test_observation_provenance.py`), `tests/test_battery_comparison_segmentation.py`, `tests/backend/test_baseline.py`, `tests/test_comparison_history.py`, `tests/api/test_battery_comparison_api.py` (renamed to `tests/api/test_grid_only_comparison_api.py`), `tests/api/test_energy_cost_series.py`; `tests/ml/test_learning_engine.py` keeps importing the `recording()` helper.
- No dependencies, migrations or config keys change.
