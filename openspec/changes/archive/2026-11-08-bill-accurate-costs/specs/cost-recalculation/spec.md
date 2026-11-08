## ADDED Requirements

### Requirement: Recalculate historical import prices
The system SHALL provide an endpoint that reprices `slot_observations.import_price_sek_kwh` from the stored raw-spot `export_price_sek_kwh` from a given date using current pricing settings, including time-of-use transfer rules, skipping rows with NULL export price, and returning repriced and skipped counts.

#### Scenario: Repricing
- **WHEN** recalculation is requested from a date
- **THEN** rows from that date get new import prices and counts are returned

#### Scenario: Null export price
- **WHEN** a row has NULL export price
- **THEN** it is skipped and counted as skipped

### Requirement: Recalculate action in Settings
The Pricing section SHALL offer a "Recalculate costs from [date]" button with a confirmation Modal and a result toast.

#### Scenario: Confirm
- **WHEN** the user confirms
- **THEN** the endpoint is called and a toast shows the counts

### Requirement: Plan metric step documented
Old slot_plans SHALL NOT be repriced; the learning plan-vs-actual cost metric steps at the recalculation date and this is documented.

#### Scenario: Plans untouched
- **WHEN** recalculation runs
- **THEN** slot_plans rows are unchanged
