## Context

The current self-use simulation treats PV and battery flows as AC-side energy. Installation sensors do not necessarily share that boundary. `get_cost_series` prices real gross import/export but simulated net flows, and the UI compares grid-only lines with savings including wear and stored energy.

Read-only checks of the local Fronius recordings (6 September–6 October 2026) found 19.07 kWh of within-slot import/export overlap costing 32.19 kr. An inverter model fitted on the first 80% of slots gave output efficiency 0.948 and input efficiency 1.0; withheld grid-energy RMSE was 0.187 kWh/slot and withheld net-cost error was 9.42 kr, about 3.9% of gross billing volume. Consecutive SoC pairs fitted battery charge/discharge factors 0.974/1.0 with withheld RMSE 0.143 kWh. These are evidence of feasibility, not constants to ship or proof of exact savings. The earlier Deye investigation is supporting evidence; its snapshot is not in the persistent investigation directory.

Stable self-use slots without EV consumption and with usable battery charge still imported 3.59 kWh across 1,085 slots. This does not identify a universal response penalty: transitions, power limits, measurement noise and within-slot demand changes cannot be reconstructed from totals. The UI must call this an estimate.

## Goals / Non-Goals

**Goals:** Compare battery actions under shared assumptions; preserve genuine metered costs; make the comparison arithmetically consistent; reject unreliable data; deliver without new infrastructure.

**Non-Goals:** Model unscheduled EV/water demand, prove full Darkstar savings, reproduce sub-slot inverter responses, tune planner settings, modify sensor recording, fix executor behaviour, add replay/archives, or add power tariffs.

## Decisions

### 1. Hold controlled-load consumption fixed

Demand is recorded base load plus recorded water heating plus recorded EV charging in every slot on both sides. Self-use may discharge only into the remaining household/water deficit. PV supplies household/water demand first, then any surplus may supply recorded EV demand; remaining EV energy imports from the grid. The cap is `max(0, load + water - eta_out * pv) / eta_out`. Mixed household/EV slots retain house-only battery discharge rather than copying Darkstar's blanket discharge block. Darkstar's real policy remains reflected in its recorded actions. No cheapest-price replacement schedule and no separate credit for load scheduling. Removing those loads would also remove real demand competing for the same battery/PV energy.

### 2. Calibrate one shared energy model, without assuming sensor boundaries

Add a pure calibration module alongside `backend/baseline.py`. Use existing numerical dependencies. Fit effective conversion factors in the recorded sensor boundary:

```
bus = pv + discharge - charge
grid_net = demand - (eta_out * bus if bus >= 0 else bus / eta_in)
stored_next = stored + eta_charge * charge - discharge / eta_discharge
```

Fit inverter factors against recorded `import - export`; fit battery factors against adjacent recorded SoC changes multiplied by configured capacity. Use bounded least-squares search with factors in [0.80, 1.00] and resolution 0.002, matching the investigated approach. Effective factors absorb measurement boundaries; a validated unity factor can describe AC measurements. Never apply a second guessed PV loss or copy Fronius values to another installation. If this family cannot explain an installation, mark the comparison unavailable.

Use at most the preceding 30 days of completed observations ending at the comparison end. Filter null/non-finite/negative energies, invalid SoC, malformed timestamps, `exclude: true` flags and known backfills; legacy rows without source metadata remain eligible if validation passes. Fit battery changes only on contiguous 15-minute pairs, with both SoCs strictly between 10% and 95% and throughput at least 0.05 kWh. Sort/split in UTC, first 80% for fitting and last 20% for validation; never randomly mix future observations into training.

Require at least 1,000 grid observations and 200 battery pairs before splitting. Each inverter bus direction and each battery flow direction must have at least 30 training observations and 3 kWh of excitation. Reject non-identifiable fits rather than pretending an unobserved direction was learned. Holdout gates: grid RMSE <= 0.25 kWh/slot, absolute mean grid error <= 0.03 kWh/slot, battery-change RMSE <= 0.25 kWh/pair, absolute mean battery-change error <= 0.03 kWh/pair, and net-cost error <= max(1 kr, 5% of gross billing volume). Gross billing volume uses absolute recorded prices and gross energies, so negative prices and near-zero net bills do not destabilise the gate. Gates are explicit initial acceptance policy, not a confidence interval or a guarantee of monetary precision.

For a requested period, additionally validate model grid net against recorded grid net using the same grid/cost gates; hide an older historical period if a single fit cannot explain it. Do not extend a model across insufficiently observed hardware/sensor regimes merely because the overall fit passes.

No calibration is persisted, no settings are changed, and no new database schema is needed. Perform fitting outside the async event-loop thread. Cache bounded results in memory for 15 minutes, keyed by installation/database identity, relevant battery/sensor configuration, model version and latest completed observation; clear on configuration changes. Existing historical periods can recompute on cache miss.

### 3. Normalize both sides; retain actual metered costs separately

Darkstar comparison grid flows come from the shared model with its recorded battery charge/discharge. Self-use grid flows come from the same model with simulated battery actions. Both use one non-negative import or export flow per 15-minute slot. This removes the gross-versus-net advantage from the estimate; it does not assert that a real inverter has perfect instantaneous response.

Keep existing actual grid totals, bars and API amounts calculated from gross metered import/export. Do not replace the user's electricity bill with a modeled bill. The battery comparison has separately named fields and labels. Do not add the real side's observed overlap or arbitrary tracking penalty to the hypothetical side: its sub-slot behaviour is unknown. Show this resolution limitation in the comparison explanation.

