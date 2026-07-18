# Proposal: price-alert-accuracy

## Why

A replay of the analyst price alerts against 97 days of production forecasts and actual prices (2026-07-17 investigation) showed two of the three rules are broken: the "prices rising" rule is structurally dead code (it uses D+1's average as the "today" reference, so it compares D+1 against itself and fired 0/97 days), and the "cheap overnight" rule fired 93/97 days while being justified only 12 times — in summer the cheapest hours are midday solar hours, yet the alert claims "Tonight 22:00–06:00 has the lowest prices". The existing spec already promises a real 22:00–06:00 window comparison; the implementation uses a min-slot heuristic instead.

This change also closes the two S-Index calibration backlog items with evidence, no code change (see Impact).

## What Changes

- Compute a true "today" reference price (average of today's known spot prices) and use it in the alert rules, replacing the `daily_outlook[0]` (= D+1) proxy.
- "Cheapest day ahead" (Rule 1): keep the 30% relative threshold but compare against the real today average, and additionally require a minimum absolute drop of 0.15 SEK/kWh to suppress noise-firing at low price levels (fired 57/97 days in replay, ~26% of them wrong).
- "Prices rising" (Rule 2): logic unchanged, but it becomes functional once the today reference is real (currently can never fire).
- "Cheap overnight" (Rule 3): replace the min-slot heuristic with the actual forecast 22:00–06:00 window average vs the next day's average, firing at 25%+ below — matching what the existing spec already promised. When the day's cheapest contiguous hours are instead in the solar midday window, emit a "midday solar hours are cheapest" message instead of the false overnight claim.
- Unit tests for all three rules, including a dead-code regression test (Rule 2 must be able to fire) and a summer solar-dip fixture for Rule 3.
- Verification: re-run the calibration replay against the new rules; Rule 3 fire count must drop from ~96% of days to roughly the justified ~12%.

## Capabilities

### New Capabilities

<!-- none -->

### Modified Capabilities

- `price-advisor-engine`: the "today" reference becomes today's actual average spot price (not D+1); Rule 1 gains a minimum absolute-drop threshold; Rule 3's overnight comparison is computed from the real 22:00–06:00 forecast window with a solar-midday alternative message.

## Impact

- **Code:** `backend/api/routers/analyst.py` (`_get_price_advice()` and its call site), possibly `backend/core/price_outlook.py` for the today-average and overnight-window helpers.
- **Frontend:** none — message strings change slightly but the advice item shape (`category`/`message`/`priority`) is unchanged; SmartAdvisor renders them as-is.
- **Tests:** new unit tests for the advice rules (currently untested).
- **Backlog:** deletes all three "(needs production data)" calibration items from `docs/BACKLOG.md`. The other two close with documented no-change verdicts from the 2026-07-17 replay: `RISK_PRICE_KW_FRACTION` stays `{1: 0.15, 2: 0.12, 3: 0.10, 4: 0.05, 5: 0.02}` (zero false fires in 97 days; sane winter magnitudes at every risk level; the observed weakness — missed events — traces to the price forecast's low bias, not the fractions), and `calculate_price_floor_addon()` keeps the pure-peak signal (forecast error is flat across D+1..D+7, the feared bad-far-day false fires never occurred, and top-2 averaging only increases missed events).
