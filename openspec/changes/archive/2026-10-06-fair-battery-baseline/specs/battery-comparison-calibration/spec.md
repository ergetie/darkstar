## ADDED Requirements

### Requirement: Calibration uses installation observations without changing operation
The system SHALL derive one installation-specific effective inverter/battery loss model from at most 30 days of completed observations ending at the selected comparison end. It SHALL model `bus = pv + discharge - charge`, `grid_net = demand - (eta_out * bus if bus >= 0 else bus / eta_in)`, and `stored_next = stored + eta_charge * charge - discharge / eta_discharge`. Factors SHALL be fitted within [0.80, 1.00] at resolution 0.002. Calibration SHALL NOT assume that all PV/battery readings are AC, add an additional guessed PV loss, use another installation's constants, write configuration, change planner settings, or modify recorded observations.

#### Scenario: Different sensor boundaries
- **WHEN** two installations record different effective PV-to-load conversion losses
- **THEN** each installation uses independently validated effective factors
- **AND** no additional universal PV derating is applied

#### Scenario: Unsupported measurements
- **WHEN** no model in the allowed family explains an installation within the validation gates
- **THEN** the comparison is unavailable with `unreliable_model`
- **AND** metered information remains available

### Requirement: Calibration validates independent observations and sufficient excitation
Calibration SHALL reject null/non-finite/negative essential energy readings, invalid SoC/timestamps, rows marked `exclude: true`, and known backfills. Legacy source metadata SHALL be allowed subject to validation. Battery samples SHALL use only contiguous 15-minute SoC pairs strictly within 10–95% SoC with battery throughput at least 0.05 kWh. The system SHALL require at least 1,000 eligible grid observations and 200 eligible battery pairs, sorted in UTC and split chronologically 80% training and 20% validation. Both bus directions and both battery flow directions SHALL each have at least 30 training observations and 3 kWh of excitation; unidentifiable fits SHALL be rejected.

The withheld grid and battery fits SHALL each satisfy RMSE <= 0.25 kWh/sample and absolute mean error <= 0.03 kWh/sample. Grid net-cost error SHALL be <= max(1 kr, 5% of recorded gross billing volume), with billing volume computed using absolute prices and gross energies. The selected comparison period SHALL independently satisfy the grid energy/cost gates. Fitting SHALL NOT use withheld samples or observations after the comparison end. These gates SHALL be described as reliability policy, not statistical confidence intervals.

#### Scenario: Too little history
- **WHEN** the installation has fewer than 1,000 eligible grid observations or 200 battery pairs
- **THEN** comparison amounts are withheld with `insufficient_data`

#### Scenario: Unobserved conversion direction
- **WHEN** training data lacks sufficient grid-charging bus excitation
- **THEN** the fit is rejected rather than assigning an invented learned input efficiency

#### Scenario: Withheld errors fail
- **WHEN** training errors are small but withheld net-cost error exceeds the gate
- **THEN** comparison amounts are withheld with `unreliable_model`

#### Scenario: Historical regime differs
- **WHEN** the calibration passes holdout validation but fails selected-period validation
- **THEN** that selected period has no available comparison

#### Scenario: Negative prices and almost-zero net costs
- **WHEN** recorded prices include negative values or the net bill is near zero
- **THEN** the cost-error gate uses absolute-price gross billing volume rather than dividing by the net bill

### Requirement: Calibration work is bounded and does not block async requests
The system SHALL perform calibration outside the async event-loop thread and SHALL use a bounded in-memory cache with at most a 15-minute lifetime. Cache identity SHALL include installation/database identity, relevant battery/sensor configuration, model version and latest completed observation. Configuration changes SHALL invalidate cached fits. Cached data SHALL NOT introduce observations later than the comparison end, and calibration SHALL require no new persistent schema or dependency.

#### Scenario: Configuration changes
- **WHEN** capacity or relevant measurement configuration changes
- **THEN** a previously cached fit is not reused

#### Scenario: Concurrent energy request
- **WHEN** a cache miss starts fitting
- **THEN** numerical fitting does not run on the async event-loop thread
