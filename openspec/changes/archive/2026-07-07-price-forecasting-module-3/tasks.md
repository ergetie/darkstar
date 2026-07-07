## 1. Price Floor Addon Calculation

- [x] 1.1 Add `RISK_PRICE_KW_FRACTION` dict constant near the top of `planner/strategy/s_index.py` (alongside the existing `RISK_CONFIG` dict):
  ```python
  RISK_PRICE_KW_FRACTION: dict[int, float] = {
      1: 0.15,  # Safety:       15% of capacity per SEK/kWh weighted spread
      2: 0.12,  # Conservative: 12% of capacity per SEK/kWh weighted spread
      3: 0.10,  # Neutral:      10% of capacity per SEK/kWh weighted spread
      4: 0.05,  # Aggressive:    5% of capacity per SEK/kWh weighted spread
      5: 0.02,  # Gambler:       2% of capacity per SEK/kWh weighted spread
  }

  # Time-proximity decay for the price signal: weight(d) = 0.5 ** ((d - 1) / half_life).
  # Half-life 2 days matches the battery's realistic 1-2 day bridging horizon
  # (a spike counts fully at D+1, half at D+3, ~13% at D+7). See design Decision 2.
  PRICE_PROXIMITY_HALF_LIFE_DAYS: float = 2.0
  ```

- [x] 1.2 Create a new function `calculate_price_floor_addon()` in `planner/strategy/s_index.py`. Signature:
  ```python
  def calculate_price_floor_addon(
      upcoming_daily_avg_spots: dict[int, float],  # days-ahead (1..7) -> avg spot p50 (SEK/kWh)
      trailing_avg_spot: float | None,             # 14-day trailing avg (SEK/kWh)
      capacity_kwh: float,
      risk_appetite: int,
  ) -> tuple[float, dict[str, Any]]:
  ```
  Logic:
  1. If `upcoming_daily_avg_spots` is empty, return `(0.0, {"price_adjustment_active": False, "price_adjustment_reason": "insufficient_forecast_data"})`. If `trailing_avg_spot` is None or `<= 0`, return `(0.0, {"price_adjustment_active": False, "price_adjustment_reason": "insufficient_historical_data"})`. Distinct reasons let operators distinguish a broken forecast pipeline from a cold-start system.
  2. For each day offset `d` in `upcoming_daily_avg_spots`, compute the proximity weight `weight_d = 0.5 ** ((d - 1) / PRICE_PROXIMITY_HALF_LIFE_DAYS)` and the weighted spread `(avg_spot_d - trailing_avg_spot) * weight_d`.
  3. Pick the maximum weighted spread as `weighted_spread_sek`; the day offset that produced it is the **driving day**. Record that day's raw spread as `raw_spread_sek` and its weight as `proximity_weight`.
  4. Look up `risk_fraction = RISK_PRICE_KW_FRACTION.get(risk_appetite, 0.10)`.
  5. Compute `price_addon_kwh = capacity_kwh * weighted_spread_sek * risk_fraction`.
  6. Return `(price_addon_kwh, {"price_adjustment_active": True, "price_spread_sek": weighted_spread_sek, "raw_spread_sek": raw_spread_sek, "driving_day_offset": driving_day, "proximity_weight": proximity_weight, "peak_upcoming_spot_sek": upcoming_daily_avg_spots[driving_day], "trailing_avg_spot_sek": trailing_avg_spot, "price_addon_kwh": price_addon_kwh, "price_reserve_fraction": risk_fraction})`.

## 2. Safety Floor Integration (Two-Tier)

- [x] 2.1 Add two optional parameters to `calculate_safety_floor()` in `planner/strategy/s_index.py`:
  ```python
  upcoming_daily_avg_spots: dict[int, float] | None = None,  # days-ahead (1..7) -> avg spot p50
  trailing_avg_spot: float | None = None,
  ```
  These default to None so the existing call sites are fully backward-compatible. Do NOT add a `risk_appetite` parameter — the function already parses `risk_appetite` from `s_index_cfg` internally; reuse that value when calling `calculate_price_floor_addon()`.

