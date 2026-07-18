# Tasks: price-alert-accuracy

## 1. Data helpers

- [x] 1.1 Add a helper in `backend/core/price_outlook.py` returning the latest-issue p50 average over the overnight window [today 22:00, tomorrow 06:00) and over tomorrow's midday window [10:00, 16:00), computed with timezone-aware datetimes (no manual hour arithmetic); returns None per window when slots are missing
- [x] 1.2 In the `/api/analyst/advice` route, compute today's actual average spot price from `get_nordpool_data()` (mean over today's slots); on failure or empty data, skip price advice while returning remaining advice categories

## 2. Rule rewrite

- [x] 2.1 Extract the alert thresholds in `backend/api/routers/analyst.py` into module-level named constants: relative drop 0.70, minimum absolute drop 0.15 SEK/kWh, window ratio 0.75
- [x] 2.2 Rule 1: compare each D+1..D+7 daily average against today's actual average; require both ≥30% relative and ≥0.15 SEK/kWh absolute drop
- [x] 2.3 Rule 2: unchanged logic against the real today average (D+1..D+3 all higher ⇒ "today is the cheapest day in the next 3 days")
- [x] 2.4 Rule 3: fire "overnight cheapest" only when the overnight window average is ≥25% below tomorrow's daily average; when overnight does not qualify but the midday window average is ≥25% below, emit the solar-midday message instead; remove the min-slot heuristic
- [x] 2.5 Keep `_get_price_advice()` a pure function of its inputs (outlook list, today average, window averages) so tests and the calibration replay can drive it directly

## 3. Tests

- [x] 3.1 Rule 1: fires on ≥30% + ≥0.15 SEK drop; suppressed when relative-only (tiny absolute) or absolute-only (<30%)
- [x] 3.2 Rule 2 regression: fires when D+1..D+3 all exceed today's actual average (would never fire under the old D+1-as-today proxy)
- [x] 3.3 Rule 3: fires on a genuinely cheap overnight window; does NOT fire when only a single cheap slot exists (old-heuristic regression); summer solar fixture emits the midday message and no overnight message
- [x] 3.4 Degradation: today's prices unavailable ⇒ no price items, other advice categories intact; forecast disabled and no-forecast-rows behaviors unchanged

## 4. Verification

- [x] 4.1 Run the full test suite and linters — all green
- [x] 4.2 Re-run the 2026-07-17 calibration replay (`openspec/changes/price-alert-accuracy/replay.py`, Part D; re-exported the two CSVs from prod per the script header) against the new rule logic — see results below
- [x] 4.3 Visually verify the SmartAdvisor card renders the new messages (only display location for price alerts per `smart-advisor` spec)

## 5. Backlog bookkeeping

- [x] 5.1 Delete the three "(needs production data)" calibration items from `docs/BACKLOG.md` (done at change-creation time per workflow rules; the two S-Index items closed with the no-change verdicts recorded in this change's proposal)
