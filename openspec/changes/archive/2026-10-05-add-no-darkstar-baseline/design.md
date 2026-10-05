## Context

`GET /api/energy/cost-series` reads started `slot_observations` rows (15-minute slots) for the period and returns per-bucket import cost, export revenue and a running net. `GET /api/energy/range` returns the period totals (computed in SQL) that feed the Grid & Financial card.

Facts verified on the production database (2026-10-07):

- Complete 96-slot days since 2025-11. Import, export, PV, load, water, EV, battery charge/discharge, SoC end and both prices are recorded.
- The slot energy balance closes: `import + pv + discharge = export + load + water + ev + charge`. With the battery idle the residual averages 0.006 kWh/slot, and in charging slots the residual equals the recorded battery charge. The battery columns are therefore already on the AC side.
- `load_kwh` is base load only; EV and water are subtracted by the recorder (`backend/recorder.py:199`). Household demand is `load + water + ev`.
- `soc_start_percent` is never populated; `soc_end_percent` is, with gaps (about 4% of recent slots).
- `import_price_sek_kwh` includes fees and VAT; `export_price_sek_kwh` is pure spot. Both are used as-is by the real figures, so the baseline uses the same columns.
- Battery wear is `(charge_kwh + discharge_kwh) × battery_cycle_cost_kwh × 0.5` (`energy.py`).
- The planner reads `battery.charge_efficiency` and `battery.discharge_efficiency` with a 0.95 default for each (`planner/pipeline.py:930`). Production config sets only `charge_efficiency`.

## Goals / Non-Goals

**Goals:**
- A "without Darkstar" net cost for any period the card can show, from the same recorded slots and prices as the real figures.
- A saving figure that credits Darkstar only for what its scheduling adds, so the baseline keeps the battery and models what the inverter does by default.
- One source for card and chart (the cost-series response).

**Non-Goals:**
- Modelling a user's own time-of-use schedule, or any price-aware baseline.
- Re-timing EV charging or water heating in the baseline.
- Changing `/api/energy/range`, the headline Net, or any stored data.
- Storing the baseline. It is computed per request from recorded slots.

## Decisions

**1. Baseline is a plain self-use inverter.** Per slot, demand = `load + water + ev`, surplus = `pv − demand`.
- Surplus ≥ 0: charge the battery from the surplus up to the room left below `max_soc_percent` and up to `max_charge_w`; export the rest.
- Surplus < 0: discharge the battery to cover the deficit down to `min_soc_percent` and up to `max_discharge_w`; import the rest.
- No grid charging and no export from the battery.
- Alternatives: *no battery at all* (credits the hardware to Darkstar, rejected); *fixed time-of-use schedule* (varies per household, cannot be modelled).

**2. Battery accounting.** Recorded battery flows are AC-side, so the simulated AC charge `c` raises stored energy by `c × charge_efficiency` and a discharge `d` lowers it by `d ÷ discharge_efficiency`. Efficiencies come from `battery.charge_efficiency` / `battery.discharge_efficiency` with the planner's 0.95 defaults. Power limits are `max_charge_w` / `max_discharge_w` × 0.25 h per slot. Capacity is `battery.capacity_kwh`.

