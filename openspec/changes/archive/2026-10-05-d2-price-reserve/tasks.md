## 1. Database

- [x] 1.1 Add nullable `known_prices_until` (String, ISO timestamp) to `PriceForecast` in `backend/learning/models.py`
- [x] 1.2 Add an Alembic migration (revises current head) that adds the nullable column; downgrade drops it; verify `alembic upgrade head` and `downgrade -1` on a copy of a local DB with existing rows (all existing rows null)

## 2. Price forecast: lags and persistence

- [x] 2.1 Extend lag resolution in `ml/price_features.py` (`_get_price_lags` and the batch builder) to accept an optional `known_spot` map and use it for source slots with no `slot_observations` row
- [x] 2.2 In `ml/price_forecast.generate_price_forecasts`, add a `days_ahead_range` parameter (default `range(1, 8)`), fetch `known_spot` via `get_known_spot_by_slot` (empty map on failure), pass it to feature building, compute `known_prices_until` (end of the last published slot, or None; non-null for the 06:00 run too, where it is the end of today) and store it on every record
- [x] 2.3 Persist `known_prices_until` in `_persist_forecasts` (overwrite-on-save unchanged)
- [x] 2.4 Update `ml/price_train.py`: select `known_prices_until` and mask each lag unless its source slot `< issue_timestamp` or `< known_prices_until`; legacy null rows keep the old rule
- [x] 2.5 Tests: published D+1 feeds D+2 `price_lag_1d`; unpublished stays NaN; `known_prices_until` persisted; training mask for null and non-null `known_prices_until` (incl. 24h-avg window); overwrite still yields one row per `(slot_start, days_ahead)`

## 3. Post-publication forecast run

- [x] 3.1 In `backend/services/scheduler_service.py`, add the post-publication check: price forecasting enabled, local time ≥ 12:00, not checked in the last 10 minutes, scheduler idle, tomorrow's local day fully present in `get_known_spot_by_slot`, and no row issued today with `known_prices_until` ≥ end of tomorrow (DB check, off the event loop)
- [x] 3.2 When due, run `generate_price_forecasts` for D+2..D+7; log success at info, the "waiting for publication" skip at info once per local day, failures at error without failing the scheduler; expose `last_post_publication_forecast_at` in scheduler status
- [x] 3.3 Tests: runs once after publication; not before 12:00; throttled to 10 minutes; skipped when tomorrow incomplete; no rerun after restart (DB idempotency); D+1 rows untouched by the post-publication run

## 4. Shared battery power-limit resolver

- [x] 4.1 Extract the A/W power-limit logic from `planner/solver/adapter.py` into `resolve_battery_power_limits(planner_config) -> tuple[float, float]` and use it in the adapter (behaviour unchanged); the reserve uses the resolver's discharge limit as is (the inverter AC limit is intentionally not applied, so reserve and solver never disagree)
- [x] 4.2 Tests: Ampere mode (185 A × 48 V = 8.88 kW), Watt mode, missing values; existing adapter tests still pass

## 5. Price reserve (pure sizing)

- [x] 5.1 Create `planner/strategy/price_reserve.py` with `RISK_RESERVE_THRESHOLD_SEK = {1: 0.20, 2: 0.15, 3: 0.10, 4: 0.05, 5: 0.00}` and a pure `size_price_reserve(...)` taking known-window slots (start, hours, import price), unseen-window slots (start, hours, forecast import price, net load), charge/discharge limits, efficiencies, wear, threshold, usable capacity, current SoC; returns reserve kWh, reason and debug values
- [x] 5.2 Implement marginal-cost greedy sizing per spec (slots by descending price; `gain_h = min(P_h, own_day_cost) − known_cost`; cheapest-first capacities; per-slot energy `min(net_load_h, discharge_kw × hours) / discharge_eff`)
- [x] 5.3 Apply physical caps: usable capacity and chargeable energy in the known window above current SoC
- [x] 5.4 Unit tests for every scenario in the spec: unseen day more expensive, own day cheaper, zero net load slot, risk threshold 1 vs 3, short known window cap, usable capacity cap, TOU-priced inputs, empty known window

## 6. Safety floor and pipeline integration

- [x] 6.1 In `planner/strategy/s_index.py`, remove `calculate_price_floor_addon`, `RISK_PRICE_KW_FRACTION`, `PRICE_PROXIMITY_HALF_LIFE_DAYS` and the Layer 2 block; accept the reserve inputs and compute `final = clamp(max(safety_floor, min_soc + reserve), min_soc, max_soc)` with all debug keys from the spec (present also when inactive) plus `price_reserve_capped_by` when a physical cap reduced the reserve; `price_reserve_active` means the reserve was sized > 0, even when the deficit floor already covers it
- [x] 6.2 Add fallbacks with reasons: disabled, insufficient_forecast (<90% unseen slots), insufficient_load_forecast (<90%), no_known_window, forecast_read_error (warning, run continues)
- [x] 6.3 In `planner/pipeline.py`, remove `fetch_price_floor_inputs` / `_fetch_price_floor_inputs_sync`; when `price_forecast.enabled`, fetch unseen-window `spot_p50` (latest issue per slot) off the event loop by reusing `fetch_forecast_spot_sync`, convert with `spot_to_import_price` (TOU-aware), build known-window slots from `df` import prices, net load from `full_forecast_df`, current SoC (initial-SoC resolution moved earlier in `planner/pipeline.py` so the reserve and Kepler share it), power limits from the shared resolver, and pass everything to the safety floor
- [x] 6.4 Replace the per-run "Price signal" event with the deduplicated price-reserve event, emitted from `planner/pipeline.py` and tagged `details.kind = "price_reserve"` (used to find the last event; ≥1.0 kWh change or active/inactive flip vs that event); failures logged as warnings
- [x] 6.5 Delete `tests/planner/strategy/test_s_index_price_awareness.py` and `tests/planner/test_price_floor_known_prices.py`; add integration tests: target reaches `kepler_config.target_soc_kwh`; max-combination (deficit floor wins / reserve wins); disabled forecasting makes no store query; forecast read error keeps the run alive; event dedup; baseline mode computes no reserve

## 7. Verification

- [x] 7.1 `rg` confirms no remaining references to removed symbols (`calculate_price_floor_addon`, `fetch_price_floor_inputs`, `RISK_PRICE_KW_FRACTION`, `price_addon`) outside `openspec/` and archived docs
- [x] 7.2 Run `./scripts/lint.sh` and the full test suite; all green
- [x] 7.3 Dry run against a copy of the production DB and config (read-only, `ssh darkstar` export): one planner run before and after publication, check debug fields, unseen window, power limits (8.88/8.0 kW), and that the target is the max of floor and reserve
- [x] 7.4 `openspec validate d2-price-reserve --strict` passes
