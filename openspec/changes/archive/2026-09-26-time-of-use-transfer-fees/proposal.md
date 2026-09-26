## Why

Many grid operators charge a time-of-use transfer fee (tidstariff): the fee per kWh depends on month, weekday and hour (e.g. higher on winter weekdays 06–22). Darkstar only supports one flat `pricing.grid_transfer_fee_sek`, so the planner optimises against wrong import prices for these users. Winter is approaching, which is when these tariffs bite.

## What Changes

- Add an optional ordered rule list `pricing.transfer_fee_rules` plus a mode switch `pricing.transfer_fee_mode: flat | time_of_use` (default `flat` — existing configs behave identically, no migration needed).
- Each rule = a reusable **time window** (`months`, `weekdays`, `hours` range, all optional) + `fee_sek`. First matching rule wins; the flat `grid_transfer_fee_sek` is the catch-all for slots no rule matches.
- Optional toggle `pricing.holidays_as_weekend` (Swedish public holidays treated as Sat/Sun when matching weekdays). Computed in-code, no new dependency.
- Import price calculation becomes timestamp-aware: fee is resolved per slot (Nordpool slots, price forecast slots, EV post-horizon slots).
- Settings → System → "Pricing & Timezone": Flat / Time-of-use toggle, rule table editor (add, delete, reorder), holiday toggle, and a 24h fee preview strip for a chosen date.
- Config-save validation for rules (hour range, month/weekday values, non-negative fee).
- Energy tax and VAT stay flat. Historical slot prices are not recomputed (recorder already stores the price that applied).
- The window matcher is built as a standalone unit so the future KISS peak guard (`docs/designs/effekttariff-kiss.md`) can reuse it to define which hours count toward the peak. Peak guard itself is **out of scope**.

## Capabilities

### New Capabilities
- `time-of-use-transfer-fees`: per-slot grid transfer fee resolved from ordered time-window rules, holiday handling, validation, and the settings editor.

### Modified Capabilities
<!-- none: no existing spec covers import price composition -->

## Impact

- Backend: `backend/core/prices.py` (`calculate_import_export_prices` gains slot time), callers in `ml/price_forecast.py`, `planner/strategy/ev_deferral.py`; new module for window matching + Swedish holidays; `backend/api/routers/config.py` validation.
- Config: `config.default.yaml` new keys under `pricing` (commented defaults).
- Frontend: `frontend/src/pages/settings/types.ts` pricing section, new rule editor component, settings search/glossary entries.
- No DB schema change, no new dependencies.