### 4. Simulate self-use with calibrated losses and configured limits

For demand D and recorded PV P, effective surplus is `eta_out * P - D`. Surplus charges at `min(surplus / eta_out, charge_limit, room / eta_charge)`; battery discharge is capped by non-EV demand: `min(max(0, load + water - eta_out * P) / eta_out, discharge_limit, usable * eta_discharge)`. EV energy remains part of D and the shared grid calculation. Limits are configured watts times the completed slot duration, expressed in the same flow boundary as the model. Apply shared battery factors to stored energy and re-evaluate grid flow through the shared model. The battery never grid-charges or exports energy beyond demand. Retain different charge and discharge power limits.

Start from the first slot's recorded `soc_start_percent` when available, otherwise the immediately preceding contiguous slot's `soc_end_percent`. Do not use a later/end-of-first-slot SoC as an invented starting point. Missing start or end SoC, interior observation gaps, missing prices or invalid essential energies make the selected-period comparison unavailable. Zero consumption remains valid. Include only completed slots; metered information can still include currently started slots. Current-day comparison explains its latest completed time. No-battery and empty-period states omit the comparison.

### 5. Compare economic costs and make endpoints reconcile

Use the period's mean recorded import price as a common reference, multiplied by calibrated inverter-output and battery-discharge factors. Negative prices remain negative; this is an explicit valuation assumption, not a forecast. For each side:

```
grid_cost = sum(import * import_price - export * export_price)
wear = (sum(charge) + sum(discharge)) * configured_cycle_cost * 0.5
stored_value = (end_stored - common_start_stored) * reference_price
comparison_cost = grid_cost + wear - stored_value
saving = self_use_comparison_cost - darkstar_comparison_cost
```

Darkstar end stored energy uses recorded SoC; self-use uses simulated SoC. The battery fit gate guards use of recorded flows with observed stored state. Wear uses the same recorded/model flow boundary on both sides and the existing configured wear convention; it is an assumption, not measured degradation.

Comparison chart points evaluate the same formula cumulatively at each completed bucket boundary, using the same period reference price throughout. Every boundary needs recorded Darkstar SoC. Final chart points equal respective summary comparison costs and their difference equals savings within display rounding. Explain the price reference and adjustments in a compact breakdown; never compare an adjusted savings badge with unadjusted dashed-line endpoints.

### 6. Add an explicit API contract and simple UI

Add `battery_comparison` to the cost-series response:

- `status`: `available`, `insufficient_data`, `unreliable_model`, `incomplete_period`, `no_battery`, or `no_data`; a stable `reason` code for detail.
- `method_version`, `through`, and `calibration` diagnostics: fitted factors, sample counts, training/validation bounds and validation errors.
- When available: `darkstar` and `self_use`, each with `grid_cost_sek`, `wear_cost_sek`, `stored_energy_change_kwh`, `stored_energy_value_sek`, and `comparison_cost_sek`; `saving_sek`, `reference_price_sek_kwh`, and comparison `points` with bucket start and both cumulative comparison costs.
- When unavailable: amounts and comparison points are absent, never zero placeholders or legacy estimates.

Preserve existing metered fields exactly. Keep legacy `baseline` fields for compatibility, explicitly separate from the validated comparison; the new UI must never fall back to legacy savings. They can be removed in a later API cleanup.

The Grid domain retains actual electricity cost prominently. When available, display "Estimated battery savings" with the two economic totals and paired comparison lines under a clearly labeled comparison view. Actual grid bars/line stay in their own cash-flow view; use a small Actual/Comparison selector rather than mixing bases. The comparison view shows the through-time and an accessible explanation: same recorded EV/water timings, self-use storage serves only house/water demand while remaining PV may supply EV charging, losses modeled on both sides, wear and remaining battery energy included, sub-slot behaviour estimated. When unavailable, retain the actual view and show one plain-language reason, e.g. "Not enough reliable data for a battery comparison." Remove the claim that retaining schedules necessarily makes savings conservative.

Use existing design tokens/components. Update dashboard and Design System fixtures; visually verify both routes, mobile/desktop and light/dark, with battery/no-battery and available/unavailable states.

## Risks / Trade-offs

- [A fitted model is not a meter or exact counterfactual] -> Label estimates, publish diagnostic errors, validate on holdout and period data, retain actual costs, and avoid invented penalties.
- [Some installations have insufficient data or unsupported measurement arrangements] -> Show a clear unavailable state; no fabricated/default calibration.
- [Good aggregate fit can conceal historical regime changes] -> Period validation and explicit gating; do not claim universal hardware coverage from one recording.
- [Stored-energy valuation changes historical totals] -> Expose the reference price and contribution; keep actual costs independent.
- [Strict gap/SoC validation hides some month comparisons] -> Prefer unavailable estimates over silently ignoring outages or inventing starting energy.
- [Calibration work delays API responses] -> Bounded numerical work off the event loop and bounded memory cache; measure cache-hit/miss response times.

## Migration Plan

Implement additive comparison data first, then update the UI and fixtures. Existing metered endpoints and values stay compatible. Reverting the new UI/API restores previous operation without a data migration. Verification must cover arithmetic, unreliable-data gating, differing measurement boundaries and both affected pages before the change is archived. Production recordings remain read-only local evidence and must not be committed.

## Open Questions

None required for implementation. The acceptance thresholds are an explicit initial policy, and a validated 15-minute estimate is the chosen deliverable. Exact sub-slot replay and unsupported installations require separate work, not open investigation tasks in this change.
