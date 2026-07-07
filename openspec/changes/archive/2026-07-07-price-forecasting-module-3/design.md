## Context

The S-Index module (`planner/strategy/s_index.py`) currently has three main functions that influence battery strategy:

1. **`calculate_probabilistic_s_index()`** / **`calculate_dynamic_s_index()`** — Computes a load inflation factor based on PV/load uncertainty (sigma scaling) or PV deficit + temperature. This factor makes Kepler reserve more battery capacity during uncertain conditions.

2. **`calculate_safety_floor()`** (Rev K23 Physical Deficit Logic) — Computes the minimum battery kWh floor based on temporal deficit (per-slot `max(0, load - pv)` sum) over a 24h look-ahead window beyond the price horizon. This is the primary mechanism that prevents the battery from being fully drained.

3. **`calculate_target_soc_risk_factor()`** — Legacy risk factor for target SOC, still used for debug output but largely superseded by the safety floor.

The pipeline (`planner/pipeline.py` lines 342-437) orchestrates these: it calls the S-Index for load inflation, then calls `calculate_safety_floor()` for the min-SOC constraint, then passes both to Kepler.

**Important constraint:** `calculate_safety_floor()` caps its output at `min_soc_kwh + max_safety_buffer_pct × capacity_kwh` (default 20% of capacity). On days with moderate-to-high deficit, most users already hit this cap, meaning the existing base floor is typically `min_soc + 20% capacity`. Any price adjustment that modifies values *inside* this cap would be silently discarded. The price addon (Layer 2 below) is therefore applied *after* the cap, not before.

**Kepler penalty:** The safety floor is passed to Kepler as `target_soc_kwh` with a `target_soc_penalty_sek = 200.0 SEK/kWh` for all risk levels. Since real electricity prices rarely exceed 5–15 SEK/kWh, this penalty is effectively a hard constraint — Kepler will always import from grid if needed to reach the floor.

Module 1 (price-forecasting-core) delivers a `price_forecasts` DB table and `GET /api/price-forecast` endpoint with per-slot p10/p50/p90 spot price predictions for D+1 through D+7. Module 2 (price-forecast-advisor-outlook) adds a `GET /api/price-forecast/outlook` endpoint with daily summaries including `level` (cheap/normal/expensive) and `avg_spot_p50`.

## Goals / Non-Goals

**Goals:**
- Allow the safety floor to decrease when cheap recharge periods are forecasted ahead (drain battery now, recharge cheaply later)
- Allow the safety floor to increase when expensive periods are forecasted ahead (stockpile energy before prices rise)
- Produce meaningful, battery-capacity-proportional adjustments regardless of battery size or current temporal deficit
- Scale price sensitivity with risk appetite — cautious users hoard more aggressively, gamblers barely react
- Maintain full backward compatibility when `price_forecast.enabled` is false or data is unavailable
- Provide clear debug output for all price-based adjustments

**Non-Goals:**
- Changing the Kepler solver's objective function or price inputs (it stays on real Nordpool prices)
- Building the price forecast model or API (Module 1)
- Modifying the advisor or UI (Module 2)
- Adding price awareness to EV charging decisions (Module 4)
- Replacing existing PV/load-based S-Index logic — price is an *additional* signal, not a replacement
- Exposing per-risk-level fraction tuning in user config (internal constants only)

## Decisions

### 1. Price adjustment applied to the safety floor, not to load inflation

**Choice:** The price signal modifies `calculate_safety_floor()` output, rather than adjusting the load inflation factor from `calculate_probabilistic_s_index()`.

**Why:** The safety floor directly controls how much energy the battery holds as a terminal SOC target for Kepler. It is the right lever for "stockpile before expensive period" or "drain before cheap period". Load inflation is about uncertainty margins on PV/load forecasts — conceptually different from price-driven strategy. Mixing price signals into load inflation would make both harder to debug.

**Alternative considered:** Adding a price component to the sigma scaling in `calculate_probabilistic_s_index()`. Rejected because sigma scaling is designed around PV/load uncertainty bounds, and adding price would conflate two different risk types.

