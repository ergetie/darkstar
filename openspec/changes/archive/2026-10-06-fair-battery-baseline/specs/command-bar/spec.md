## ADDED Requirements

### Requirement: Grid domain displays a consistent estimated battery comparison
The dashboard Grid domain SHALL retain actual metered electricity costs prominently and SHALL display an available validated comparison as "Estimated battery savings". It SHALL show the Darkstar and plain self-use comparison totals on the same economic basis and offer distinct Actual and Comparison chart views. The comparison view SHALL plot both validated cumulative comparison costs; its final gap SHALL match the displayed saving within rounding. Actual cash-flow bars/lines SHALL NOT be mixed with comparison lines. Negative saving SHALL be communicated as an estimated additional battery-management cost. The UI SHALL NOT use legacy baseline savings as a fallback.

#### Scenario: Available estimate
- **WHEN** validated self-use cost is 40 kr and Darkstar comparison cost is 30 kr
- **THEN** estimated battery savings display 10 kr
- **AND** the comparison chart's endpoint gap is 10 kr
- **AND** actual metered electricity cost remains separately identifiable

#### Scenario: Negative estimate
- **WHEN** validated estimated saving is negative
- **THEN** the UI describes estimated additional cost without presenting it as savings

### Requirement: Battery comparison assumptions and unavailable states are understandable
The comparison SHALL expose its latest completed time and an accessible explanation that EV charging/water heating retain recorded timings, self-use storage serves only house/water demand and remaining PV may supply EV energy, losses are modeled on both sides, wear and energy left in the battery are included, and 15-minute observations cannot reproduce exact sub-slot inverter response. A compact breakdown SHALL expose grid cost, wear, stored-energy value and the common valuation price. The UI SHALL NOT claim full Darkstar savings or guaranteed conservative savings. For insufficient, unreliable or incomplete data, it SHALL show one plain-language reason with no saving amount or comparison line; actual information SHALL remain visible. No-battery installations SHALL hide comparison controls. Shared cost-chart changes SHALL be visually verified on Dashboard and Design System using existing design tokens, across mobile/desktop and light/dark themes.

#### Scenario: Fixed controlled loads
- **WHEN** the user opens the comparison explanation
- **THEN** it states that recorded EV/water schedules are shared, storage supplies only non-EV demand, remaining PV may supply the EV, and scheduling savings are excluded

#### Scenario: Unreliable estimate
- **WHEN** comparison status is `unreliable_model`
- **THEN** the UI explains that the data cannot support a reliable battery comparison
- **AND** it shows actual costs without an estimated saving or comparison line

#### Scenario: No battery
- **WHEN** no battery is configured
- **THEN** the user sees the actual view with no battery-comparison controls
