## Purpose

Let Reflex use the PV confidence setting as a safety margin driven by relative forecast bias, so a site with a consistently over- or under-forecasting model is nudged back.

## ADDED Requirements

### Requirement: Relative bias decides confidence changes
Reflex SHALL compute PV bias over the last 14 days of cleaned slots as sum(forecast - actual) / sum(actual). When the bias is above +10 % it SHALL lower `forecasting.pv_confidence_percent`; when below -10 % it SHALL raise it. Within +/-10 % it SHALL leave it unchanged. Each change SHALL respect the existing bounds and maximum daily change, and the existing minimum sample count and once-per-day limit. Bias SHALL NOT be computed when the actual total is 0.

#### Scenario: Forecast too high
- **WHEN** the 14-day bias is +15 %
- **THEN** confidence SHALL be lowered by the maximum daily change, not below its lower bound

#### Scenario: Forecast too low
- **WHEN** the 14-day bias is -15 %
- **THEN** confidence SHALL be raised by the maximum daily change, not above its upper bound

#### Scenario: Within tolerance
- **WHEN** the bias is +6 %
- **THEN** no change SHALL be made and the report SHALL show the bias as a percentage

#### Scenario: Insufficient data or no production
- **WHEN** fewer than the minimum samples exist, or the actual total is 0
- **THEN** no change SHALL be made

#### Scenario: Independent of array size
- **WHEN** two sites with different array sizes have the same relative bias
- **THEN** both SHALL be treated identically