### 2. Price signal: absolute spread (SEK/kWh), proximity-weighted, not ratio

**Choice:** For each forecast day D+1 through D+7, compute that day's spread against the trailing average — `spread_d = avg_spot_p50_d - trailing_14day_avg_spot`, both in SEK/kWh — then scale it by a **time-proximity weight** that decays exponentially with distance (half-life: 2 days). The price signal is the **maximum weighted spread** across the seven days. The "trailing" reference is the 14-day historical average from `slot_observations.export_price_sek_kwh`.

**Why:** A ratio-based signal (`upcoming / trailing`) breaks at low absolute prices. A jump from 0.10 to 0.50 SEK/kWh is a 400% ratio spike but both prices are practically free — the system should barely react. A jump from 1.00 to 6.00 SEK/kWh is a 500% ratio but represents enormous real economic opportunity — the system should react strongly. Absolute spread in SEK/kWh correctly distinguishes these cases. Both price values are pure Nordpool spot prices (no grid fees or VAT), making the comparison unit-consistent.

**Note on field naming:** the historical column `slot_observations.export_price_sek_kwh` *is* the raw Nordpool spot price despite the misleading name. Only the *import* price has VAT and grid fees added in this codebase; the export price is stored as pure spot. Comparing forecast `spot_p50` to trailing `export_price_sek_kwh` is therefore a valid apples-to-apples comparison, no normalisation required.

**Why peak, not average:** A single very expensive day in an otherwise normal week creates real economic incentive to stockpile. Averaging D+1-D+7 dilutes this signal. Taking the maximum (weighted) daily spread captures the worst upcoming day and is what the system is economically hedging against.

**Why proximity-weighted:** The battery realistically bridges 1–2 days of load — it will never "hold" energy for 7 days. An expensive day at D+7 does not justify hoarding today: doing so sacrifices daily arbitrage flexibility for days with no benefit, and D+5–D+7 forecasts are the least accurate. The exponential decay (half-life 2 days) matches the battery's realistic bridging horizon: a spike counts fully when 1 day away, half at D+3, and ~13% at D+7. A useful emergent behavior: as an expensive day approaches, its weight grows each day, so the floor **ramps up gradually** — the battery fills over several cheap nights instead of hoarding a full week early.

**Proximity weight table** (`weight(d) = 0.5^((d−1)/2)`, `PRICE_PROXIMITY_HALF_LIFE_DAYS = 2.0`):

| Days ahead | D+1 | D+2 | D+3 | D+4 | D+5 | D+6 | D+7 |
|---|---|---|---|---|---|---|---|
| Weight | 1.00 | 0.71 | 0.50 | 0.35 | 0.25 | 0.18 | 0.13 |

**Formula:**
```
spread_d            = avg_spot_p50_d - trailing_14day_avg_sek     (for d = 1..7)
weight(d)           = 0.5^((d − 1) / 2)
weighted_spread_sek = max(spread_d × weight(d), for d = 1..7)
```

The day that produces the maximum is the **driving day** (recorded in debug output). Positive weighted spread → expensive period near enough to matter → increase floor. Negative weighted spread → cheap period ahead → no effect (see Decision 3).

### 3. Two-tier architecture: price addon applied after the existing 20% cap, asymmetric (additive only)

**Choice:** The price addon is computed separately from the existing safety floor and added to it *after* the `max_safety_buffer_pct` cap is applied. The final result is bounded at 80% of battery capacity on the upper end, and at the existing `safety_floor_kwh` on the lower end — meaning **the price signal can only raise the floor, never lower it**.

