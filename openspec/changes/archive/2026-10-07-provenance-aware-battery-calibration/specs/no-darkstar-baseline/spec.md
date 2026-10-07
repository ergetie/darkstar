## MODIFIED Requirements

### Requirement: Baseline is unavailable without a battery
When system.has_battery is false, no battery comparison SHALL be computed or shown. Empty periods SHALL have no comparison amounts. A complete selected period that is eligible for the configured-loss path SHALL return a clearly labelled estimate when strict calibration is insufficient or fails its gates, preserving the actual calibration status/reason and any genuine diagnostics. A passing strict calibration SHALL return the verified basis. Only when the selected period is not eligible for either path, including invalid or missing required measurements, prices or state-of-charge anchors, SHALL the comparison be unavailable with no amounts. Actual metered costs SHALL remain available regardless of comparison availability.

#### Scenario: No battery
- **WHEN** system.has_battery is false
- **THEN** the cost-series comparison status is no_battery and the UI shows no battery comparison

#### Scenario: No recorded slots
- **WHEN** the period has no completed observations
- **THEN** comparison status is no_data with no amounts

#### Scenario: Strict calibration fails but an estimate is usable
- **WHEN** calibration is insufficient or fails a validation gate while the complete selected period remains eligible for configured-loss estimates
- **THEN** the comparison returns estimate amounts with basis configured_losses and the original calibration state/reason
- **AND** the UI identifies the result as an estimate

#### Scenario: Selected-period inputs are not estimate-eligible
- **WHEN** required selected-period measurements, prices or state-of-charge anchors are invalid or unsupported
- **THEN** the comparison has no amounts and the UI shows a plain-language unavailable reason beside actual metered information

### Requirement: Baseline battery accounting uses the configured limits and efficiencies
For the verified comparison, stored energy SHALL change by charge * eta_charge and discharge / eta_discharge, using calibrated effective factors in the recorded flow boundary. Capacity SHALL be configured battery.capacity_kwh. Configured minimum/maximum SoC and separate charge/discharge power limits SHALL be enforced. Missing or unreliable calibration SHALL withhold the verified comparison; it SHALL NOT substitute planner/default efficiencies as a learned comparison model. A separate configured-loss estimate may use the installation's configured charge/discharge efficiencies and limits under battery-comparison-calibration, and SHALL remain explicitly estimated. Inverter conversion and battery storage losses SHALL each be applied once.

#### Scenario: Efficiency applied
- **WHEN** 1.0 kWh is charged with validated eta_charge 0.92
- **THEN** simulated stored energy increases by 0.92 kWh

#### Scenario: Missing discharge calibration
- **WHEN** the discharge factor cannot be reliably calibrated
- **THEN** the verified comparison is unavailable rather than defaulting to 0.95
- **AND** any separately eligible configured-loss result remains labelled as an estimate

#### Scenario: Separate limits
- **WHEN** configured charge power is lower than discharge power
- **THEN** charging and discharging respect their respective limits
