## ADDED Requirements

### Requirement: Battery Top Up ends at its target SoC
The `force_charge` quick action SHALL end when the house battery SoC reaches or exceeds its `target_soc`, not after a fixed duration. It SHALL also end when the user clears it, and after a safety timeout of 24 hours. A `force_charge` request SHALL be rejected when `target_soc` is below the configured `min_soc_percent`, above 100, or when the current battery SoC is already at or above the target. The `force_charge` action SHALL NOT require or be limited by the 15/30/60-minute duration list; `force_stop` and `force_heat` keep their existing duration behaviour.

#### Scenario: Target reached
- **GIVEN** a Top Up to 80% is active
- **WHEN** the battery SoC reads 80%
- **THEN** the quick action SHALL be cleared and the executor SHALL follow the schedule on the next tick

#### Scenario: Charging longer than an hour
- **GIVEN** a Top Up to 100% starting at 20%
- **WHEN** 60 minutes pass and SoC is 70%
- **THEN** the Top Up SHALL still be active

#### Scenario: Safety timeout
- **GIVEN** a Top Up whose target is never reached
- **WHEN** 24 hours have passed since it started
- **THEN** the quick action SHALL be cleared

#### Scenario: Target below minimum SoC rejected
- **GIVEN** `min_soc_percent` is 12
- **WHEN** a Top Up to 10% is requested
- **THEN** the request SHALL be rejected

#### Scenario: Already at target rejected
- **GIVEN** battery SoC is 85%
- **WHEN** a Top Up to 80% is requested
- **THEN** the request SHALL be rejected with an error saying the target is already reached
