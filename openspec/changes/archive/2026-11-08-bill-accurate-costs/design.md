# Design

## Context

Import price is computed in one place, `calculate_import_export_prices` (backend/core/prices.py); the planner, cost card and ML price forecast inherit it. `pricing.subscription_fee_sek_per_month` exists in config but no backend code reads it. Two bin scripts duplicate the formula with hardcoded constants. Nordpool cache is already invalidated on pricing change (backend/api/routers/config.py). See proposal.md for motivation.

## Goals / Non-Goals

**Goals:** bill-accurate actual cost; one price formula; safe migration; reproducible reconciliation against the October bill.

**Non-Goals:** export credits/markups (export stays raw spot); repricing slot_plans; fees in planner, grid-only comparison, battery benchmark or learning.

## Decisions

1. **Markup inside VAT bracket**: import = (spot + transfer + energy_tax + markup) * (1+VAT). Single formula means all consumers inherit. Alternative (post-hoc add in cost card) rejected: planner would disagree with actuals.
2. **Fixed fees as a separate additive term in energy.py only**, applied after the existing net cost computation (~line 318). Keeps comparison/benchmark/learning code untouched, so no leak by construction. Tests assert absence.
3. **Proration**: per local calendar day, monthly/days_in_month(date) and yearly/days_in_year(date), times (1+VAT). Days come from the requested date range, not rows with data; a DST day is one day; today counts the full fee from midnight. A helper `fixed_fees_for_range(start_date, end_date, config)` computes the total for `/energy/range`.
4. **cost-series stays energy-only**: the chart plots the actual/DS cumulative line against grid-only and hindsight lines (CostSeriesChart.tsx uses cumulative_ds_cost_sek, cumulative_grid_only_cost_sek, cumulative_net_cost_sek). Adding fees there would compare unlike quantities, so fees appear only in `/energy/range` (card total and "Fixed fees" row).
5. **Tax default change with migration** following `_migrate_target_margin`: rewrite only if value == 0.439, so user-customised values survive. New keys added to config.default.yaml with default 0 so template_aware_merge fills them.
6. **Recalc**: iterate slot_observations from the date, compute import price via `calculate_import_export_prices(export_price*1000, config, slot_start)` (uses resolve_transfer_fee for time-of-use); skip rows with NULL export price; batch update in a transaction; return {repriced, skipped}. Frontend follows AdvancedTab confirm Modal + toast pattern with an api.ts wrapper.
7. **Backfill scripts** call the shared function with the loaded config.
8. **Settings UI** (types.ts): group "Grid operator": monthly subscription fee, transfer fee, energy tax; group "Electricity supplier": yearly fee, markups, VAT %, recalc button. All amounts excl VAT; help entries in config-help.json; remove "[FUTURE]" note.

## Risks / Trade-offs

- Learning plan-vs-actual metric steps at the recalc date (old plans keep old prices) -> accepted, documented in settings help text (docs/RELEASE_NOTES.md is not modified).
- Recalculation changes history irreversibly -> confirm Modal, explicit date, counts returned.
- Export raw spot assumption relied on by get_known_spot_by_slot -> export left unchanged.
- Float rounding in reconciliation -> test with tolerance 0.01 kr.

## Migration Plan

Config migration on startup rewrites 0.439 -> 0.36; template merge adds new keys at 0. Rollback: revert code; config keys are inert. Users run recalc manually.
