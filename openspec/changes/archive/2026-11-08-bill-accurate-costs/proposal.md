## Why

Darkstar's actual cost omits fixed monthly fees, supplier per-kWh markups and uses an outdated energy tax default. Against a real E.ON October 2026 bill (2625.30 kr) Darkstar showed 1896.33 kr; the 728.97 kr gap is fully explained by fixed fees (678 kr), supplier markup (154 kr) and tax/default drift. Costs must match the bill.

## What Changes

- Add fixed fees to actual cost: existing `pricing.subscription_fee_sek_per_month` (grid) plus new `pricing.supplier_fee_sek_per_year`, both excl VAT, VAT applied, prorated per local calendar day over the requested range.
- `/energy/range` returns `fixed_fees_sek`, included in `net_cost_sek` and `net_cost_incl_wear_sek`; `/energy/cost-series` stays energy-only so the chart lines remain comparable. Fees never enter grid-only comparison, battery benchmark/hindsight or learning metrics.
- Add `pricing.supplier_markup_sek_kwh` (excl VAT) inside the VAT bracket of the import price formula. Export stays raw spot (out of scope: export credits).
- Change energy tax default 0.439 -> 0.36 (code fallback, config.default.yaml, onboarding and help text); migration rewrites only a value equal to 0.439.
- `bin/backfill_prices.py` and `bin/backfill_vattenfall.py` call the shared price function instead of duplicated hardcoded formulas.
- New "Recalculate costs from [date]" endpoint and Settings button repricing `slot_observations.import_price_sek_kwh` from stored raw spot export price.
- Settings UI regrouped: "Grid operator" and "Electricity supplier"; new "Fixed fees" row in the Grid & Financial card.
- Known accepted effect: old `slot_plans` are not repriced, so the learning plan-vs-actual cost metric steps at the recalculation date.

## Capabilities

### New Capabilities
- `fixed-fee-costs`: proration and inclusion of fixed fees in actual cost APIs and the UI card, with exclusions.
- `supplier-markup-pricing`: supplier markup and updated energy tax default in the import price formula, config keys, migration, settings layout.
- `cost-recalculation`: endpoint and UI action to reprice historical import prices.

### Modified Capabilities
<!-- none: new capabilities own these requirements -->

## Impact

backend/core/prices.py, backend/api/routers/energy.py, backend/api/routers/config.py (new recalc endpoint or sibling router), backend/config_migration.py, config.default.yaml, bin/backfill_*.py, frontend CommandDomains.tsx, settings types.ts/AdvancedTab pattern/api.ts, onboarding steps.tsx, config-help.json. No schema change, no new dependencies.
