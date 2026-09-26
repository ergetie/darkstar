## 1. Window matcher & holidays

- [x] 1.1 Create `backend/core/time_windows.py`: `TimeWindow` dataclass, `parse_window(dict)` (raises on invalid), `matches(window, local_dt, holidays_as_weekend)` with wrap-around hour ranges
- [x] 1.2 Add `swedish_public_holidays(year)` (computus + fixed/floating days + Midsommarafton/Julafton/Nyårsafton), cached per year
- [x] 1.3 Create shared test-vector fixture `tests/fixtures/time_window_vectors.json` (window, local datetime, holiday flag, expected match)
- [x] 1.4 Unit tests: vectors, wrap-around, exclusive end, omitted fields, holidays for several years (incl. 2027 dates from spec), DST days

## 2. Price calculation

- [x] 2.1 Add `resolve_transfer_fee(slot_start, pricing_cfg, tz)` in `backend/core/prices.py` (flat/ToU mode, first match wins, skip+warn invalid rules)
- [x] 2.2 Extend `calculate_import_export_prices` with optional `slot_start`; `None` → flat fee
- [x] 2.3 Pass slot time from `_process_nordpool_data`, `ml/price_forecast.py:derive_consumer_prices` (and its caller), `planner/strategy/ev_deferral.py:spot_to_import_price` (and its callers)
- [x] 2.4 Verify/implement Nordpool price cache invalidation when `pricing.*` changes on config save
- [x] 2.5 Tests: flat parity with old formula, ToU per-slot fees, forecast and EV post-horizon paths use slot fee, invalid rule tolerance

## 3. Config & validation

- [x] 3.1 Add commented `transfer_fee_mode`, `holidays_as_weekend`, `transfer_fee_rules` example to `config.default.yaml` under `pricing`
- [x] 3.2 Confirm `backend/config_migration.py` preserves the new `pricing` keys (add to template/merge handling if needed)
- [x] 3.3 Add rule validation to `_validate_config_for_save` (errors + empty-rules warning) reusing `parse_window`
- [x] 3.4 Tests for validation messages

## 4. Frontend

- [x] 4.1 TS port of matcher + holidays (`frontend/src/pages/settings/transferFees.ts`) with vitest consuming the shared vector fixture
- [x] 4.2 `TransferFeeRulesEditor` component: mode toggle, rule rows (month chips, weekday chips, hour selects, fee), add/delete/reorder, fixed "All other times" row bound to `grid_transfer_fee_sek`, holiday toggle — per design system guidelines
- [x] 4.3 24h fee preview strip with date picker
- [x] 4.4 Wire into "Pricing & Timezone" section in `types.ts`/`SystemTab.tsx`; surface backend validation errors
- [x] 4.5 Add settings search/glossary/guide entries for the new keys
- [x] 4.6 Component tests: toggle preserves rules, reorder, add/delete, preview output

## 5. Verification

- [x] 5.1 Run `./scripts/lint.sh` and full test suites
- [x] 5.2 Manual check in dev: configure winter-weekday rule, confirm planner import prices and chart reflect per-slot fee; switch to flat and confirm parity

## 6. Follow-up fixes

- [x] 6.1 Fix clipped "Treat holidays as weekend" switch: Settings toggle layout (switch first, non-shrinking)
- [x] 6.2 Preview hour tooltips (hour range, fee, matched rule / "All other times") on hover, tap and focus; title/aria-label per hour
- [x] 6.3 Chart price breakdown resolves the transfer fee per slot in time-of-use mode (`splitPriceBreakdown` + `slotStarts`), flat unchanged
- [x] 6.4 Tests: editor tooltip/labels/toggle layout, breakdown flat/ToU/catch-all/UTC/no-slot-time, `slotStarts`
- [x] 6.5 Re-run `./scripts/lint.sh` and full test suites
- [x] 6.6 Preview strip recomputes on every render from current (unsaved) rules, mode, catch-all fee and holiday toggle; tests for fee/hours/weekday/catch-all/mode/holiday edits without a date change, incl. through the Settings form wiring
- [x] 6.7 Chart breakdown matches rules in the configured `timezone` (fallback `Europe/Stockholm`) via `pricingBreakdownFromConfig`; tests with non-Stockholm zones (Helsinki, Tokyo) and fallback
- [x] 6.8 Re-run `./scripts/lint.sh` and full test suites
