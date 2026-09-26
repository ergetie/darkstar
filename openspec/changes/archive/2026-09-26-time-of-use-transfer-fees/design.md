## Context

Import price today (`backend/core/prices.py:140`):
`(spot + grid_transfer_fee_sek + energy_tax_sek) * (1 + vat)` — a pure function of spot price. Callers:

| Caller | Has slot time? |
|---|---|
| `prices.py:_process_nordpool_data` | yes (`start_time`, local tz) |
| `ml/price_forecast.py:derive_consumer_prices` | yes (`slot_start` in caller loop) |
| `planner/strategy/ev_deferral.py:spot_to_import_price` | yes (`post_horizon_slot_starts`) |

The recorder copies `import_price_sek_kwh` from the price slots into `slot_observations`, so history keeps whatever fee applied when it was recorded.

## Goals / Non-Goals

**Goals:** per-slot transfer fee from a generic rule list that works for any grid operator; zero behaviour change for flat users; a window matcher reusable by the future peak guard.

**Non-Goals:** effekttariff / peak guard; operator presets; time-varying energy tax or VAT; recomputing historical prices; non-Swedish holiday calendars.

## Decisions

### D1. Config shape
```yaml
pricing:
  transfer_fee_mode: flat          # flat | time_of_use
  grid_transfer_fee_sek: 0.2456    # flat fee; also catch-all in time_of_use mode
  holidays_as_weekend: false       # Swedish public holidays match as Sat/Sun
  transfer_fee_rules:              # ordered, first match wins
    - months: [11, 12, 1, 2, 3]    # 1-12; omitted/empty = all
      weekdays: [0, 1, 2, 3, 4]    # 0=Mon..6=Sun; omitted/empty = all
      hours: { start: 6, end: 22 } # [start, end) local hours 0-24; omitted = all day
      fee_sek: 0.76
```
- Explicit `transfer_fee_mode` (vs. "rules non-empty means ToU") so users can switch back to flat without losing their rules.
- The flat fee doubles as the catch-all → the UI shows it as the fixed, undeletable last row "All other times". No gaps are possible.
- `hours` with `start > end` wraps midnight (22→6). `start == end` is invalid. `end: 24` allowed.
- Weekdays as ints matches Python `weekday()`; UI renders labels.

### D2. First match wins
Alternative "most specific wins" rejected: hard to explain, ambiguous ties. Ordered list + reorder in UI is predictable, and the preview strip makes mistakes visible.

### D3. Standalone window matcher
New module `backend/core/time_windows.py`:
- `TimeWindow` (dataclass: months, weekdays, hour range) + `parse_window(dict)` + `matches(window, local_dt, holidays_as_weekend)`.
- `swedish_public_holidays(year) -> set[date]` (cached).
Peak guard later adds `peak_guard.windows: [window]` using the same parser/matcher. Tariff logic (`resolve_transfer_fee(slot_start, pricing_cfg)`) lives in `prices.py` on top of it.

Matching uses the slot **start** in the configured local timezone (via existing tz config), so DST is handled by wall-clock hour. 15-min slots never straddle an hour boundary, so start-time matching is exact.

### D4. Holidays in code, no dependency
Swedish red days: Nyårsdagen, Trettondedag jul, Långfredagen, Påskdagen, Annandag påsk, 1 maj, Kristi himmelsfärd, Nationaldagen, Pingstdagen, Midsommardagen (Sat 20–26 Jun), Alla helgons dag (Sat 31 Oct–6 Nov), Juldagen, Annandag jul — plus the de-facto non-working eves Midsommarafton, Julafton, Nyårsafton, which operators commonly treat as holidays. Easter via the anonymous Gregorian computus. Adding the `holidays` PyPI package was rejected (new dependency for ~40 lines). Toggle default off; label says "Swedish public holidays".

When enabled, a holiday is treated as a weekend day: a rule's weekday filter matches it if the rule includes 5 (Sat) or 6 (Sun), and a Mon–Fri-only rule does not match it.

