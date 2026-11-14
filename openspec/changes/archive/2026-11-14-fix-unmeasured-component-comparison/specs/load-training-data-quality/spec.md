## ADDED Requirements

### Requirement: Slots with an unknown device component are not trained on
Load training and every other ML consumer of slot `load_kwh` SHALL drop slots whose `recording.components` has method `unknown` for any device component (`ev`, `water`, other device component), because the derived load still contains the unmeasured device energy. Slots with any device component method `snapshot` or `mixed`, or an unknown `load` method, SHALL also be dropped, so legacy rows with a fake 0 device snapshot are never trained on. A device with `unconfigured_zero` SHALL NOT cause a drop. Rows without `recording` provenance are unaffected. The drop count SHALL be stored in `learning_runs` `result_metrics_json` and the load model sidecar as `dropped_unmeasured_device_rows`.

#### Scenario: EV unknown slot dropped
- **WHEN** a slot has `ev=unknown` and `load=derived_history`
- **THEN** it SHALL NOT be used for load training

#### Scenario: Device snapshot slot dropped
- **WHEN** a slot has `ev=snapshot` and `load=mixed`
- **THEN** it SHALL NOT be used for load training

#### Scenario: Unconfigured device slot kept
- **WHEN** a slot has `water=unconfigured_zero`, `load=mixed` and every other device measured
- **THEN** it SHALL be kept

#### Scenario: Measured slot kept
- **WHEN** a slot has all device components measured
- **THEN** it SHALL be kept

#### Scenario: Count reported
- **WHEN** training completes
- **THEN** the metrics contain `dropped_unmeasured_device_rows`
