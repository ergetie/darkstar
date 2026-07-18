# Delta Spec: planner

## MODIFIED Requirements

### Requirement: End-of-Horizon SoC Target acts as a Minimum Floor (Safety Floor)
The solver SHALL enforce the end-of-horizon `target_soc` constraint solely as a minimum floor. It SHALL penalize the solver heavily if the final State of Charge (SoC) is *below* the target (`target_under_violation`). The solver SHALL NOT apply any penalty (`target_over_violation`) if the final SoC exceeds the target, allowing the system to naturally preserve excess free or cheap energy beyond the minimum safety requirement.

The safety floor calculation SHALL use **temporal (per-slot) deficit** instead of aggregate deficit ratio. For each forecast slot, the system SHALL compute `max(0, load_forecast - pv_forecast)` and sum these values to determine the total energy the battery must provide when PV is unavailable. This temporal deficit SHALL replace the previous `(total_load - total_pv) / total_load` aggregate ratio.

The safety floor calculation SHALL look **beyond the price horizon** by using extended load/PV forecast data for a 24h window starting from where the price data ends. The forecast-data pipeline that feeds the planner SHALL supply **slot-level** load/PV forecasts covering at least 24h beyond the price horizon whenever such slots exist in the forecast store; this extended slot-level data SHALL NOT be reduced to daily aggregates before reaching the safety floor calculation, and SHALL be provided independently of the price-bounded planning horizon used by the solver. When extended forecast data is **genuinely absent** from the forecast store for the look-ahead window, the system SHALL fall back to using only the available horizon and log a warning. The fallback-and-warn path SHALL NOT be reached merely because available extended forecast slots were not loaded or were truncated to the price horizon.

The safety floor SHALL incorporate two risk-based mechanisms:
1. A **risk margin** applied to the temporal deficit (higher risk appetite = lower margin, trusting the forecast more)
2. A **minimum floor** per risk level as a percentage of battery capacity above min_soc, ensuring the floor never collapses to min_soc regardless of forecast conditions

The safety floor SHALL be capped at a **risk-aware maximum buffer**. The effective cap SHALL be derived by scaling the configured `max_safety_buffer_percent` (which retains its existing meaning as the Risk 3 / Neutral baseline) by a per-risk multiplier that decreases monotonically with risk appetite (Risk 1 highest ceiling, Risk 5 lowest; Risk 3 multiplier = 1.0 so Neutral behavior is unchanged). The effective cap SHALL never be lower than the risk level's own minimum floor percentage, so the promised per-risk minimum buffer can never be suppressed by the cap. The S-Index debug output SHALL report the effective (post-scaling) cap and the applied multiplier.

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

#### Scenario: Extended forecast slots present in store are loaded and used
- **GIVEN** the forecast store (`slot_forecasts`) contains slot-level PV/load forecasts extending at least 24h beyond the price horizon
- **WHEN** the safety floor is calculated
- **THEN** the calculation SHALL receive those extended slots as slot-level data and compute the temporal deficit over the 24h look-ahead window beyond the price horizon
- **AND** the system SHALL NOT log the "extended forecast data unavailable or insufficient" warning

#### Scenario: Risk level 3 neutral user in spring
- **GIVEN** risk_appetite = 3, min_soc = 12%, battery capacity = 34.2 kWh
- **WHEN** the temporal deficit beyond the price horizon is approximately 15 kWh (overnight load)
- **THEN** the safety floor SHALL be significantly above min_soc (approximately 20-35% depending on margin and minimum floor)

#### Scenario: Risk level 5 gambler with PV surplus
- **GIVEN** risk_appetite = 5
- **WHEN** temporal deficit beyond the price horizon is calculated
- **THEN** the safety floor SHALL equal min_soc (0% margin, 0% minimum floor)

#### Scenario: Extended forecast data unavailable
- **WHEN** load/PV forecast data does not extend beyond the price horizon **in the forecast store** (genuinely absent, e.g. a forecast outage or early deployment)
- **THEN** the system SHALL log a warning
- **AND** the safety floor SHALL use only the available horizon data with the minimum floor per risk level as baseline

#### Scenario: Risk-aware max safety buffer cap applies
- **WHEN** the calculated safety floor (temporal deficit reserve + weather buffer + minimum floor) exceeds the risk level's effective cap above min_soc
- **THEN** the safety floor SHALL be capped at min_soc + (configured max buffer fraction × per-risk multiplier × capacity)

#### Scenario: Risk levels produce differentiated floors under saturating deficit
- **GIVEN** a temporal deficit large enough to exceed every risk level's effective cap
- **AND** `max_safety_buffer_percent` = 20
- **WHEN** the safety floor is calculated for risk levels 1, 3, and 5
- **THEN** the Risk 1 floor SHALL be strictly greater than the Risk 3 floor
- **AND** the Risk 3 floor SHALL be strictly greater than the Risk 5 floor
- **AND** the Risk 3 floor SHALL equal the pre-change flat-cap floor (min_soc + 20% of capacity)

#### Scenario: Effective cap never suppresses the per-risk minimum floor
- **GIVEN** risk_appetite = 1 (minimum floor 25% of capacity)
- **AND** `max_safety_buffer_percent` configured low (e.g. 10)
- **WHEN** the safety floor is calculated
- **THEN** the effective cap SHALL be raised to at least the risk level's minimum floor percentage
- **AND** the delivered floor SHALL honor the 25% minimum buffer

#### Scenario: Debug output reports the effective cap
- **WHEN** the safety floor is calculated
- **THEN** the S-Index debug payload SHALL include the effective (post-scaling, post-minimum-floor) `max_buffer_kwh` and the applied per-risk cap multiplier