### D5. Signature change
`calculate_import_export_prices(spot_price_mwh, config, slot_start: datetime | None = None)`. `None` → flat fee (keeps unchanged callers/tests valid). All three production callers pass the slot time. Config is parsed per call; rule lists are tiny, cost is negligible vs. the solver, so no caching layer.

### D6. Validation
In `_validate_config_for_save`: errors for invalid months/weekdays values, invalid/equal hour bounds, negative or non-numeric fee. Warning if mode is `time_of_use` with zero rules. Runtime parser is defensive too: an invalid rule is skipped with a log warning (never crash price fetching).

### D7. UI
Settings → System → "Pricing & Timezone", replacing the single fee field:
- Segmented toggle Flat / Time-of-use.
- ToU: table rows (month chips, weekday chips, from/to hour selects, fee input, ↑↓ reorder, delete), `+ Add rule`, fixed last row bound to `grid_transfer_fee_sek`, holiday toggle.
- Preview: 24-hour strip for a date picker (default today), colored by fee, computed client-side with a TS port of the matcher (holidays included). Backend remains the source of truth; a shared test-vector table keeps TS and Python in sync.
- Follow `docs/design-system/AI_GUIDELINES.md`; reuse patterns from `SolarArraysEditor`.

## Risks / Trade-offs

- [TS/Python matcher drift] → shared JSON test-vector fixture consumed by pytest and vitest.
- [Nordpool cache holds prices computed with old rules for up to 1 h] → invalidate the price cache on config save of `pricing.*` (verify existing config-change hooks during implementation).
- [Holiday list wrong for some operator] → toggle is opt-in; list documented in helper text.
- [Non-Swedish users] → holiday toggle is Sweden-only; rules themselves are country-agnostic.

## Migration Plan

None required: absent keys → `flat` mode, identical prices. Add commented defaults to `config.default.yaml`; confirm config migration doesn't strip unknown `pricing` keys. Rollback = set mode `flat`.

### D8. Post-implementation UI fixes
- Holiday toggle uses the Settings boolean layout (switch first, `shrink-0`, label/helper beside it) so the switch can never be squeezed or clipped.
- Preview hours are buttons with hover (mouse/pen), tap (touch, toggles) and focus tooltips, rendered through a portal with the `Tooltip` component's surface styling; each hour's `title`/`aria-label` is "HH:00–HH:00: X.XX SEK/kWh (Rule N | All other times)". Tooltip hides on scroll, resize, outside tap and blur.
- Chart breakdown (`ChartCard.splitPriceBreakdown`) takes `{vat, energyTax, transferFee}` plus the slot's ISO start; the fee comes from the TS matcher (`transferFeeAt`) using the slot's wall-clock in the configured `timezone` from `/api/config` (the same key the backend matches rules in), falling back to `Europe/Stockholm` when unset or empty. The zone travels in `PricingBreakdownConfig.timezone`, built by `pricingBreakdownFromConfig` from the config ChartCard already loads (no API change). `buildLiveData` exposes `slotStarts` per chart index. No slot time (sample data) → flat fee, like the backend.
- Known inconsistency (out of scope): chart time labels and the today/tomorrow slot filter still use the hardcoded `Europe/Stockholm` default in `frontend/src/lib/time.ts` (`formatHour`, `isToday`, `isTomorrow`), shared with the Dashboard. For a non-Stockholm `timezone` the breakdown is correct per slot but the hour label shown beside it is Stockholm time. Moving labels/filters to the configured zone is an app-wide follow-up.
- The fee preview strip is derived on every render from the current (unsaved) mode, rules, catch-all fee and holiday toggle — no memoisation — so any edit shows immediately without changing the preview date. Shading is relative (min–max of the day), so a fee edit that keeps the ordering changes the numbers (tooltip, range text) but not the shading.

## Resolved Questions (user decisions)

- Holiday eves (Midsommarafton, Julafton, Nyårsafton) stay in the single holiday toggle; no separate toggle.
- The preview's default date uses the browser-local "today"; accepted.
