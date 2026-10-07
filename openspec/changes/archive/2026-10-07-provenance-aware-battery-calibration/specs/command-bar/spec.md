## MODIFIED Requirements

### Requirement: Grid domain displays a consistent estimated battery comparison
The dashboard Grid domain SHALL retain actual metered electricity costs prominently and SHALL display every amount-bearing battery comparison on a consistent economic basis. A configured-loss result SHALL be labelled “Estimate based on configured losses”; a result whose strict fitted model passed the calibration and selected-period checks SHALL be labelled “Verified”. Both SHALL show the Darkstar and plain self-use comparison totals on the same active basis and offer distinct Actual and Comparison chart views. The Comparison view SHALL plot both cumulative comparison costs, and its final gap SHALL match the displayed saving within rounding. Actual cash-flow bars/lines SHALL NOT be mixed with comparison lines. A negative saving SHALL be communicated as an estimated additional battery-management cost. The UI SHALL NOT use legacy baseline savings as a fallback or present a configured-loss estimate as verified.

#### Scenario: Available configured-loss estimate
- **WHEN** the comparison has status estimated, basis configured_losses, self-use cost 40 kr and Darkstar cost 30 kr
- **THEN** the UI labels it “Estimate based on configured losses” and displays savings of 10 kr
- **AND** the comparison chart endpoint gap is 10 kr
- **AND** actual metered electricity cost remains separately identifiable

#### Scenario: Negative comparison
- **WHEN** a comparison on either active basis has a negative saving
- **THEN** the UI describes the additional battery-management cost and shows whether the basis is estimated or verified

### Requirement: Battery comparison assumptions and unavailable states are understandable
The comparison SHALL expose its latest completed time and an accessible explanation that EV charging/water heating retain recorded timings, self-use storage serves only house/water demand and remaining PV may supply EV energy, losses are modeled on both sides according to the active basis, wear and energy left in the battery are included, and 15-minute observations cannot reproduce exact sub-slot inverter response. A compact breakdown SHALL expose grid cost, wear, stored-energy value and the common valuation price. The UI SHALL NOT claim full Darkstar savings or guaranteed conservative savings. When a configured-loss estimate is shown, it SHALL identify the estimate basis and show the underlying calibration status/reason without suggesting validation passed. When no supported estimate can be produced for the selected period, it SHALL show one plain-language reason with no saving amount or comparison line; actual information SHALL remain visible. A calibration state alone SHALL NOT suppress a valid configured-loss estimate. No-battery installations SHALL hide comparison controls. Shared cost-chart changes SHALL be visually verified on Dashboard and Design System using existing design tokens, across mobile/desktop and light/dark themes.

#### Scenario: Fixed controlled loads
- **WHEN** the user opens the comparison explanation
- **THEN** it states that recorded EV/water schedules are shared, storage supplies only non-EV demand, remaining PV may supply the EV, and scheduling savings are excluded

#### Scenario: Unreliable calibration with a usable estimate
- **WHEN** comparison status is estimated and its calibration status is unreliable_model
- **THEN** the UI labels the configured-loss basis, explains the calibration reason plainly and shows actual costs separately
- **AND** it does not claim that the estimate passed validation

#### Scenario: No battery
- **WHEN** no battery is configured
- **THEN** the user sees the actual view with no battery-comparison controls

## ADDED Requirements

### Requirement: Grid domain explains trustworthy history availability
The Grid domain SHALL distinguish collecting trustworthy compatible history, an unsupported selected period and a numerical accuracy failure through one short plain-language reason. It SHALL keep actual electricity costs visible and omit unavailable saving amounts and comparison lines. It SHALL NOT blame hardware, instruct users to weaken checks, expose internal provenance terminology or present configured-loss estimates as if they were verified. Copy and fixtures SHALL follow the existing design system.

#### Scenario: Collecting trustworthy history
- **WHEN** reason is `unverified_history` or `insufficient_compatible_history`
- **THEN** the UI explains that the battery comparison needs more trustworthy energy history
- **AND** it does not describe this as a failed accuracy check

#### Scenario: Unsupported period readings
- **WHEN** reason is `unsupported_period_measurements`
- **THEN** the UI explains that this period includes readings the comparison cannot reliably use

#### Scenario: Model accuracy failure
- **WHEN** sufficient trustworthy data fails numeric validation and no usable configured-loss estimate exists
- **THEN** the UI retains the accuracy-failure explanation without an estimated saving

### Requirement: Grid comparison labels the active basis
When comparison amounts are present, the Grid domain SHALL label configured-loss results “Estimate based on configured losses” and calibrated results “Verified”. It SHALL show the status/reason for calibration alongside an estimate without suggesting that the estimate passed validation. Saving amounts, cards and chart comparison lines SHALL all reflect the same active basis. Unavailable-period copy SHALL continue to explain missing or unsupported usable data plainly.

#### Scenario: Configured-loss result
- **WHEN** comparison amounts use configured losses
- **THEN** cards and chart identify the values as an estimate based on configured losses

#### Scenario: Verified result
- **WHEN** comparison amounts use the validated fitted model
- **THEN** the UI identifies the result as verified

#### Scenario: Learning reason accompanies estimate
- **WHEN** estimated amounts are available while history is insufficient or calibration is unreliable
- **THEN** the UI shows the estimate basis and concise calibration state/reason together
