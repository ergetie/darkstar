## Context

- The Kepler MILP only sees published Nordpool prices (rest of today; plus tomorrow after ~13:00 CET). Its terminal SoC target comes from `calculate_safety_floor` (`planner/strategy/s_index.py`): Layer 1 reserves energy for the load/PV deficit of the 24 h after the price horizon (capped per risk level); Layer 2 adds a "price floor addon" from 7-day daily-average forecasts versus a 14-day mean. The target is enforced with a 200 SEK/kWh under-target penalty (`planner/pipeline.py` ~1813), so raising it effectively pre-charges in the cheapest known slots.
- Evidence (read-only replays on production data, Apr-Oct 2026 with live forecasts, Dec 2025-Mar 2026 with leakage-free reconstructed forecasts, real prod config):
  - Layer 2 addon: ~0 SEK/month, negative on ~40% of days; it follows daily averages, not the cheapest charging hours.
  - The value only exists when the unseen day's own cheapest charging hours cost more than the cheapest hours left in the known window (true ~56% of days). A rule based on that: ~50-70 SEK/month at the 13:30 decision; hindsight ceiling ~90-120. Thresholds 0-0.2 SEK/kWh performed alike.
  - The price forecast runs once at 06:00 (`backend/services/scheduler_service.py`), before tomorrow's prices exist. Re-issuing after publication with D+1 prices as lags cut daily-average MAE by ~6% (CI excludes zero).
  - Dedicated gap model, uncertainty-based sizing and extra data sources gave no robust gain; they are out of scope.
- Users run SE1-SE4 (and other areas), Ampere- or Watt-controlled inverters, flat or time-of-use fees, very different battery sizes; the change must use only each user's own configuration.

## Goals / Non-Goals

**Goals:**
- Replace the Layer 2 addon with a reserve for the first unseen day, driven by cheapest-hour economics.
- Use the user's own power limits (same resolver as the solver), efficiencies, wear, SoC limits, fees and load/PV forecast.
- Add a post-publication price forecast run with leakage-consistent lag handling for inference and training.
- Fail safe: any missing input degrades to Layer 1 only, never fails a planner run.

**Non-Goals:**
- No new config keys or UI settings.
- No new external data sources, no dedicated gap model, no quantile-based sizing, no p10/p90 recalibration.
- No change to Layer 1, the solver objective, EV deferral or the price outlook.
- No change to `docs/` (ask separately if user docs should describe the reserve).

## Decisions

