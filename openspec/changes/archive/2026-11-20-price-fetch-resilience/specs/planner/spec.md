# Spec Delta

## ADDED Requirements

### Requirement: Empty price input fails with PRICES_UNAVAILABLE
Schedule generation SHALL raise `PlannerError` with code `PRICES_UNAVAILABLE` when the input contains no price slots, before any other planning step, so that the transient retry backoff and the price fix hint apply.

#### Scenario: No price slots
- **WHEN** schedule generation receives an empty `price_data`
- **THEN** it SHALL raise `PlannerError` with code `PRICES_UNAVAILABLE` and `price_slot_count` 0 in the details
- **AND** the existing `schedule.json` SHALL be left untouched

#### Scenario: Retry policy applies
- **WHEN** the planner service handles that error
- **THEN** the failure SHALL follow the transient backoff and show the price fix hint
