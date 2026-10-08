## Context

The financial card currently consumes `battery_comparison` from `/api/energy/cost-series`. That request reads a calibration window, fits/caches a loss model, simulates self-use, and values remaining battery energy. Its chart reconstructs a "Without Darkstar" line from the difference between modeled comparison costs. A separate legacy self-use simulation also runs in the endpoint.

The agreed replacement is **DS vs grid-only**: the recorded household, water and EV consumption bought entirely from the grid at each recorded slot's import tariff. The actual side is the measured electricity bill. This is a comparison of the whole controlled installation, including solar and battery, with a different physical installation on the same tariff. It is not an estimate of controller-only optimization benefit.

`load_kwh` is isolated household consumption; `water_kwh` and `ev_charging_kwh` must be added once. Charging the stationary battery is not household consumption in the baseline. The codebase already stores separate per-slot import and export prices including applicable variable tariff components.

## Goals / Non-Goals

**Goals:**

- A deterministic sum using recorded consumption, grid flows, slot prices and the configured wear calculation.
- One signed comparison figure and directly priced Grid-only chart line.
- Matching coverage on both comparison sides, including incomplete data and DST.
- Supports installations without a battery or PV; configured batteries require measured charge/discharge for eligible comparison slots. SoC, calibration and forecasts are not required.
- Preserve actual headline accounting and separate battery wear information.

**Non-Goals:**

- Measuring marginal Darkstar controller benefit relative to another controller.
- Reconstructing different EV/water schedules or tariff contracts.
- Valuing remaining battery energy, lifetime returns, fixed subscription fees or capital costs.
- Modifying recording, planner/executor operation, history annotations, dependencies or database schema.

## Decisions

### 1. Price actual consumption slot by slot

For each eligible completed slot:

```
demand_kwh = load_kwh + water_kwh + ev_charging_kwh
grid_only_cost_sek = demand_kwh * import_price_sek_kwh
ds_electricity_cost_sek = import_kwh * import_price_sek_kwh - export_kwh * export_price_sek_kwh
ds_wear_cost_sek = (batt_charge_kwh + batt_discharge_kwh) * battery_cycle_cost_kwh * 0.5
ds_cost_sek = ds_electricity_cost_sek + ds_wear_cost_sek
grid_only_wear_cost_sek = 0
saving_sek = grid_only_cost_sek - (ds_cost_sek + grid_only_wear_cost_sek)
```

Sum unrounded values and round only response/display values. Retain measured gross imports and exports when both occurred within a slot; do not net energy before pricing. Keep zero and negative prices. Do not include stationary battery charging in grid-only demand or deduct PV from it. When a battery is configured, require finite nonnegative recorded battery charge/discharge values on each eligible slot and use the existing configured cycle-cost formula. Missing battery-flow measurements exclude that slot from both sides; do not replace them with zero. With no battery, wear is zero and battery-flow readings are not required.

Use the recorded slot tariff rather than averaging prices, looking up current configuration prices, or forecasting tomorrow. This represents the same recorded consumption bought from the grid, not a hypothetical monthly-price contract. Expose actual DS electricity cost separately from battery wear; include the existing configured wear calculation once in DS's wear-inclusive comparison total, and assign zero wear to grid-only.

### 2. A small calculation helper and a bounded period query

Create a focused pure accounting helper (for example `backend/grid_only_comparison.py`) for row validation, slot costs and bucket totals. Feed it the selected period's completed observations from the energy router. Do not read 30 days of history, preceding SoC, fit/cache models, simulate self-use or run a planner for this calculation.

