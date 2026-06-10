## Purpose

The Planner is responsible for generating optimized energy management schedules by solving MILP (Mixed Integer Linear Programming) problems. It coordinates data fetching, solver execution, and result delivery.

## Requirements

### Requirement: Planner Handles Formatting Safely
The planner logging logic SHALL correctly escape standard percent-formatting characters.

#### Scenario: Logging EV SoC fallback
- **WHEN** EV SoC sensor returns no data
- **THEN** the system logs a warning with the literal "0%" without crashing

### Requirement: Meaningful Planner Error Notifications
The planner error handler SHALL emit structured error records carrying a `PlannerErrorCode`, a human-readable message, a fix hint, and a diagnostic payload for every failure. The previous generic `ValueError("Planner generated invalid schedule (safety guard)")` SHALL be replaced by a typed `PlannerError` with code `INVALID_SCHEDULE` and diagnostics including the solver status, the last observed `initial_soc_kwh`, `max_soc_kwh`, and `capacity_kwh`.

Solver-level failures SHALL be mapped to codes `SOLVER_INFEASIBLE` (when PuLP reports `LpStatusInfeasible`), `SOLVER_UNDEFINED` (when PuLP reports `LpStatusUndefined`), and `SOLVER_TIMEOUT` (when the solver's `timeLimit` is exceeded). The solver status string SHALL be included in the diagnostics payload for each.

The WebSocket `planner_error` event payload SHALL include the `code` and `details` fields. The existing `error` string field SHALL continue to be populated for backwards compatibility.

#### Scenario: Generic ValueError is replaced by typed error
- **WHEN** the planner would previously have raised `ValueError("Planner generated invalid schedule (safety guard)")`
- **THEN** it raises `PlannerError` with code `INVALID_SCHEDULE`
- **AND** the diagnostics include solver status, `initial_soc_kwh`, `max_soc_kwh`, and `capacity_kwh`

#### Scenario: Infeasible solver status maps to SOLVER_INFEASIBLE
- **WHEN** PuLP reports `LpStatusInfeasible` after the solver returns
- **THEN** the emitted error has code `SOLVER_INFEASIBLE`
- **AND** the diagnostics include the solver status string

#### Scenario: Undefined solver status maps to SOLVER_UNDEFINED
- **WHEN** PuLP reports `LpStatusUndefined`
- **THEN** the emitted error has code `SOLVER_UNDEFINED`
- **AND** the diagnostics include the solver status string

#### Scenario: WebSocket payload carries structured fields
- **WHEN** the backend emits a `planner_error` event
- **THEN** the payload includes `error` (string, legacy), `code` (string), and `details` (object) fields

### Requirement: End-of-Horizon SoC Target acts as a Minimum Floor (Safety Floor)
The solver SHALL enforce the end-of-horizon `target_soc` constraint solely as a minimum floor. It SHALL penalize the solver heavily if the final State of Charge (SoC) is *below* the target (`target_under_violation`). The solver SHALL NOT apply any penalty (`target_over_violation`) if the final SoC exceeds the target, allowing the system to naturally preserve excess free or cheap energy beyond the minimum safety requirement.

The safety floor calculation SHALL use **temporal (per-slot) deficit** instead of aggregate deficit ratio. For each forecast slot, the system SHALL compute `max(0, load_forecast - pv_forecast)` and sum these values to determine the total energy the battery must provide when PV is unavailable. This temporal deficit SHALL replace the previous `(total_load - total_pv) / total_load` aggregate ratio.

The safety floor calculation SHALL look **beyond the price horizon** by using extended load/PV forecast data for a 24h window starting from where the price data ends. When extended forecast data is unavailable, the system SHALL fall back to using only the available horizon and log a warning.

The safety floor SHALL incorporate two risk-based mechanisms:
1. A **risk margin** applied to the temporal deficit (higher risk appetite = lower margin, trusting the forecast more)
2. A **minimum floor** per risk level as a percentage of battery capacity above min_soc, ensuring the floor never collapses to min_soc regardless of forecast conditions

The existing `max_safety_buffer_pct` cap SHALL still apply to prevent the floor from exceeding reasonable levels.

#### Scenario: Excess Solar Energy at End of Horizon
- **WHEN** the battery receives abundant solar energy and covering all loads leaves the end-of-horizon SoC higher than the calculated Safety Floor target
- **THEN** the solver finishes the horizon with the high SoC without attempting to force-dump the energy into the grid to hit the target

#### Scenario: Spring day with aggregate PV surplus but overnight deficit
- **WHEN** total PV forecast over the horizon exceeds total load forecast (aggregate surplus)
- **AND** evening/night slots have load but zero PV (temporal deficit exists)
- **THEN** the safety floor SHALL reflect the temporal deficit (not zero)
- **AND** the risk appetite setting SHALL meaningfully scale the floor

#### Scenario: Midday planning with short price horizon
- **WHEN** planning occurs at midday and price data only extends to midnight (~11.5h horizon)
- **AND** load/PV forecasts extend beyond midnight
- **THEN** the safety floor SHALL use the extended forecast data for the 24h window beyond midnight to account for tomorrow's overnight energy needs

#### Scenario: Price horizon expands after 13:00
- **WHEN** tomorrow's prices arrive at 13:00 and the price horizon extends to tomorrow midnight
- **THEN** the safety floor look-ahead window SHALL shift to cover the 24h beyond tomorrow midnight
- **AND** the MILP can now directly optimize the previously-blind overnight period

#### Scenario: Risk level 3 neutral user in spring
- **GIVEN** risk_appetite = 3, min_soc = 12%, battery capacity = 34.2 kWh
- **WHEN** the temporal deficit beyond the price horizon is approximately 15 kWh (overnight load)
- **THEN** the safety floor SHALL be significantly above min_soc (approximately 20-35% depending on margin and minimum floor)

#### Scenario: Risk level 5 gambler with PV surplus
- **GIVEN** risk_appetite = 5
- **WHEN** temporal deficit beyond the price horizon is calculated
- **THEN** the safety floor SHALL equal min_soc (0% margin, 0% minimum floor)

#### Scenario: Extended forecast data unavailable
- **WHEN** load/PV forecast data does not extend beyond the price horizon
- **THEN** the system SHALL log a warning
- **AND** the safety floor SHALL use only the available horizon data with the minimum floor per risk level as baseline

#### Scenario: Max safety buffer cap applies
- **WHEN** the calculated safety floor (temporal deficit reserve + weather buffer + minimum floor) exceeds `max_safety_buffer_pct` of battery capacity above min_soc
- **THEN** the safety floor SHALL be capped at min_soc + (max_safety_buffer_pct * capacity)

### Requirement: Solver Respects Export Threshold
The planner adapter MUST map the user's `export_threshold_sek_per_kwh` parameter to the solver configuration. The solver MUST mathematically deduct this threshold from the spot price before making export decisions, preventing micro-cycling for negligible profits.

#### Scenario: Spot price does not clear threshold
- **WHEN** the spot price is only 0.05 SEK higher than the import cost + wear cost, and the `export_threshold` is set to 0.20 SEK
- **THEN** the solver refrains from exporting energy, as the adjusted profit margin is negative

### Requirement: Dynamic Export Threshold Based on Price Volatility and Risk Appetite
The StrategyEngine SHALL calculate `export_threshold_sek_per_kwh` dynamically based on price spread (volatility) and user's `risk_appetite` setting. The calculation SHALL use a continuous function (not step-based) to eliminate threshold gaps.

**Formula:**
```python
# Risk appetite shifts the minimum threshold floor
RISK_BASELINE_SHIFTS = {
    1: 0.15,   # Safe: Never below 0.15 SEK
    2: 0.10,   # Conservative: Floor at 0.10
    3: 0.05,   # Neutral: Floor at 0.05
    4: 0.02,   # Aggressive: Floor at 0.02
    5: 0.00,   # Gambler: Can go to 0.00 on high spread days
}

# Normalize spread: 0.0 at 0.3 SEK, 1.0 at 2.0 SEK
spread_norm = max(0.0, min(1.0, (spread - 0.3) / 1.7))

# Threshold scales from 0.50 (low spread) down to risk-based baseline (high spread)
baseline = RISK_BASELINE_SHIFTS[risk_appetite]
threshold = 0.50 - (0.50 - baseline) * spread_norm
```

**Behavior:**
- At low price spread (< 0.3 SEK): Threshold = 0.50 SEK (conservative, prevents micro-cycling in flat markets)
- At high price spread (> 2.0 SEK): Threshold = risk-based baseline (aggressive users capture more marginal profits)
- Between 0.3 and 2.0 SEK: Linear interpolation
- Risk appetite only affects the floor, not the ceiling
- `wear_cost_sek_per_kwh` and `ramping_cost_sek_per_kw` overrides MUST always be applied alongside the threshold — they remain spread-dependent and are NOT removed by this change

#### Scenario: Flat price day with conservative user
- **GIVEN** price spread of 0.2 SEK and `risk_appetite = 1` (safe)
- **WHEN** the StrategyEngine calculates export threshold
- **THEN** the threshold is 0.50 SEK (high threshold prevents unnecessary cycling)

#### Scenario: Volatile price day with aggressive user
- **GIVEN** price spread of 2.5 SEK and `risk_appetite = 5` (gambler)
- **WHEN** the StrategyEngine calculates export threshold
- **THEN** the threshold is 0.00 SEK (captures all profitable opportunities)

#### Scenario: Moderate volatility with neutral user
- **GIVEN** price spread of 1.0 SEK and `risk_appetite = 3` (neutral)
- **WHEN** the StrategyEngine calculates export threshold
- **THEN** the threshold is approximately 0.24 SEK (balanced protection)

#### Scenario: Continuous scaling eliminates step-function gaps
- **GIVEN** price spread of 0.5 SEK (previously in the "gap")
- **WHEN** the StrategyEngine calculates export threshold for `risk_appetite = 3`
- **THEN** the threshold is approximately 0.38 SEK (no longer falls back to default 0.0)

### Requirement: Solver blocks battery discharge during EV charging
The solver SHALL force battery discharge to zero in any slot where ANY EV charger is charging. This SHALL be enforced by introducing an auxiliary binary `any_ev_charging[t]` that is 1 when any charger's `ev_charge[d][t]` is 1, then applying the Big-M constraint: `discharge[t] <= (1 - any_ev_charging[t]) * M`, where `M = max_discharge_kw * slot_hours[t]`. The linking constraints SHALL be: `any_ev_charging[t] >= ev_charge[d][t]` for each device d, and `any_ev_charging[t] <= sum(ev_charge[d][t] for d)`. This constraint SHALL only be added when at least one EV charger is present in the solver input.

#### Scenario: One of two chargers active forces zero discharge
- **WHEN** the solver schedules charger A to charge in slot t (`ev_charge[A][t] = 1`) and charger B is idle (`ev_charge[B][t] = 0`)
- **THEN** `any_ev_charging[t]` is forced to 1
- **AND** `discharge[t]` is forced to 0.0 by the Big-M constraint

#### Scenario: No chargers active allows normal discharge
- **WHEN** no charger is scheduled in slot t (all `ev_charge[d][t] = 0`)
- **THEN** `any_ev_charging[t]` is 0
- **AND** `discharge[t]` is bounded only by its normal upper bound

#### Scenario: EV disabled users are unaffected
- **WHEN** no EV chargers are present in the solver input
- **THEN** no EV-related discharge constraint is added to the MILP model
- **AND** solver behavior is identical to before this change

### Requirement: Adapter passes per-device EV configs to solver
The planner adapter SHALL build a list of `EVChargerInput` objects from the `ev_chargers[]` config array, fetching per-device SoC and plug state from Home Assistant. Only enabled chargers SHALL be included. The adapter SHALL NOT aggregate EV chargers into a single blob.

#### Scenario: Two enabled chargers with different states
- **WHEN** charger A has SoC 30% and is plugged in, charger B has SoC 80% and is unplugged
- **THEN** the adapter SHALL pass both chargers to the solver with their individual states

#### Scenario: Disabled charger excluded
- **WHEN** charger A is enabled and charger B has `enabled: false`
- **THEN** only charger A SHALL be passed to the solver

### Requirement: Per-device deadline calculation
The pipeline SHALL calculate `ev_deadline` independently for each charger using that charger's `departure_time` field. Chargers without a departure time SHALL have `deadline: None`.

#### Scenario: Two chargers with different departure times
- **WHEN** charger A has `departure_time: "07:00"` and charger B has `departure_time: "09:00"`
- **AND** current time is 22:00
- **THEN** charger A's deadline SHALL be tomorrow 07:00 and charger B's deadline SHALL be tomorrow 09:00

#### Scenario: Charger with no departure time
- **WHEN** a charger has `departure_time: ""`
- **THEN** its deadline SHALL be `None` (no deadline constraint in solver)

### Requirement: Per-device initial state fetching
The `get_initial_state()` function SHALL fetch SoC and plug state for ALL enabled chargers from Home Assistant, returning per-device state instead of scalar values.

#### Scenario: All chargers' states fetched
- **WHEN** three chargers are enabled with different SoC and plug sensors
- **THEN** `get_initial_state()` SHALL return SoC and plug state for each charger individually

#### Scenario: Missing SoC sensor defaults to 0%
- **WHEN** a charger has no `soc_sensor` configured
- **THEN** its SoC SHALL default to 0% (conservative: assumes empty battery)

#### Scenario: Missing plug sensor defaults to true
- **WHEN** a charger has no `plug_sensor` configured
- **THEN** its plug state SHALL default to `True` (assume plugged in, let user control via enabled flag)

### Requirement: Replan plug state override applies per-device
When a replan is triggered by a specific charger's plug-in event, the known plug state (`plugged_in=True`) SHALL be passed as an override for that specific charger only. Other chargers SHALL still fetch their plug state from the HA REST API.

#### Scenario: Charger A plug-in triggers replan
- **WHEN** charger A's plug sensor fires a plug-in event
- **THEN** `get_initial_state()` SHALL use `plugged_in=True` for charger A
- **AND** charger B's plug state SHALL be fetched from HA REST API

### Requirement: Adapter builds per-device water heater configs
The planner adapter SHALL replace `_aggregate_water_heaters()` with a per-device config builder that creates a `WaterHeaterInput` for each enabled water heater from the `water_heaters[]` config array. The adapter SHALL NOT aggregate power, daily minimums, or timing settings across heaters.

#### Scenario: Two enabled heaters produce two WaterHeaterInput objects
- **WHEN** `water_heaters[]` contains two entries with `enabled: true`
- **THEN** the adapter SHALL create two `WaterHeaterInput` objects
- **AND** each SHALL have its own `power_kw`, `min_kwh_per_day`, `max_hours_between_heating`, and `min_spacing_hours`

#### Scenario: Global settings passed alongside per-device list
- **WHEN** the adapter builds KeplerConfig
- **THEN** global water settings (comfort penalties, block penalties, reliability penalty, deferral hours, max block hours) SHALL remain as scalar fields on KeplerConfig
- **AND** per-device settings SHALL be in the `water_heaters` list

#### Scenario: No enabled heaters produces empty list
- **WHEN** no water heaters have `enabled: true`
- **THEN** `KeplerConfig.water_heaters` SHALL be an empty list
- **AND** water heating SHALL be disabled in the solver

### Requirement: Pipeline builds per-device mid-block locking
The pipeline SHALL detect mid-block heating state per water heater independently. For each heater currently in an active heating block (detected via power sensor), the pipeline SHALL set `force_on_slots` on that heater's `WaterHeaterInput`.

#### Scenario: One heater mid-block, another idle
- **WHEN** heater A's power sensor shows active heating and heater B's power sensor shows idle
- **THEN** heater A's `WaterHeaterInput.force_on_slots` SHALL contain the remaining block slot indices
- **AND** heater B's `WaterHeaterInput.force_on_slots` SHALL be None or empty

#### Scenario: No heaters mid-block
- **WHEN** no heater power sensors show active heating
- **THEN** all heaters' `force_on_slots` SHALL be None or empty

### Requirement: Pipeline tracks per-device today's heated energy
The pipeline SHALL calculate `heated_today_kwh` per water heater from recorder data or sensor state. Each heater's `WaterHeaterInput.heated_today_kwh` SHALL reflect only that heater's contribution.

#### Scenario: Two heaters with different today progress
- **WHEN** heater A has heated 4.0 kWh today and heater B has heated 2.0 kWh today
- **THEN** heater A's `heated_today_kwh` SHALL be 4.0
- **AND** heater B's `heated_today_kwh` SHALL be 2.0

### Requirement: Soft max-SoC bound with penalty
The Kepler MILP SHALL enforce `battery.max_soc_percent` as a soft constraint. The solver SHALL introduce a per-slot `soc_overshoot[t] >= 0` slack variable and replace the previous hard upper bound `soc[t] <= max_soc_kwh` with `soc[t] <= max_soc_kwh + soc_overshoot[t]`. The objective SHALL include a penalty term `MAX_SOC_PENALTY * sum(soc_overshoot[t])` where `MAX_SOC_PENALTY = 1000.0` (mirroring the existing `MIN_SOC_PENALTY`).

The clipping of `initial_soc` to the physical range SHALL use `[0, capacity_kwh]` only; it SHALL NOT clip to `[min_soc_kwh, max_soc_kwh]`.

The KeplerConfig SHALL include an `export_floor_soc_percent: float | None` field. When set and `enable_export` is True, the solver SHALL add a per-slot binary `is_exporting[t]` and enforce that grid export is only allowed when `soc[t] >= export_floor_kwh`, using a soft constraint with `EXPORT_FLOOR_PENALTY = 1000.0`.

#### Scenario: Initial SoC above max produces a feasible plan
- **GIVEN** `battery.max_soc_percent = 95` and `capacity_kwh = 19.2` (max_soc_kwh = 18.24)
- **AND** measured initial SoC is 18.989 kWh (98.9%)
- **WHEN** the planner runs
- **THEN** the solver returns status `Optimal`
- **AND** the resulting plan's first slot begins with a discharge action (battery_charge_kw < 0) or an export action sufficient to reduce SoC toward the ceiling
- **AND** the `soc_overshoot` penalty is reflected in the total cost

#### Scenario: Initial SoC below max is unaffected
- **GIVEN** `battery.max_soc_percent = 95` and measured SoC is 10.0 kWh (52%)
- **WHEN** the planner runs
- **THEN** the solver returns status `Optimal`
- **AND** `soc_overshoot[t]` is zero for all slots

#### Scenario: Lower bound behavior unchanged
- **GIVEN** measured initial SoC is below `min_soc_kwh`
- **WHEN** the planner runs
- **THEN** the existing `soc_violation` slack and `MIN_SOC_PENALTY` are applied
- **AND** no change to the lower-bound enforcement is observed

#### Scenario: Export floor config passed through adapter
- **GIVEN** `export_floor_soc_percent = 20` is configured in the planner config
- **WHEN** the adapter builds `KeplerConfig`
- **THEN** `KeplerConfig.export_floor_soc_percent` SHALL be 20.0
- **AND** the solver SHALL enforce the export-floor constraint

### Requirement: Pre-flight validator runs before solver
The planner pipeline SHALL invoke a deterministic pre-flight validator before constructing the Kepler MILP. The validator SHALL perform an ordered sequence of checks and SHALL raise a typed `PlannerError` carrying a `PlannerErrorCode` and a structured diagnostic payload on the first failed check. The checks SHALL include at minimum:

1. Battery config: `min_soc_percent < max_soc_percent`, `capacity_kwh > 0` if battery enabled, and `max_charge_power_kw > 0 AND max_discharge_power_kw > 0` if battery enabled (code `CONFIG_INVALID`).
2. Initial SoC within `[0, capacity_kwh]` (code `INITIAL_SOC_OUT_OF_RANGE`).
3. Initial SoC reading timestamp within 30 minutes of now (code `DATA_STALE`, warning — does not halt).
4. Every plugged-in EV charger has `max_power_kw > 0` (code `EV_MISSING_POWER`).
5. Every plugged-in EV charger has `battery_capacity_kwh > 0` (code `EV_INVALID_CAPACITY`).
6. Every EV charger with a `deadline` has `deadline > now` (code `EV_DEADLINE_PAST`, warning — does not halt, EV excluded from deadline constraints for that run).
7. Price data covers at least 4 hours ahead of now (code `PRICES_UNAVAILABLE`).
8. Forecast data is non-empty and covers the planning horizon (code `FORECAST_UNAVAILABLE`).
9. No NaN or Inf values in prices or forecasts (code `NUMERIC_INVALID`).

On a blocking failure, the validator SHALL raise immediately without running additional checks. On warning-only conditions, the validator SHALL log the warning and continue.

The 30-minute SoC staleness threshold SHALL be hardcoded; no configuration surface is introduced.

#### Scenario: Invalid battery config halts before solver
- **GIVEN** `battery.min_soc_percent = 50` and `battery.max_soc_percent = 40`
- **WHEN** the planner runs
- **THEN** the pre-flight validator raises `PlannerError` with code `CONFIG_INVALID`
- **AND** the Kepler solver is not invoked
- **AND** the error details include `min_soc_percent` and `max_soc_percent` values

#### Scenario: EV missing power halts with specific code
- **GIVEN** an EV charger is plugged in with `max_power_kw = 0`
- **WHEN** the planner runs
- **THEN** the pre-flight validator raises `PlannerError` with code `EV_MISSING_POWER`
- **AND** the error details include the offending `charger_id`

#### Scenario: Missing prices halt with transient code
- **GIVEN** no price slots are available for the next 4 hours
- **WHEN** the planner runs
- **THEN** the pre-flight validator raises `PlannerError` with code `PRICES_UNAVAILABLE`
- **AND** the error details include the price horizon range observed

#### Scenario: Stale SoC reading produces warning only
- **GIVEN** the battery SoC reading timestamp is 45 minutes old
- **WHEN** the planner runs
- **THEN** the pre-flight validator emits a `DATA_STALE` warning but does not halt
- **AND** the solver still runs with the observed SoC value

#### Scenario: EV deadline in the past produces warning only
- **GIVEN** an EV charger has `deadline` set to 1 hour before now
- **WHEN** the planner runs
- **THEN** the pre-flight validator emits an `EV_DEADLINE_PAST` warning but does not halt
- **AND** the Kepler solver runs without applying a deadline constraint for that charger

#### Scenario: NaN in forecast data halts
- **GIVEN** at least one forecast slot contains a NaN value
- **WHEN** the planner runs
- **THEN** the pre-flight validator raises `PlannerError` with code `NUMERIC_INVALID`
- **AND** the error details identify the offending field and slot

### Requirement: Inverter AC constraint permits zero discharge when PV forecast exceeds inverter capacity
The Kepler MILP SHALL apply the `max_inverter_ac_kw` limit only to power that crosses the AC inverter. It SHALL split forecast PV per slot into `pv_to_battery[t] >= 0` (DC-coupled charge that bypasses the AC stage) and `pv_to_ac[t] >= 0` (PV feeding load/export through the inverter), with the balance `pv_to_battery[t] + pv_to_ac[t] + curtailment[t] == s.pv_kwh` where `s.pv_kwh = pv_forecast[t]`. The AC limit SHALL be enforced as `pv_to_ac[t] + discharge[t] <= inverter_ac_kwh` where `inverter_ac_kwh = max_inverter_ac_kw * slot_hours[t]`.

For `dc_coupled` topology (the default), `pv_to_battery[t]` SHALL NOT count against the AC limit and SHALL be bounded only by available battery charge headroom and the battery charge-power limit. For `ac_coupled` topology, battery charging also crosses the AC inverter and the limit SHALL include it (equivalent to the previous `pv_forecast[t] + discharge[t] <= inverter_ac_kwh`).

The model SHALL remain feasible for every `pv_forecast[t]`, including `pv_forecast[t] >= inverter_ac_kwh`: surplus PV that cannot cross the AC side SHALL be absorbable by `pv_to_battery[t]` (subject to battery headroom) or `curtailment[t]`, never forcing infeasibility. When `max_inverter_ac_kw` is unset, no AC-limit constraint SHALL be added (unchanged default).

#### Scenario: PV forecast within inverter limit — normal discharge bound (dc_coupled)
- **WHEN** `pv_forecast[t] = 1.5 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and no PV is routed to battery (`pv_to_battery[t] = 0`)
- **THEN** `pv_to_ac[t] = 1.5 kWh` and `discharge[t] <= 0.5 kWh`
- **AND** the LP is feasible for this slot

#### Scenario: PV forecast exceeds inverter limit — surplus routes to battery, no infeasibility (dc_coupled)
- **WHEN** `pv_forecast[t] = 2.1177 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and battery charge headroom is available
- **THEN** the surplus above `inverter_ac_kwh` SHALL be absorbable by `pv_to_battery[t]` (here `pv_to_battery[t] >= 0.1177 kWh`) rather than forced to curtailment
- **AND** `pv_to_ac[t] + discharge[t] <= 2.0 kWh` holds
- **AND** the solver returns `Optimal`, not `Infeasible`

#### Scenario: PV-to-AC export is independently capped (dc_coupled)
- **WHEN** `pv_forecast[t] = 3.0 kWh`, `inverter_ac_kwh = 2.0 kWh`, topology `dc_coupled`, and battery headroom can absorb 1.0 kWh
- **THEN** `pv_to_ac[t] <= 2.0 kWh` (so PV feeding load + export never exceeds the AC rating)
- **AND** the remaining `>= 1.0 kWh` is routed to `pv_to_battery[t]` and/or `curtailment[t]`
- **AND** the plan SHALL NOT assume grid export of PV beyond `inverter_ac_kwh` in this slot

#### Scenario: AC-coupled topology retains the stricter combined limit
- **WHEN** `pv_forecast[t] = 1.5 kWh`, `inverter_ac_kwh = 2.0 kWh`, and topology `ac_coupled`
- **THEN** battery charging counts against the AC limit, enforcing `pv_forecast[t] + discharge[t] <= inverter_ac_kwh` (i.e. `discharge[t] <= 0.5 kWh`)
- **AND** when `pv_forecast[t] >= inverter_ac_kwh` the effective discharge upper bound is `0.0` and the LP remains feasible

#### Scenario: Inverter limit unset — no AC constraint added
- **WHEN** `max_inverter_ac_kw` is unset (default)
- **THEN** no inverter-AC constraint SHALL be added to the MILP
- **AND** PV routing variables MAY be omitted (no AC cap to enforce)

### Requirement: Kepler result merge is index-aligned and crash-safe
After the Kepler solver runs, the pipeline merges `result_df` columns back into `final_df` using index-aligned pandas assignment. The merge SHALL NOT use positional `.values` assignment. If `len(result_df) != len(future_df)`, the pipeline SHALL log an error at `ERROR` level describing the mismatch (including both lengths) and continue with index-aligned assignment so that matching slots are correctly populated.

#### Scenario: Normal case — equal lengths
- **WHEN** Kepler returns the same number of slots as `future_df` has rows and timestamps align
- **THEN** all columns from `result_df` are written into `final_df` with correct values for every row
- **AND** no error is logged

#### Scenario: Length mismatch — no crash
- **WHEN** `result_df` has fewer rows than `final_df` (e.g., due to duplicate timestamps from malformed price input)
- **THEN** the pipeline SHALL NOT raise a `ValueError`
- **AND** the pipeline SHALL log an `ERROR` message containing both lengths
- **AND** matched rows in `final_df` SHALL receive correct `result_df` values
- **AND** unmatched rows SHALL retain the NaN values from the join

#### Scenario: No positional assignment in result merge loop
- **WHEN** the pipeline writes Kepler result columns into `final_df`
- **THEN** each assignment uses `final_df[col] = result_df[col]` (index-aligned Series assignment)
- **AND** `result_df[col].values` (positional numpy array assignment) is never used

### Requirement: Reported plan cost uses the effective export price

The reported plan cost (`total_cost_sek` and per-slot `cost_sek`) SHALL be recomputed using the same effective export price the solver objective minimized — `export_price − export_threshold` per exported kWh — so the displayed cost matches the optimized quantity. This is a reporting correction only; planning decisions are unchanged.

#### Scenario: Reported cost matches the optimized export price

- **WHEN** a plan exports energy in slots with a non-zero export threshold
- **THEN** the reported cost values the exported energy at `export_price − export_threshold` per kWh
- **AND** the reported total equals the cost the solver actually minimized

#### Scenario: No double-subtraction and no decision change

- **WHEN** the export threshold is zero
- **THEN** the reported cost is identical to today's value
- **AND** the chosen schedule is unchanged in all cases

### Requirement: Simulation SoC projection reflects total battery charge within the SoC band

The `/api/simulate` SoC projection SHALL use total battery charge (including PV-sourced charge), not grid-sourced charge only, and SHALL clamp the projected SoC to the configured min/max SoC band.

#### Scenario: PV charging is reflected in the simulated SoC curve

- **WHEN** the battery charges from surplus PV in a simulated slot
- **THEN** the projected SoC rises by the total battery charge for that slot, not only the grid-sourced portion

#### Scenario: Projected SoC stays within the configured band

- **WHEN** the projection would exceed the configured min or max SoC
- **THEN** the projected SoC is clamped to the configured band