```
Layer 1 (existing, unchanged):
  safety_floor_kwh = min(raw_floor, min_soc_kwh + 0.20 × capacity_kwh)

Layer 2 (new, price signal — additive only, proximity-weighted):
  RISK_PRICE_KW_FRACTION = {1: 0.15, 2: 0.12, 3: 0.10, 4: 0.05, 5: 0.02}
  risk_fraction       = RISK_PRICE_KW_FRACTION[risk_appetite]
  weighted_spread_sek = max(spread_d × 0.5^((d−1)/2), for d = 1..7)   # Decision 2
  price_addon_kwh     = capacity_kwh × weighted_spread_sek × risk_fraction

  final_floor_kwh   = clamp(
                        safety_floor_kwh + price_addon_kwh,
                        min = safety_floor_kwh,        # negative addons have no effect
                        max = 0.80 × capacity_kwh
                      )
```

**Why two tiers:** The existing 20% cap bounds the weather/deficit-based reserve. If the price addon were applied *inside* the cap (modifying `base_reserve_kwh`), it would be silently discarded on most days when the cap is already binding. Placing it outside the cap ensures it always has effect.

**Why asymmetric (additive only):** The "safety floor" exists for *physical* safety — it is sized so the battery does not run out during a real PV/load deficit overnight. Allowing a cheap-week price signal to lower this floor would let price optimization undercut the deficit-based reserve, which contradicts the non-goal "price is an *additional* signal, not a replacement". Cheap-period exploitation is already handled implicitly: when upcoming prices are cheap, Kepler sees them in its real Nordpool input and will plan to drain to the floor and recharge cheaply on its own. We do not need to relax the floor to enable that behavior. The negative addon is therefore computed (for debug visibility) but clamped to zero effect.

**Why 80% upper bound:** Leaves at least 20% headroom for intraday PV charging and normal load cycling. Prevents Kepler from being forced to fill the battery to near-100%, which would block PV absorption. The 80% bound is only reached in extreme price scenarios (e.g., 5+ SEK/kWh spread at Risk 1).

**Why capacity-proportional:** `capacity_kwh × spread × fraction` scales correctly for any battery size. A 10 kWh home battery and a 100 kWh commercial system both get appropriate adjustments without requiring size-specific config.

**Concrete examples (risk 3, fraction 0.10):**

| Scenario | Raw spread | Weight | Weighted spread | Computed addon | Effective change |
|---|---|---|---|---|---|
| Normal week | 0.0 SEK | — | 0.0 | 0 kWh | none |
| +1.5 SEK/kWh spike at D+1 | +1.5 | 1.00 | +1.50 | +capacity×0.15 | applied |
| +1.5 SEK/kWh spike at D+6 | +1.5 | 0.18 | +0.27 | +capacity×0.027 | applied (small — spike is far out) |
| +5.0 SEK/kWh spike at D+1 | +5.0 | 1.00 | +5.00 | +capacity×0.50 | applied (clamped at 80% capacity) |
| +5.0 SEK/kWh spike at D+7 | +5.0 | 0.13 | +0.63 | +capacity×0.063 | applied (ramps up as the day nears) |
| Cheap week ahead | −0.8 SEK | 1.00 (D+1) | −0.80 | −capacity×0.08 | **clamped to zero — floor unchanged** |

### 4. Risk-level scaling via internal constant table

**Choice:** `RISK_PRICE_KW_FRACTION` is a hardcoded dict in `s_index.py`. No user-facing config param is added.

**Why:** Risk appetite already expresses the user's conservatism preference. Tying price hoarding aggressiveness to risk level is intuitive — a Risk 1 (Safety) user should hoard more aggressively (fraction 0.15) than a Risk 5 (Gambler) who barely reacts (fraction 0.02). Exposing a separate config knob would let users inadvertently contradict their own risk settings. The fractions can be tuned in a future change if real-world usage reveals they need adjustment.

**Risk fraction table:**

| Risk | Fraction | Meaning: addon per 1 SEK/kWh spread |
|---|---|---|
| 1 Safety | 0.15 | 15% of capacity per SEK/kWh |
| 2 Conservative | 0.12 | 12% of capacity per SEK/kWh |
| 3 Neutral | 0.10 | 10% of capacity per SEK/kWh |
| 4 Aggressive | 0.05 | 5% of capacity per SEK/kWh |
| 5 Gambler | 0.02 | 2% of capacity per SEK/kWh |

