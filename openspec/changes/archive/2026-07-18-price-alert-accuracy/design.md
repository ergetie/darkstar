# Design: price-alert-accuracy

## Context

`_get_price_advice()` in `backend/api/routers/analyst.py` evaluates three rules over `get_daily_outlook()` data (D+1..D+7 daily aggregates of the latest `price_forecasts` issue). Measured against production data (97 days, 2026-04-08..2026-07-16):

- The "today" reference is `daily_outlook[0]` — i.e. **D+1**, not today. Rule 1 therefore compares against tomorrow, and Rule 2 (all of D+1..D+3 higher than "today"=D+1) can never fire (0/97 days).
- Rule 3 fires when any single 15-min slot of D+1 is below 75% of D+1's average — true on 93/97 days — and always claims "Tonight 22:00–06:00 has the lowest prices". The actual overnight window was ≥15% cheap on only 12 of those days; in summer the cheap hours are midday (solar). The existing `price-advisor-engine` spec already promises a real 22:00–06:00 window comparison.
- Rule 1 fired 57/97 days, ~74% justified — works, but chatty at low price levels.

## Goals / Non-Goals

**Goals:**
- Every alert message is true against the data it was computed from: real today reference, real overnight window, and a solar-midday message when that's where the cheap hours actually are.
- Rule 2 becomes able to fire.
- Reduce Rule 1/Rule 3 noise-firing without losing genuine events.

**Non-Goals:**
- No frontend changes — advice item shape (`category`/`message`/`priority`) is unchanged; SmartAdvisor renders messages as-is.
- No changes to the S-Index price floor addon (closed as "no change" by the same investigation).
- No confidence-weighting by model accuracy (d1_mae) — deferred; thresholds first, weighting only if noise persists.
- No new alert rules.

## Decisions

1. **Today reference = today's actual day-ahead prices via `get_nordpool_data()`** (`backend/core/prices.py`), averaged over today's slots. Nordpool day-ahead prices for today are fully known — no forecast needed. If unavailable (HA down), skip price advice entirely for that request (same degradation the current `except` already provides).
   - *Why not today's `price_forecasts` rows?* Forecasts of a known quantity; the real prices are available and exact.
   - *Why not `slot_observations`?* Only contains already-elapsed slots; the day-ahead feed has the full day.

2. **Rule 1 gains a minimum absolute drop: 0.15 SEK/kWh** in addition to the existing ≥30% relative threshold. Rationale: at summer trailing averages (~0.5 SEK), 30% can be pure noise; the forecast daily-avg MAE is ~0.25 SEK, so a combined 30%-and-0.15-SEK gate keeps only drops that outsize typical forecast error at low levels while leaving winter events untouched.

3. **Rule 3 computes the real window**: new helper in `backend/core/price_outlook.py` returning the latest-issue p50 average over slots in [today 22:00, tomorrow 06:00) and the D+1 daily average. Fire "cheap overnight" only when the window average is ≥25% below the D+1 daily average (the spec's existing threshold).
   - **Solar-midday alternative**: when overnight does not qualify but the [10:00, 16:00) window of D+1 is ≥25% below the D+1 daily average, emit "Midday solar hours have the lowest prices tomorrow — ideal for heavy loads." instead. Windows are fixed constants, not detected clusters — KISS, matches how users read the chart.

4. **Rule 2 logic stays as-is** (D+1..D+3 all above today) — it is correct once the today reference is real. Message text unchanged.

5. **`_get_price_advice()` becomes testable**: it keeps taking plain data (daily outlook list, today average, window averages) as arguments; the route assembles inputs. All threshold constants (`0.70`, `0.15`, `0.75` window ratios) become module-level named constants so the calibration replay and tests reference the same values.

## Risks / Trade-offs

- [`get_nordpool_data()` is async; advice assembly is sync helpers called from the async route] → assemble inputs in the async route function and pass values down; helpers stay sync and pure.
- [Rule 3 window spans two calendar days (today 22:00 → tomorrow 06:00) across DST changes] → compute window bounds in the configured local timezone from concrete datetimes, not hour arithmetic; add a DST fixture only if the helper does manual hour math (it should not).
- [0.15 SEK absolute threshold is a judgment call] → it is recorded as a named constant with the replay evidence in this design; the re-run verification task (below) confirms Rule 1 keeps the genuinely-justified fires.
- [Midday window fixed at 10:00–16:00 may mislabel shoulder-season dips] → acceptable; the message is advisory and strictly more truthful than the current always-overnight claim.

## Migration Plan

Pure behavior fix inside one endpoint; no schema, config, or API-shape changes. Deploys with the normal release; rollback is a revert.

## Open Questions

None — thresholds and data sources were decided against the 2026-07-17 replay evidence (see `docs/BACKLOG.md` history and the change proposal).