- [x] 2.2 At the **end** of `calculate_safety_floor()`, after the existing `safety_floor_kwh` has been computed and capped at `min_soc_kwh + max_buffer_kwh` (Layer 1), add the Layer 2 price block. **The price addon is additive only — negative addons are clamped to zero effect so price never undercuts the deficit-based safety floor:**
  ```python
  # Layer 2: price floor addon (applied after existing 20% cap, additive only)
  if upcoming_daily_avg_spots is not None and trailing_avg_spot is not None:
      price_addon_kwh, price_debug = calculate_price_floor_addon(
          upcoming_daily_avg_spots, trailing_avg_spot, capacity_kwh, risk_appetite
      )
      # Asymmetric clamp: price can only RAISE the floor, never lower it.
      # Lower bound is safety_floor_kwh (Layer 1 result), not min_soc_kwh.
      final_floor_kwh = max(
          safety_floor_kwh,
          min(safety_floor_kwh + price_addon_kwh, 0.80 * capacity_kwh)
      )
      debug.update(price_debug)
      debug["price_addon_applied_kwh"] = final_floor_kwh - safety_floor_kwh
      debug["final_floor_kwh"] = final_floor_kwh
  else:
      final_floor_kwh = safety_floor_kwh
      debug["price_adjustment_active"] = False
      debug["price_adjustment_reason"] = "disabled_or_no_data"
  ```
  Return `final_floor_kwh` instead of `safety_floor_kwh`. Note: the *computed* `price_addon_kwh` may be negative (debug visibility), but the *effective* change to the floor is `max(0, price_addon_kwh)` after the clamp.

- [x] 2.3 After computing `price_addon_kwh`, add strategy event logging only when the floor is meaningfully raised (negative addons produce no event since they have no effect):
  ```python
  if price_addon_kwh >= 0.5:
      append_strategy_event(
          event_type="STRATEGY_CHANGE",
          message=(
              f"Price signal: {peak_upcoming_sek:.2f} SEK/kWh forecast in D+{driving_day} "
              f"({raw_spread_sek:+.2f} vs trailing avg, {weighted_spread_sek:+.2f} weighted) "
              f"→ floor raised by {price_addon_kwh:.1f} kWh"
          ),
          data={
              "price_spread_sek": weighted_spread_sek,
              "raw_spread_sek": raw_spread_sek,
              "driving_day_offset": driving_day,
              "price_addon_kwh": price_addon_kwh,
              "peak_upcoming_spot_sek": peak_upcoming_sek,
          },
      )
  ```

## 3. Pipeline Wiring

- [x] 3.1 In `planner/pipeline.py`, add a helper function (or inline, matching existing patterns) to fetch price data for the safety floor. The helper should:
  - Query `price_forecasts` table for `slot_start` in D+1 through D+7, grouping by date, returning `avg(spot_p50)` per day as `dict[int, float]` (days-ahead offset → avg SEK/kWh). Compute the offset as calendar days between the slot's local date and today's local date (timezone-aware), so the proximity weighting in `calculate_price_floor_addon()` receives correct distances.
  - Query `slot_observations` for the trailing 14-day average of `export_price_sek_kwh` where at least 2 distinct calendar days exist; return `float | None`.
  - Return both. Use the existing async DB access pattern (same as how Aurora data is fetched in the pipeline).

- [x] 3.2 In the strategy section of `planner/pipeline.py` (around the `calculate_safety_floor()` call), add:
  ```python
  upcoming_spots: dict[int, float] | None = None
  trailing_spot: float | None = None
  if active_config.get("price_forecast", {}).get("enabled", False):
      upcoming_spots, trailing_spot = await fetch_price_floor_inputs(sqlite_path)
  ```

