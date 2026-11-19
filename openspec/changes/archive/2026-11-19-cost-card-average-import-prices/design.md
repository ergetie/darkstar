## Context

`get_energy_range` already runs one aggregate `select` over `SlotObservation` for the period and builds the response from positional row indices. The Cost card (`CommandDomains.tsx`) renders a Financial Breakdown from that response.

Non-obvious naming: in `slot_observations`, `export_price_sek_kwh` is the pure Nordpool spot price (no fees, VAT or markups) for the slot, regardless of direction. `import_price_sek_kwh` is the all-in per-kWh import price (spot plus grid fee, energy tax, VAT, markups). So the "raw spot price of imported energy" is `export_price_sek_kwh` weighted by `import_kwh`. This must be commented in code and in the spec.

Related change: `bill-accurate-costs` (fixed fees) is NOT in-progress; it is archived as `openspec/changes/archive/2026-11-08-bill-accurate-costs` and its result lives in `openspec/specs/fixed-fee-costs`. This change is independent of it: fixed fees (`fixed_fees_sek`, `fixed_fees_for_range`, `net_cost_sek`) are untouched and deliberately excluded from the averages. File overlap is only `backend/api/routers/energy.py` (same function and same response dicts, different fields and lines) and `CommandDomains.tsx` (same card, different rows); there is no logical dependency or merge-order requirement. The working tree also has uncommitted unrelated edits (e.g. beta-exit-hardening) that touch other files; implementers must not stage them.

## Goals / Non-Goals

**Goals:**
- Two weighted averages in the range response and Cost card, correct under NULL prices and zero import.

**Non-Goals:**
- No fixed fees, subscriptions, export-side or battery-wear in either average.
- No change to `/energy/today`, `/energy/cost-series`, DB schema, config or `docs/`.
- No per-slot or chart display.

## Decisions

1. **Formulas (SQL, same select as existing sums).** Let `imp = coalesce(import_kwh, 0)`.
   - Spot numerator: `SUM(CASE WHEN import_kwh > 0 AND export_price_sek_kwh IS NOT NULL THEN import_kwh * export_price_sek_kwh END)`; denominator: `SUM(CASE WHEN import_kwh > 0 AND export_price_sek_kwh IS NOT NULL THEN import_kwh END)`.
   - All-in numerator/denominator: identical with `import_price_sek_kwh`.
   Four extra select columns appended after the existing last column (index 16-19) so existing indices stay valid. Implemented with SQLAlchemy `case(...)`. Rationale: each price column gets its own kWh denominator, so a slot with a spot price but no all-in price still counts for the spot average only.
2. **NULL handling.** NULL price excludes the slot from that average's numerator and denominator. A price of 0.0 is a real value and is included. Missing is never coerced to 0. Negative prices (negative spot) are real and included.
3. **Only `import_kwh > 0`.** NULL or zero import slots never contribute.
4. **Result computation in Python.** `avg = num / den` when `den` is not None and `den > 0`, else `None`. SUM over no rows yields NULL, which maps to `None`.
5. **Response fields.** `avg_import_spot_sek_kwh` and `avg_import_price_sek_kwh`, unrounded-to-display: rounded to 4 decimals (SEK/kWh values are small; the UI rounds again for display). `null` when not computable. Fallback (exception) dict includes both as `None`. Added in the main dict next to `import_cost_sek`.
6. **No fixed fees.** The averages are computed only from slot sums; `fixed_fees_sek` is neither added nor divided. A test asserts the averages are identical with non-zero configured fixed fees.
7. **Frontend price formatting.** Reuse the existing `formatPrice(v)` from `frontend/src/components/ChartCard.logic.ts` (two decimals, `SEK/kWh`, shared `EMPTY_VALUE` dash for null/undefined). No new helper is added, so per-kWh prices are formatted the same way as in the chart card.
8. **UI placement.** Two rows in the Financial Breakdown directly after the Grid Import block (below its EV sub-row), same row markup (`flex items-baseline justify-between`, `text-muted` label, `tabular-nums whitespace-nowrap` value, `bg-surface2/30` container), per `docs/design-system/AI_GUIDELINES.md` tokens only. Labels: "Avg spot price (imported)" and "Avg import price (all-in)". Each label has a `title` tooltip: spot = "Raw Nordpool spot price, weighted by imported kWh. No fees, tax or VAT."; all-in = "Includes grid fees, energy tax, VAT and markups, weighted by imported kWh. Fixed fees are not included." Value colour is `text-text` (neutral, informational, not a cost or gain). The rows are not added to Net.
9. **Empty state.** When the value is `null` the row stays visible and shows `–` in `text-muted`, so layout does not jump between periods. Rows render only when `rangeData` exists (same as the rest of the breakdown).
10. **Type plumbing.** `rangeData` state type gains `avg_import_spot_sek_kwh: number | null` and `avg_import_price_sek_kwh: number | null`, mapped with `?? null` so an older backend response yields the dash.
11. **Tests.** Backend: new `tests/api/test_energy_avg_import_prices.py` using the existing in-memory store pattern from `tests/api/test_energy_ev_cost.py`; no network or webhooks; safe under `pytest -n auto` (own temp DB per test). Frontend: extend `CommandDomains.test.tsx` with values rendering and null state.

## Risks / Trade-offs

- Row index drift in the positional select: mitigated by appending new columns at the end only.
- Slots recorded before prices existed have NULL prices: they are excluded rather than skewing the average; the average then reflects only priced slots. Accepted and documented in the spec.
- Spot average uses a column whose name suggests export: mitigated by code comment and spec wording.

## Migration Plan

None. Additive response fields; no DB change. Rollback is reverting the commit.

## Open Questions

None.