**3. Starting state.** The simulation starts from the real SoC at the start of the period: the `soc_end_percent` of the slot before the first slot of the period, else the first non-null `soc_end_percent` in the period, else `min_soc_percent`. After the start the simulated SoC is carried forward and never re-synced to the real SoC (the real SoC reflects Darkstar's decisions). A missing slot row is skipped and the simulated SoC carries over.

**4. Pure module, called from the endpoint.** `backend/baseline.py` holds a pure function over a time-ordered list of slot inputs and a battery parameter object, returning per-slot simulated import/export/charge/discharge kWh. It has no I/O so it is unit-testable. The cost-series endpoint reads the extra columns (`pv_kwh`, `load_kwh`, `water_kwh`, `ev_charging_kwh`, `batt_charge_kwh`, `batt_discharge_kwh`, `soc_end_percent`) and prices the result with the slot prices, bucketing with the existing local-hour/local-day key. Slots are sorted by parsed datetime, not by string, so DST changes order correctly.
- Alternative: compute in SQL like `/range` — rejected, each slot depends on the previous SoC.

**5. What the response carries.**
- Per point: `baseline_cumulative_net_cost_sek` (grid cash flow only, same basis as `cumulative_net_cost_sek` so the two chart lines are comparable).
- Top level `baseline`: `net_cost_sek`, `battery_wear_cost_sek`, `net_cost_incl_wear_sek`, `saving_incl_wear_sek`, `stored_energy_difference_kwh` and `stored_energy_value_sek`, where saving = baseline net incl. wear − (actual net + actual wear) + stored-energy value (decision 7). Actual wear uses the same formula as `/range`. The saving includes wear on both sides and the stored-energy value; the chart lines exclude both. The card makes this clear in the tooltip.
- `baseline` is `null` and per-point fields are omitted when `system.has_battery` is false, or when the period has no slots.

**6. Frontend.** The card shows one extra line below the net-incl-wear line: "Without Darkstar −X kr" and the saving. The saving is green when ≥ 0 and muted when negative (Darkstar cost more in the period). Hidden when `baseline` is null. The chart adds a dashed muted line, a legend entry "no Darkstar", the baseline total in the hover readout, and includes the baseline values in the vertical scaling in `computeCostChartGeometry`. All colours are design-system tokens (`docs/design-system/AI_GUIDELINES.md`, `frontend/src/index.css`).

**7. The saving values the energy left in the battery.** Comparing only cash flow ignores that the two batteries end the period at different charge: on 2026-10-04 production data the baseline battery ended empty (about 15 %) while the real one ended at 32 %, about 4.6 kWh more stored (about 12 kr at the day's average import price of 2.54 kr/kWh). Without crediting that, the card said Darkstar cost 3.55 kr more although it was ahead. Over long periods the effect is small, on single days it decides the verdict.
- `stored_energy_difference_kwh` = real end stored energy − simulated end stored energy, each `soc_percent / 100 × capacity_kwh`. Real end SoC is the last non-null `soc_end_percent` of the period's started slots; simulated end SoC is the simulation's final state, exposed by `simulate_self_use_with_end_state` (`simulate_self_use` keeps returning only the flows).
- `stored_energy_value_sek` = difference × simple mean of `import_price_sek_kwh` over the started slots that have a price (0 if none) × `battery.discharge_efficiency` (default 0.95). Positive when the real battery holds more.
- If no real end SoC exists both fields are `null` and count as 0 in the saving. The per-point cumulatives stay pure cash flow. The "Without Darkstar" tooltip states the amount in plain language.
- Alternatives: *value at the export price* or *at the period's last price* (rejected: the user chose the average import price, which is what the stored energy displaces).

**8. Chart header layout.** The legend with "no Darkstar" is too long to share a line with the heading at card width (about 320-360 px). The heading is `whitespace-nowrap` on its own row, the legend (or hover readout) sits on a second row with `flex-wrap`, and each legend entry is `whitespace-nowrap`. The fixed `h-4` header becomes one `h-4` heading row plus a `min-h-4` second row; the chart area is `flex-1` and absorbs the difference.

## Risks / Trade-offs

- [EV and water are replayed at their real hours] → the saving is conservative; the tooltip says so.
- [Wear and stored-energy value are in the saving but not in the chart lines] → the saving can differ from the visible gap between the lines; the tooltip states that the saving includes battery wear and the energy left in the battery.
- [Stored-energy value uses the period's mean import price] → an approximation of what the energy is worth; on long periods the term is small.
- [Hover readout can wrap to two lines at card width] → the second header row is `min-h-4`, so the chart area shrinks by one line while hovering.
- [Config missing `discharge_efficiency`] → the planner's 0.95 default is used, same as the planner.
- [Recorded `load_kwh` of the first slots after an outage may be zero] → the baseline sees the same inputs as the real figures; no special handling.
- [30-day periods simulate about 2,900 slots per request] → trivial cost (a loop of simple arithmetic), no caching needed.
- [Baseline wear uses simulated AC flows] → consistent with how actual wear uses recorded AC flows.

## Open Questions

None.