- [x] 3.3 Pass the fetched data to `calculate_safety_floor()` (risk appetite is already parsed internally from `s_index_cfg` — no extra argument):
  ```python
  target_soc_kwh, soc_debug = calculate_safety_floor(
      df,
      active_config.get("battery", {}),
      s_index_cfg,
      timezone_name,
      fetch_temperature_fn=...,
      full_forecast_df=full_forecast_df,
      price_horizon_end=price_horizon_end,
      upcoming_daily_avg_spots=upcoming_spots,
      trailing_avg_spot=trailing_spot,
  )
  ```

## 4. Tests

- [x] 4.1 Create `tests/planner/strategy/test_s_index_price_awareness.py` with unit tests for `calculate_price_floor_addon()` (keys are days-ahead offsets):
  - **Rising prices at D+1 (full weight):** `upcoming = {1: 3.0}`, `trailing = 1.0`, `capacity = 10.0`, `risk = 3` → weight 1.0 → addon = `10.0 × 2.0 × 1.0 × 0.10 = 2.0 kWh`, debug active = True, `driving_day_offset = 1`.
  - **Proximity damping:** same spike at D+3 (`{3: 3.0}`) → weight 0.5 → addon = 1.0 kWh; at D+7 (`{7: 3.0}`) → weight 0.125 → addon = 0.25 kWh.
  - **Ramp as spike approaches:** identical +2.0 spread placed at D+6, D+4, D+2, D+1 → addons strictly increase (0.35 → 0.71 → 1.41 → 2.0 kWh approx).
  - **Weighted peak selection:** `upcoming = {1: 1.5, 5: 5.0}`, `trailing = 1.0` → D+1 weighted spread = 0.5, D+5 weighted spread = `4.0 × 0.25 = 1.0` → driving day = 5, addon uses weighted spread 1.0 (a huge far spike can still win, but heavily damped).
  - **Cheap period:** `upcoming = {1: 0.5}`, `trailing = 1.5`, `capacity = 10.0`, `risk = 3` → addon = `10.0 × -1.0 × 0.10 = -1.0 kWh` (weight 1.0 at D+1; negative spreads pick the least-negative weighted value).
  - **Insufficient forecast data:** empty `upcoming_daily_avg_spots` → `(0.0, {"price_adjustment_active": False, ...})`.
  - **Insufficient historical data:** `trailing_avg_spot = None` → `(0.0, {"price_adjustment_active": False, ...})`.
  - **Risk scaling:** same inputs at risk 1 (0.15) vs risk 5 (0.02) produce proportionally different addons.

- [x] 4.2 Add integration tests for `calculate_safety_floor()` with price data in the same file:
  - **Two-tier floor increase:** pass price data with positive spread → `final_floor > safety_floor_kwh` (before price addon).
  - **Cheap-period asymmetry (Option B):** pass price data with negative spread → `final_floor == safety_floor_kwh` (negative addon clamped to zero effect). The computed `price_addon_kwh` in debug SHALL still reflect the negative value for observability, but `price_addon_applied_kwh` SHALL be 0.
  - **80% cap enforced:** construct scenario where addon would push floor above 80% capacity → clamped at 80%.
  - **safety_floor preserved on extreme negative addon:** very large negative spread → `final_floor == safety_floor_kwh` (never below). Verify result is *not* clamped to `min_soc_kwh`.
  - **Backward compatibility:** call `calculate_safety_floor()` with no price params → result identical to pre-change behavior.
  - **Disabled (no params):** `upcoming_daily_avg_spots=None` → `price_adjustment_active = False` in debug, no floor change.
  - **No strategy log on negative addon:** integration test verifies `append_strategy_event` is *not* called when spread is negative (since negative addons have no effective floor change).

- [x] 4.3 Verify existing S-Index tests in `tests/planner/test_safety_floor_temporal.py` and `tests/planner/strategy/test_s_index_new.py` still pass without modification.
