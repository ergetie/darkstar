## Context

The Temporal Safety Floor (`planner/strategy/s_index.py::calculate_safety_floor`) is designed to reserve battery for energy deficits that fall **beyond** the Nordpool price horizon, by integrating slot-level load/PV forecasts over a 24h look-ahead window that starts where the price data ends. The `planner` spec already requires this behavior.

In production it never engages. Every plan logs `Temporal Safety Floor: Extended forecast data unavailable or insufficient, using available horizon only` and falls back to the available (price-bounded) horizon. Verified data flow:

- `backend/core/forecasts.py::_get_forecast_data_aurora()` builds the `"slots"` list **strictly for the price horizon** (loop over `price_slots`, ~2 days). It *does* fetch the extended slot-level forecasts at `get_forecast_slots(start_dt, end_dt, ...)` (`forecasts.py:267`, horizon ≥ 4 days) — but only to accumulate **daily aggregate** dicts (`daily_pv_forecast`, `daily_load_forecast`). The extended slot-level rows are discarded; the returned `"slots"` covers only the price horizon.
- `planner/pipeline.py:445-447` builds `full_forecast_df` from `input_data["forecast_data"]` — the price-horizon-only slots.
- `calculate_safety_floor()` masks `full_forecast_df` to `(index > price_horizon_end) & (index <= price_horizon_end + 24h)`. That window is always empty because the dataframe ends at the price horizon → `using_extended_data = False` → fallback warning.

So the look-ahead data exists in the DB (`slot_forecasts`, ~7 days ahead) and is even fetched into memory — it is simply collapsed to daily totals before it can reach the calculation.

Impact today: harmless (summer temporal deficit ≈ 0). Impact in winter: the safety floor cannot see the night/next-day deficit beyond the price horizon, so it under-reserves battery before cold, dark stretches — the exact case the feature exists for.

## Goals / Non-Goals

**Goals:**
- Provide `calculate_safety_floor()` with slot-level load/PV forecasts that extend ≥ 24h beyond the price horizon, when those slots exist in the forecast store.
- Keep the existing fallback-and-warn behavior for the genuinely-absent case.
- Stop the spurious per-plan warning on healthy systems.

**Non-Goals:**
- No change to the Kepler/MILP planning horizon — the solver stays intentionally bounded by the price horizon. This change only feeds the safety-floor *reservation* calculation, not the optimization window.
- No DB schema change; no change to how forecasts are generated or persisted.
- Not fixing the daily-aggregate path (`daily_pv_forecast` etc.) — it stays as-is for whatever else consumes it.

## Decisions

**Decision 1 — Emit extended slot-level forecasts from the forecast-data builder, alongside the existing daily aggregates.**
In `_get_forecast_data_aurora()`, the loop at `forecasts.py:269` already iterates every `extended_records` row to build daily totals. Extend that same loop to also append a slot-level entry (`start_time`, `pv_forecast_kwh`, `load_forecast_kwh`, and `pv_p10/pv_p90/load_p10/load_p90` where available) to a new list, returned under a new key such as `"extended_slots"`. No extra DB query — reuses the rows already fetched at `forecasts.py:267`.
- *Alternative considered:* widen the price-horizon `"slots"` list to the full horizon. Rejected — `"slots"` is consumed by the price-bounded planning path (zipped against `price_slots`); lengthening it risks changing solver inputs. Keeping a separate `"extended_slots"` key isolates the safety-floor concern.
- *Alternative considered:* reconstruct slot data from the daily aggregates. Rejected — lossy; the safety floor needs per-slot `max(0, load - pv)`, which daily totals cannot reproduce.

**Decision 2 — Build `full_forecast_df` from the extended slots in the pipeline.**
In `planner/pipeline.py`, build `full_forecast_df` from `input_data["extended_forecast_data"]` (the new key threaded through from the forecast builder). If that key is missing/empty, fall back to the current `forecast_data` slots so behavior degrades exactly as today. `calculate_safety_floor()` needs no signature change — it already accepts `full_forecast_df` and `price_horizon_end`.

**Decision 3 — Thread the new key through `input_data`.**
The unpack site is `backend/core/forecasts.py:653-669` (the planner-input builder): `get_forecast_data()` is called at line 653, its `"slots"` is extracted to `forecast_data` at line 654, and the planner-input dict is returned at lines 661-669 (mapping `forecast_data`, `daily_pv_forecast`, `daily_load_forecast`, `daily_probabilistic`). Add a sibling extraction `extended_forecast_data = forecast_result.get("extended_slots", [])` after line 654 and add `"extended_forecast_data": extended_forecast_data` to the returned dict. Keep naming consistent with existing keys.

**Decision 4 — "Unavailable" means genuinely absent.**
The fallback warning should fire only when the forecast store has no slots in the look-ahead window (forecast outage, fresh deployment). This is naturally satisfied once Decisions 1–2 supply the data: when `slot_forecasts` has the rows, the window is populated and no warning fires.

**Decision 5 — Non-Aurora forecast paths are out of scope.**
Only the Aurora path (`_get_forecast_data_aurora`) emits `extended_slots`. The active production forecast version is Aurora, so this covers the live system. Other paths (e.g. Open-Meteo) simply hit the pipeline fallback (Decision 2) and behave exactly as today. Extending those paths is explicitly deferred; this is a settled decision, not a blocker.

## Risks / Trade-offs

- **[Other forecast paths]** Non-Aurora builders (e.g. the Open-Meteo path) may not emit `extended_slots`. → The pipeline fallback (Decision 2) preserves today's behavior for those paths; emitting extended slots there can be a follow-up. The active production path is Aurora, which this change covers.
- **[Timezone / index alignment]** The extended loop already normalizes `slot_start` to tz-aware and localizes for indexing; the new slot list must carry tz-aware `start_time` so `build_forecast_dataframe` indexes it consistently with the price-horizon slots. → Mirror the existing normalization used for the daily loop.
- **[Behavior change in winter]** Floors will rise on short-horizon winter days (the intended effect), which changes dispatch. → Covered by spec scenarios; validate against a winter day in testing and confirm `max_safety_buffer_pct` still caps it.
- **[Double-counting the boundary]** The look-ahead mask is `index > price_horizon_end`, so the price-horizon slots and extended slots must not overlap-double-count at the boundary. → The mask is strictly greater-than; ensure extended slots use the same slot timestamps so the boundary slot isn't both ends.

## Migration Plan

- Pure code change; deploy with the normal image build. No migration step.
- Rollback: revert the commit — the pipeline fallback means the system returns to logging the warning and using the available horizon, with no data left in an inconsistent state.
