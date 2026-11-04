## Purpose

Tell the user, informationally and in plain language, when recorded PV is far from what the weather physically allows, so they can check array settings, shading or the PV measurement, and let them acknowledge the notice.

## Requirements

### Requirement: Inform on implausible recorded PV
Health checks SHALL report an informational notice (not a warning or error) when, over clear days in the last 60 days, total recorded PV divided by total Open-Meteo baseline is below 0.55 or above 1.30. Only cleaned slots (same rules as PV training) SHALL count. The notice SHALL state the ratio as a rounded percentage.

#### Scenario: Recorded PV far too low
- **WHEN** 20 clear days show a ratio of 0.40
- **THEN** an info notice SHALL say the panels produce much less than forecast on clear days (about 40 % of forecast), name shading, a wrong panel setting or a missing string as possible causes, and say Darkstar still learns and adjusts the forecast

#### Scenario: Recorded PV far too high
- **WHEN** 20 clear days show a ratio of 1.50
- **THEN** an info notice SHALL say the panels produce much more than forecast on clear days (about 150 % of forecast), name panels configured smaller than they really are or production measured twice as possible causes, and say Darkstar still learns and adjusts the forecast

#### Scenario: Plausible
- **WHEN** the ratio is 0.55 to 1.30 inclusive
- **THEN** no notice SHALL be shown

#### Scenario: Check failure
- **WHEN** the check cannot read data
- **THEN** it SHALL show nothing and never fail the health report

### Requirement: Clear-day definition and minimum evidence
A clear day SHALL be one whose baseline total is at least 75 % of the highest daily baseline in the 60-day window and at least 1 kWh. At least 14 clear days SHALL be required; otherwise no notice is shown.

#### Scenario: Too few clear days
- **WHEN** only 9 clear days exist in the window
- **THEN** no notice SHALL be shown

### Requirement: Plain-language wording
The notice SHALL be non-technical, SHALL NOT use the words error or failed, and SHALL contain no technical identifiers.

#### Scenario: Message content
- **WHEN** a notice is shown
- **THEN** it SHALL contain no technical identifiers and SHALL describe causes in everyday words

### Requirement: The user can acknowledge the notice
The user SHALL be able to acknowledge the notice. Acknowledging SHALL record the ratio at that moment, persist across restarts and browsers, and hide the notice. The notice SHALL reappear only when the ratio moves at least 0.10 further beyond the acknowledged value in the same direction (lower if it was low, higher if it was high), or crosses to the other side of the plausible range. When the ratio returns inside the plausible range the acknowledgement SHALL be cleared.

#### Scenario: Acknowledged and stable
- **WHEN** the user acknowledges at ratio 0.40 and the ratio later is 0.38
- **THEN** the notice SHALL stay hidden

#### Scenario: Much worse
- **WHEN** acknowledged at 0.40 and the ratio later is 0.30
- **THEN** the notice SHALL be shown again

#### Scenario: Slightly better is not a reason to reshow
- **WHEN** acknowledged at 0.40 and the ratio later is 0.50
- **THEN** the notice SHALL stay hidden

#### Scenario: Other side of the range
- **WHEN** acknowledged at 0.40 and the ratio later is 1.40
- **THEN** the notice SHALL be shown again

#### Scenario: Recovered and later recurs
- **WHEN** acknowledged at 0.40, the ratio returns to 0.80, and later falls to 0.45
- **THEN** the notice SHALL be shown again

#### Scenario: Acknowledgement survives restart
- **WHEN** the application restarts after acknowledgement
- **THEN** the notice SHALL stay hidden under the same rules

#### Scenario: Acknowledge without a current notice
- **WHEN** an acknowledgement is requested while no notice is active
- **THEN** the request SHALL be rejected and nothing SHALL be stored