### 5. Fetch price forecast data in the pipeline and pass to safety floor function

**Choice:** The pipeline (`planner/pipeline.py`) fetches price forecast data and passes it as optional parameters to `calculate_safety_floor()`. The S-Index functions remain pure calculation functions with no DB access.

**Why:** Consistent with how PV/load forecast data and temperature data are already passed to S-Index functions. Keeps the strategy module testable (pass mock data in tests). The pipeline is already the orchestration layer that gathers inputs.

**Data fetched** (by a new self-contained helper, `fetch_price_floor_inputs()` — the existing Aurora forecast retrieval is not touched):
- Daily average `spot_p50` per day from `price_forecasts` table (D+1 through D+7), keyed by days-ahead offset (int) so the proximity weighting receives correct distances
- 14-day trailing average `export_price_sek_kwh` from `slot_observations`

### 6. Use daily p50 averages from price forecasts

**Choice:** The price signal uses daily average spot p50 values, not per-slot granularity or p10/p90.

**Why:** The S-Index operates at a daily strategic level (safety floor for the next 24h). Per-slot price variation within a day is Kepler's domain. P50 (median) is the right central estimate for planning. P90 would over-react to tail scenarios; p10 would under-react. Daily averages also match the Module 2 Weekly Outlook widget that users see, making system behavior predictable.

### 7. Log strategy events for significant price-driven floor changes

**Choice:** Log a strategy event via `append_strategy_event()` when `abs(price_addon_kwh) >= 0.5 kWh`.

**Why:** Observability. Users and developers can see in the strategy log why the safety floor was higher or lower than usual. The 0.5 kWh threshold avoids noise from tiny adjustments. Matches the existing pattern where vacation mode and other strategy decisions are logged.

## Risks / Trade-offs

- **[Sustained expensive periods]** → If prices are elevated for many days, the trailing 14-day average slowly rises to match, narrowing the spread and reducing the floor over time. This is correct long-run behavior: the system gradually normalises to the new price level. The 14-day lag is a feature, not a bug — it prevents permanent high floors if prices never come back down. During the first ~7 days of a sustained spike, the floor will be elevated and Kepler may import at "expensive" prices to maintain it. This is an acceptable trade-off: the user is storing energy that avoids even-more-expensive future imports.
- **[Cold start — no price forecasts yet]** → When `price_forecast.enabled` is false or no forecast data exists, `price_addon_kwh = 0.0` and the final floor equals the existing safety floor. Zero risk of regression.
- **[Interaction with risk_appetite]** → Risk appetite already controls the base safety floor via `RISK_CONFIG` margins and min_buffer_pct in Layer 1. The price addon (Layer 2) also scales with risk_appetite via `RISK_PRICE_KW_FRACTION`. A Risk 5 (Gambler) user gets a fraction of 0.02 — almost no price hoarding. A Risk 1 (Safety) user gets 0.15 — aggressive. These stack correctly.
- **[Price forecast accuracy for D+5-D+7]** → A single inaccurate far-future day could inflate the signal. Mitigation: the proximity weighting (Decision 2) damps far-out days heavily — D+5/D+6/D+7 count at only 25%/18%/13% — so a phantom spike a week out barely moves the floor, and its influence grows only if the forecast keeps predicting it as the day approaches. The 80% capacity upper bound additionally prevents runaway floors, and the trailing average as reference dampens single-day spikes far from historical norms.
- **[Trailing average unavailable for new systems]** → If fewer than 2 days of historical prices exist, return `price_addon_kwh = 0.0`. Same pattern as Module 2's reference average fallback.
- **[Risk fractions are initial estimates, not calibrated]** → The values in `RISK_PRICE_KW_FRACTION` (0.02 → 0.15) were chosen by reasoning about reasonable behavior, not measured against real Swedish price history. They could be too aggressive, too timid, or roughly right — we will not know until 2–4 weeks of production observation. Plan: revisit these constants after a meaningful sample of real spread events (see `docs/BACKLOG.md`). Until then, treat them as v1 defaults, not validated tuning.