1. **Unseen window = the 24 h after the price horizon end** (identical to Layer 1's look-ahead). Works before publication (unseen = tomorrow) and after (unseen = D+2) without special cases. Alternative: calendar D+2 only — rejected, it would idle half the day.
2. **Marginal-cost greedy sizing (pure function).** Visit unseen slots by descending forecast import price; add energy while `min(P_h, own_day_cost) − known_cost > threshold`, recomputing marginal costs from cheapest-first slot capacities (`max_kw × slot_hours`). This is the replay's value function (`max(0,P−ck) − max(0,P−co)`) made explicit and testable. Implemented as `size_price_reserve(...)` in `planner/strategy/price_reserve.py` (new module, no I/O), called from `calculate_safety_floor`. Alternative: put the unseen day into the MILP horizon with forecast prices — rejected (solve time ×~2, forecast error enters every decision).
3. **Combine with `max`, not addition.** Layer 1 already reserves for the same 24 h deficit; adding would double-count. Cap at `max_soc` and at what the known window can physically charge, so the 200 SEK/kWh penalty never forces infeasible or absurd grid charging.
4. **Risk threshold map 1→0.20 … 5→0.00 SEK/kWh.** Uses the existing risk setting; replay showed 0-0.2 equivalent, so cautious users trade a little value for fewer loss days.
5. **Shared power-limit resolver.** Extract the adapter's A/W logic (`planner/solver/adapter.py` ~500-512) into `resolve_battery_power_limits(planner_config) -> (charge_kw, discharge_kw)`; the adapter and the reserve both call it, so the reserve can never assume a different limit than the solver (a 5 kW vs 8.88 kW mismatch was found during the investigation). The reserve takes the resolver's discharge limit as is; the inverter AC limit is intentionally not applied, so reserve and solver never disagree.
6. **Wear from `battery_economics.battery_cycle_cost_kwh`.** The strategy engine's dynamic wear override is applied later to the solver; the reserve uses the configured base value and documents it. Sensitivity in the replay was <10%.
7. **Forecast lags use observations, then published prices.** `_get_price_lags` / batch features receive a `known_spot` map (from `get_known_spot_by_slot`, forecast-fallback excluded). The run records `known_prices_until` (end of the last published slot, so it is also non-null for the 06:00 run, where it is the end of today; training treats today's published prices as knowable, consistent with inference). Training masks a lag if its source slot is not `< issue_timestamp` and not `< known_prices_until`. One nullable column, additive migration; legacy rows keep the old rule. Alternative: infer knowability from issue hour ≥ 13:00 — rejected, wrong on late publication or custom `daily_run_time`.
8. **Post-publication run = D+2..D+7 only.** Keeps the morning D+1 rows intact for the D+1 fallback and accuracy KPI. Triggered by actual publication (tomorrow fully present in known spot), checked at most every 10 min from 12:00 local, once per day, idempotency from the DB. The "waiting for publication" info log is written once per local day. `generate_price_forecasts` takes the range as `days_ahead_range`. Nordpool fetches are cached by `get_nordpool_data`; the 10-minute throttle bounds extra calls.
9. **Deduplicated strategy event.** Compare against the last price-reserve event in strategy history (≥1.0 kWh change or active/inactive flip). Today's addon writes an event on every run (100 of 100 recent events on prod were "Price signal"). The event is emitted from `planner/pipeline.py` (not `calculate_safety_floor`) and tagged `details.kind = "price_reserve"`; that tag is how the last event is found for the comparison.
10. **Initial SoC resolved earlier in the pipeline.** The initial-SoC resolution in `planner/pipeline.py` moved before the strategy step so the reserve and Kepler start from the same value.
11. **Debug semantics.** `price_reserve_active` means the reserve was sized > 0, even when the deficit floor already covers it (`price_reserve_applied_kwh` then stays 0). An extra key `price_reserve_capped_by` (`usable_capacity` or `known_window_charge`) is present only when a physical cap reduced the reserve.
12. **Resolution and tuning alternatives (replayed, rejected).** Prices stay at native 15-minute resolution on both sides. Hourly averaging, forecast dip-bias correction (trailing quantile map and additive) and thresholds 0.2/0.3 were replayed on production data (summer and winter, 15-minute scoring) and gave no gain or lost value (dip correction −7.5 SEK/month in winter), so the risk-3 threshold 0.10 and raw 15-minute prices are kept. Replay result for the shipped rule: ~82 SEK/month in summer and ~55 in winter at the 13:30 decision. All-or-nothing behaviour (≈0 kWh about half the days, 16-23 kWh on active days) is expected.

## Risks / Trade-offs

- [Forecast error makes the reserve lose money on some days (~15-20% in replay)] → risk threshold; value is net positive in both seasons; monitored via debug fields and events.
- [Replay value is upward-biased (planner may already hold some energy)] → accepted; current rule is ~0, so even a smaller gain is an improvement; no claim of a specific saving in user-facing text.
- [Model trained on mixed lag regimes (NaN vs published D+1)] → LightGBM handles NaN natively; legacy rows unchanged; quality checked by the existing accuracy KPI after rollout.
- [Unseen-day own-cheap-hours ordering ignored (cheap hours after the expensive ones)] → this overstates `own_day_cost` availability, so the reserve is conservative, not aggressive.
- [Extra Nordpool calls while waiting for publication] → 10-minute throttle plus existing cache.
- [Extended load forecast missing for some users] → 90% coverage gate, reason reported, Layer 1 unaffected.
- [Users without price forecasting] → behaviour equals today's Layer 1 floor only (the addon was already off for them).

## Migration Plan

1. Alembic migration adds nullable `price_forecasts.known_prices_until` (runs automatically on startup like existing migrations); downgrade drops the column.
2. Deploy; the next morning and post-publication runs start writing the column; training picks it up on its next cycle with no retrain required for correctness.
3. Rollback: revert the release; the column is ignored by old code (nullable, unused).

## Open Questions

- None blocking. Optional later: user-facing docs text for the reserve (needs approval for `docs/` changes).