Require finite nonnegative demand components and metered import/export energies, finite import/export prices, valid timezone-aware 15-minute timestamps, and genuine recorded rows. On configured-battery installations, battery charge/discharge values are also required, finite and nonnegative. Reject explicit exclusions, backfills, known snapshot/mixed essential readings, invalid values and missing slots; do not treat unknown required values as zero. Legacy `source: recorder` rows with valid relevant values remain usable as recorded bill data without upgrading their provenance. Modern validation concerns only demand/grid components and, when configured, measured battery flows; missing or cached SoC and unavailable PV do not disqualify otherwise valid inputs. Legitimately disabled demand components use recorded zero values. Missing configured-battery flow measurements do disqualify a slot.

Both sides exclude the same rows. Each completed slot is independent, so a gap does not require a new SoC anchor or drop an otherwise usable following slot. Count expected completed slots in elapsed UTC time; exclude the running and future slots. Bucket by installation-local hour/day while preserving distinct UTC identities for repeated DST hours.

### 3. An explicit response replacing retired contracts

Keep top-level actual `points`, period/date/bucket/error fields and metered costs unchanged. Introduce `grid_only_comparison` with:

- `status`: `available`, `partial`, `no_data` or `unavailable`;
- `reason`: `complete_coverage`, `partial_coverage`, `no_completed_observations` or `no_usable_observations`;
- `method_version`: `grid-only-bill-v1`;
- `coverage`: `covered_slots`, `total_slots`, `excluded_slots`;
- `time_axis`: installation IANA `timezone` and offset-qualified local ISO `start`/`end` for the full requested period, from its first local midnight to the exclusive following midnight; these bounds are not clipped to completed coverage;
- `through`: last included slot's exclusive end, when an amount-bearing result exists;
- amount-bearing fields: `grid_only_cost_sek`, zero `grid_only_wear_cost_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `saving_sek`, bucket `points`, and covered `segments`;
- each comparison bucket point: offset-qualified local ISO `start` and exclusive `end`, eligible `import_cost_sek`, `export_revenue_sek`, `ds_electricity_cost_sek`, `ds_wear_cost_sek`, zero `grid_only_wear_cost_sek`, wear-inclusive `ds_cost_sek`, `grid_only_cost_sek`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`;
- each covered segment: offset-qualified local ISO `start`, exclusive `end`, and boundary `points` carrying `at`, `cumulative_ds_cost_sek` and `cumulative_grid_only_cost_sek`.

Segments are maximal runs of eligible slots contiguous in elapsed UTC time, independent of hour/day bucket boundaries. Each segment contains a point at its start and at every included slot's exclusive end, ordered in UTC. Its start point carries the accumulated totals from all earlier eligible slots (zero for the first segment); later points add only that segment's eligible costs. Totals carry across gaps for reconciliation, but no segment, line or shading spans a gap. Bucket points retain hourly/daily totals for bars and readouts; segment points provide the exact line/shading geometry, including exclusions inside a partially covered bucket. Both representations use the same unrounded slot calculations and reconcile within response rounding.

`available` means complete input coverage, not calibration verification. `partial` means at least one usable slot and at least one excluded completed slot. `no_data` applies when there are no completed observations; `unavailable` applies when completed observations exist but none is usable. No-data/unavailable results omit money fields, comparison points and covered segments, but retain `time_axis` for the Actual-only chart. Their coverage still counts the requested elapsed completed slots, including missing records. An invalid range retains the endpoint's error/empty-actual-points behavior without fabricated comparison amounts.

Remove `baseline`, `baseline_*` point fields, `battery_comparison` and router-specific calibration/cache logic. This is an intentional response contract change; update the bundled frontend and tests together. Do not rename battery model data to grid-only or return legacy values as a fallback. Keep `backend/battery_comparison.py` and other helpers still imported by history-audit tools/tests; remove only modules/functions proven to have no remaining consumers. Preserve all stored observations and annotations.

### 4. One signed figure and a direct chart

Under the headline, show `DS vs grid-only +X.XX kr` or `DS vs grid-only -X.XX kr` using existing good/bad tokens (zero neutral). Remove "Darkstar saved you", "Darkstar cost you extra", Estimate/Verified chips, loss-fit diagnostics and the stored-energy adjustment fold-down.

