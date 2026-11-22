# Spec Delta

## MODIFIED Requirements

### Requirement: Slots with an unknown device component are not trained on
Load training and every other ML consumer of slot `load_kwh` SHALL drop slots with an unmeasured device component, because the derived load still contains that device's energy, and slots whose `quality_flags.base_load.reliable` is false (with or without `recording` provenance), and SHALL store the drop count as `dropped_unmeasured_device_rows`.

#### Scenario: Drop rules
- **THEN** a slot is dropped when any device component (`ev`, `water`, other) has method `unknown`, `snapshot` or `mixed`, or when `load` is unknown, or when `base_load.reliable` is false, so legacy rows with a fake 0 device snapshot or a clamped 0 are never trained on
- **AND** a device with `unconfigured_zero` does not cause a drop, and rows without `recording` provenance and without a `base_load` flag are unaffected

#### Scenario: Count storage
- **THEN** the count is stored in `learning_runs` `result_metrics_json` and in the load model sidecar

#### Scenario: EV unknown slot dropped
- **WHEN** a slot has `ev=unknown` and `load=derived_history`
- **THEN** it SHALL NOT be used for load training

#### Scenario: Device snapshot slot dropped
- **WHEN** a slot has `ev=snapshot` and `load=mixed`
- **THEN** it SHALL NOT be used for load training

#### Scenario: Clamped slot dropped
- **WHEN** a slot has `load_kwh` 0 and `base_load.reliable` false with reason `negative_after_subtraction`
- **THEN** it SHALL NOT be used for load training and does not feed the clamp-day statistics as a real zero

#### Scenario: Flagged legacy row without recording dropped
- **WHEN** a row without `recording` provenance carries `base_load.reliable` false
- **THEN** it SHALL NOT be used for load training

#### Scenario: Unconfigured device slot kept
- **WHEN** a slot has `water=unconfigured_zero`, `load=mixed` and every other device measured
- **THEN** it SHALL be kept

#### Scenario: Measured slot kept
- **WHEN** a slot has all device components measured and no `base_load` flag
- **THEN** it SHALL be kept

#### Scenario: Count reported
- **WHEN** training completes
- **THEN** the metrics contain `dropped_unmeasured_device_rows`
