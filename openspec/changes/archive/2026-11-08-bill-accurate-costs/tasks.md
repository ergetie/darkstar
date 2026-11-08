# Tasks

## 1. Pricing core

- [x] 1.1 Add `supplier_markup_sek_kwh` into the VAT bracket and change tax fallback to 0.36 in backend/core/prices.py; verify tests/backend/test_prices.py and tests/core/test_transfer_fees.py pass (incl. export unchanged)
- [x] 1.2 Update config.default.yaml (tax 0.36, add subscription fee, supplier yearly fee, markup at 0) and add config validation tests in tests/config/test_config_validation.py
- [x] 1.3 Add `_migrate_energy_tax` in backend/config_migration.py (only 0.439 rewritten) with migration test
- [x] 1.4 Point bin/backfill_prices.py and bin/backfill_vattenfall.py at calculate_import_export_prices; verify with a unit test (no real webhooks)

## 2. Fixed fees

- [x] 2.1 Implement fee proration helper (per local day, month/year lengths, DST, today full day) and wire into `/energy/range` after ~line 318; verify the October reconciliation test (1090 kWh, 510/384, markup 0.1132, tax 0.36, transfer 0.2584, VAT 25% -> 678.26 kr)
- [x] 2.2 Keep `/energy/cost-series` energy-only; add a test in tests/api/test_energy_cost_series.py that buckets and cumulative values are identical with non-zero fees
- [x] 2.3 Add leak tests in tests/test_grid_only_comparison.py and tests/backend/test_battery_benchmark.py showing results unchanged with non-zero fees

## 3. Recalculation

- [x] 3.1 Add recalc endpoint (reprice from stored export price, resolve_transfer_fee, skip NULL, return counts) with endpoint test
- [x] 3.2 Add api.ts wrapper and Settings Pricing button with confirm Modal and toast following AdvancedTab pattern; verify settings tests

## 4. Frontend

- [x] 4.1 Add "Fixed fees" row to CommandDomains.tsx between Grid Import and Export Rev; verify CommandDomains.test.tsx
- [x] 4.2 Regroup settings in types.ts ("Grid operator", "Electricity supplier"), add config-help.json entries, remove "[FUTURE]" note, update onboarding steps.tsx text; follow docs/design-system/AI_GUIDELINES.md and verify settings tests
- [x] 4.3 Document the learning-metric step at recalculation date in help text; verify text present

## 5. Integration

- [x] 5.1 Reconcile against a copy of production data (never the live DB): with the October bill settings, `/energy/range` for 2026-10-01..31 after recalculation is within the 6 kWh metering difference of 2625.30 kr minus the out-of-scope export credits (~26 kr)
- [x] 5.2 Run `./scripts/lint.sh` and full affected test suites; verify all pass

## Workflow follow-up

- Archive the change after review.
