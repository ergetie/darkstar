## Context

Three consumers need per-day spot prices:

- **EV multi-day quota** — `planner/pipeline.py:1449` → `fetch_price_floor_inputs` → `_compute_daily_ev_quota` → `MultiDayPlanner`. Kepler enforces each in-horizon day's quota as a cap, and the sum of in-horizon quotas as the soft requirement (`planner/solver/kepler.py:683-717`). So an inflated "today" quota is effectively forced into today's slots.
- **Battery safety-floor price addon** — `planner/pipeline.py:1179`, same function.
- **Daily outlook** — `backend/core/price_outlook.py:get_daily_outlook`, latest forecast run only.

All three read only `price_forecasts.spot_p50`. The slot-level plan itself is correct: `backend/core/prices.py:get_nordpool_data` returns real Nordpool for today (and D+1 after 13:00). Before 13:00 it appends ML-forecast fallback entries for D+1 that are indistinguishable from real ones in the output.

Evidence (prod, 2026-09-24 ~23:00): the forecast for 23:00–23:45 was 0.24/0.24/0.18/0.18 SEK (issue 2026-09-23 06:00); the real spot was 2.07/2.07/2.00/1.97 SEK. The logged quota was `{Thu: 11.0, Fri: 2.3, Sat: 4.17, Sun: 3.08, Mon: 1.05}`.

## Goals / Non-Goals

**Goals:**
- Published Nordpool spot is always used when known; the forecast only fills gaps.
- One resolver shared by all three consumers.
- Today keeps averaging only remaining slots.

**Non-Goals:**
- Changing the inverse-price weighting, minimum daily fraction, caps, or Kepler's quota constraints.
- Adding grid fees/VAT to the weighting.
- Planned-EV chart history (separate change: `ev-planned-history`).

## Decisions

1. **Resolver lives in `backend/core/prices.py`.** Name: `get_known_spot_by_slot(config) -> dict[datetime, float]` (SEK/kWh, local-tz slot start, raw spot). It reuses the Nordpool fetch that `get_nordpool_data` already does and its cache. It returns only genuinely published entries.
   - *Alternative:* read `slot_observations.export_price_sek_kwh`. Rejected: the recorder only covers slots already recorded, not published future slots.
2. **Tag entries in `get_nordpool_data` with `price_source: "nordpool" | "forecast"`.** Fallback entries get `"forecast"`. This is additive, so existing consumers ignore the field. The resolver filters on `"nordpool"`. It keeps a single fetch path and avoids a second Nordpool call.
3. **Merge per slot, then average per day.** For each slot in the window, use the known spot if present, else the latest-issue `spot_p50`. Group by local date. Offset 0 skips `slot_start < now`. The per-day averages stay comparable because each slot uses the most accurate available value.
4. **Planner async boundary.** `fetch_price_floor_inputs` is already async and wraps a sync DB read. It awaits the resolver first, then passes the known map into `_fetch_price_floor_inputs_sync` for the merge. If Nordpool is unavailable, it falls back to forecast-only and logs a warning, which is the current behaviour.
5. **Outlook.** `get_daily_outlook` is sync. It has two callers: `async_get_daily_outlook`, used by `backend/api/routers/price_forecast.py:362`, and the Aurora advisor at `backend/api/routers/analyst.py:204`, whose "Prices drop X% on Sat" alerts come from it. It gains an optional `known_spot` map, which both callers supply via the resolver. For a day with published prices, `avg_spot_p50` / `min_hour_p50` / `max_hour_p50` use merged values. p10/p90 for known slots equal the known value, since there is no uncertainty.
6. **Diagnostics.** The quota log line adds per-day `known/forecast` slot counts.

## Risks / Trade-offs

- [The safety-floor addon changes behaviour too] → Intended: it had the same stale-forecast flaw. Its tests are re-run, and a test is added for a known-price day.
- [A Nordpool fetch failure would silently regress to forecast-only] → A warning log, plus the per-day source counts in the log line.
- [Timezone/DST key mismatch between Nordpool datetimes and forecast ISO strings] → Normalize both to tz-aware local datetimes before merging. Add a test around a DST boundary.

## Migration Plan

No data migration. Rollback = revert the commit.