Keep the accessible info toggle and outside-tap/Escape dismissal. Its exact explanation is: "Same recorded consumption bought entirely from the grid at each slot's price, compared with actual import costs minus export income, including estimated battery wear." Identify it as a whole-installation comparison including solar and exports. Include grid-only electricity and wear, DS electricity and wear-inclusive totals, completed-through local timestamp and covered/total slot counts. For partial results retain the muted covered-percentage suffix, floored and capped at 99. For no-data/unavailable results show one concise reason and no amount. Show the comparison for any installation with usable inputs, including no-battery installations.

When comparison amounts exist, draw the solid **DS** line from cumulative measured net electricity plus configured battery wear and the dotted **Grid-only** line from cumulative grid-only electricity cost. Use the covered segments' boundary points directly, not actual plus a simulated adjustment. Use the identically covered hourly/daily bucket points for import/export bars and readouts. This deliberately prevents comparing an unfinished/invalid actual slot against an omitted baseline slot. Top-level actual data remains the fallback chart when comparison data is unavailable; it retains the **Actual** legend and accounting. Headline actual totals remain independent and unchanged; details identify the comparison's completed coverage.

Use a common scale including zero, hourly/daily bars and readouts, design tokens, reduced-motion behavior and interactions. Draw each covered segment independently and split good/bad shading at crossings within it; never connect lines or shading across excluded slots, even inside one bucket. A bucket with no usable slot gets no fabricated contribution. A partially covered bucket includes its eligible costs only. Hover/tap shows the bucket's DS and Grid-only running values and eligible import/export costs.

Position all chart timestamps by elapsed UTC time within `time_axis.start`/`end`, including the Actual-only fallback. A single-day chart spans the full installation-local day: normally 24 elapsed hours, 23 at spring-forward and 25 at fall-back. Generate labels and readouts in `time_axis.timezone`, independent of the browser timezone. Omit the nonexistent spring-forward hour; give repeated fall-back hours distinct x positions and UTC-offset labels (for example `02:00 +02:00` and `02:00 +01:00`). Longer-period charts retain daily buckets positioned by their actual local-midnight UTC boundaries. Refresh design-system examples for complete, negative, partial, unavailable, within-bucket gaps and DST grid-only cases without creating new UI components or editing `docs/`.

## Risks / Trade-offs

- [The DS side includes configured wear while grid-only has no battery] → Name it DS vs grid-only and explain that the whole-installation comparison uses measured net electricity costs including configured battery wear; do not imply a lifetime return or scheduling-only benefit.
- [Same recorded EV/water timing does not reconstruct behavior without DS] → Define the baseline explicitly as the same consumption at the same times.
- [Legacy records can have imperfect measurement quality] → Validate relevant inputs and honor exclusions without implying a learned/verified physical model.
- [Current actual headline can include a started slot while comparison includes completed slots only] → Use matching completed data for both comparison chart lines and show through-time/coverage in details.
- [Third-party consumers may use retired response fields] → Mark the contract change explicitly and update every repository consumer in the same implementation.
- [Removing helpers can break history-audit tooling] → Inspect imports before deletion, preserve independently used provenance/calibration helpers, and run history/provenance regressions.

## Migration Plan

1. Add accounting helper, grid-only API contract and meaningful formula/coverage tests.
2. Switch frontend types, financial line, chart, design-system fixtures and tests together; remove retired request-path work and response fields.
3. Run focused backend/frontend regressions, history/provenance checks and `./scripts/lint.sh`; verify the financial card in light/dark themes at mobile/desktop sizes.
4. Roll back code as a unit if necessary. There is no persisted data or schema migration to reverse.

## Open Questions

None required before implementation. The selected contract compares per-slot grid-only electricity costs with measured DS electricity costs plus configured battery wear, without battery inventory valuation, under the exact label **DS vs grid-only**.
