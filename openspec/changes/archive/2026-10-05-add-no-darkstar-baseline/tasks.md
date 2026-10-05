## 1. Baseline simulation

- [x] 1.1 Add `backend/baseline.py` with a pure function that takes chronologically ordered slot inputs (pv, load, water, ev, soc_end) and battery parameters (capacity, min/max SoC, max charge/discharge W, charge/discharge efficiency) and returns per-slot simulated import, export, charge and discharge kWh, following the self-use rules and starting-SoC rules in the `no-darkstar-baseline` spec
- [x] 1.2 Add `tests/backend/test_baseline.py` covering: surplus charges first, surplus beyond room/limit exported, deficit covered then imported, empty battery imports, no grid charging, no battery export, efficiency applied, default 0.95 efficiencies, start SoC (previous slot, first in period, fallback to min), skipped slot leaves SoC unchanged, SoC never re-synced to recorded values

## 2. Cost-series endpoint

- [x] 2.1 In `get_cost_series` (`backend/api/routers/energy.py`) also select `pv_kwh`, `load_kwh`, `water_kwh`, `ev_charging_kwh`, `batt_charge_kwh`, `batt_discharge_kwh`, `soc_end_percent`, and the `soc_end_percent` of the slot just before the period for the starting SoC
- [x] 2.2 Read battery parameters from config; skip the baseline when `system.has_battery` is false or there are no started slots; sort slots by parsed datetime
- [x] 2.3 Price the simulated flows with the slot prices, bucket them with the existing local-hour/local-day key, and add `baseline_cumulative_net_cost_sek` to each point
- [x] 2.4 Add the top-level `baseline` object (`net_cost_sek`, `battery_wear_cost_sek`, `net_cost_incl_wear_sek`, `saving_incl_wear_sek`) using the `/range` wear formula for the real side; `null` when unavailable
- [x] 2.5 Extend `tests/api/test_energy_cost_series.py`: fields present with a battery, last cumulative equals `baseline.net_cost_sek`, saving matches the definition, `null` without battery, existing fields identical, DST day ordering, future slots excluded from the baseline

## 3. Frontend types and chart

- [x] 3.1 Add `baseline_cumulative_net_cost_sek?` to `CostSeriesPoint` and a `baseline` object (or `null`) to `CostSeriesResponse` in `frontend/src/lib/api.ts`
- [x] 3.2 In `computeCostChartGeometry` add the baseline line (same x positions as the net line, starting at zero) and include its values in the vertical scale; no change when the field is absent
- [x] 3.3 In `CostSeriesChart.tsx` draw the baseline as a dashed muted line (design-system tokens, non-scaling stroke), add the "no Darkstar" legend entry and the baseline total in the hover readout, and honour reduced motion
- [x] 3.4 Extend `CostSeriesChart.geometry.test.ts`: baseline line positions, range covers the baseline maximum, unchanged output without baseline

## 4. Card

- [x] 4.1 In `CommandDomains.tsx` render the "Without Darkstar" line below the net-incl-wear line from `costSeries.baseline`: baseline net, saving in the good colour when ≥ 0, "Darkstar cost more" in a muted colour when negative, hidden when `baseline` is null
- [x] 4.2 Add the hover explanation (plain self-use inverter with the same battery, saving includes battery wear, EV and water counted at real hours so the saving is conservative)
- [x] 4.3 Extend `CommandDomains.test.tsx`: line shown with a positive saving, negative saving wording, hidden without a baseline, headline Net unchanged

## 5. Verification

- [x] 5.1 Run `./scripts/lint.sh` and the affected backend and frontend tests; fix any failures
- [x] 5.2 Check the card and chart in `pnpm run dev` for Today, 7d and a no-battery configuration against the design system
- [x] 5.3 Compare the baseline net for a past day on production data (read-only) with a hand calculation of the same slots to confirm the simulation

## 6. Follow-up: value the energy left in the battery

- [x] 6.1 Expose the simulation's final state of charge from `backend/baseline.py` (`simulate_self_use_with_end_state`) without changing `simulate_self_use`; test it
- [x] 6.2 In `get_cost_series` compute `stored_energy_difference_kwh` and `stored_energy_value_sek` (real last non-null `soc_end_percent`, mean import price, discharge efficiency), add them to `baseline` and into `saving_incl_wear_sek`; chart cumulatives unchanged
- [x] 6.3 Extend `tests/api/test_energy_cost_series.py`: positive and negative difference, missing real SoC, missing prices, discharge-efficiency default, saving formula, chart lines unchanged
- [x] 6.4 Add the two fields to `CostSeriesBaseline` in `api.ts` and the plain-language sentence to the "Without Darkstar" tooltip in `CommandDomains.tsx`; extend `CommandDomains.test.tsx` (more, less, unknown)

## 7. Follow-up: chart header layout

- [x] 7.1 In `CostSeriesChart.tsx` keep the heading on one line, put the legend/hover readout on its own wrapping row below it, keep legend entries unbroken
- [x] 7.2 Add `CostSeriesChart.test.tsx` for the header structure and the hover readout replacing the legend
