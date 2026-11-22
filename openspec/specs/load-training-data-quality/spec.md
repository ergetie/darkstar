# Capability: Load Training Data Quality

## Purpose

Keep fake or corrupt load history out of load model training while keeping good legacy history.

## Requirements

### Requirement: Legacy backfill rows are not trained on
Load training SHALL drop rows with `source: backfill` that do not carry modern `recording` provenance. Rows with `"exclude": true` SHALL be dropped as before.

#### Scenario: Backfill row dropped
- **WHEN** a row has `source: backfill` and no `recording` object
- **THEN** it SHALL NOT be used for load training

### Requirement: Clamp-signature days are dropped
Load training SHALL drop every whole local day that is a legacy day with a clamp signature. A legacy day has no `recording` provenance on any of its rows. A clamp signature needs at least 80 slots in the day and more than 30 % of them clamp slots. A clamp slot has `load_kwh <= 0.02` while `import_kwh`, `pv_kwh` or `batt_discharge_kwh` is `> 0.1`.

#### Scenario: Fake legacy day flagged
- **WHEN** a legacy day has 96 slots of which 50 have load 0 while import is 0.3 kWh
- **THEN** the whole day SHALL be dropped

#### Scenario: Normal day kept
- **WHEN** a legacy day has at most 28 % clamp-signature slots
- **THEN** all its rows SHALL be kept

### Requirement: Clamp rule exemptions and constants
Days with `recording` provenance and days with fewer than 80 slots SHALL NOT be dropped by the clamp rule. All other rows, including long good legacy history, SHALL be kept. Thresholds are module constants, not configuration, and contain no per-site values. A balance-residual rule is NOT used.

#### Scenario: Short or modern day kept
- **WHEN** a day has 60 slots, or its rows carry `recording` provenance
- **THEN** the clamp rule SHALL NOT drop it

### Requirement: Dropped data is reported
Each training run SHALL log the number of dropped backfill rows, dropped clamp days and their rows, and store these counts in `learning_runs` `result_metrics_json` and the load model sidecar.

#### Scenario: Counts stored
- **WHEN** training completes
- **THEN** the metrics SHALL contain dropped days and rows per rule

### Requirement: Load training receives historical weather
Load training SHALL use the same historical weather frame as PV training and SHALL continue without weather (warning only) if the fetch fails.

#### Scenario: Weather fetch fails
- **WHEN** the historical request returns no data
- **THEN** load models SHALL still be trained with weather columns missing

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
