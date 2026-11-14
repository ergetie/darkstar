## ADDED Requirements

### Requirement: Partial slots keep the line unbroken and are explained
The Grid & Financial card SHALL draw partial slots as part of the continuous cost lines. Each partial span SHALL show a note below the chart in the form "EV not measured for 26 h (Nov 9 10:00-Nov 10 12:15)", using fixed phrases per component, never raw codes. Partial spans SHALL use a hatched band style distinct from excluded spans, built on the existing exclusion-notes and hatched-band machinery, and follow `docs/design-system/AI_GUIDELINES.md`.

#### Scenario: EV partial span
- **WHEN** the response has a `partial_spans` entry for `ev` covering 105 slots
- **THEN** the chart line is unbroken across it and a note reads "EV not measured for 26 h 15 min (Nov 9 10:00-Nov 10 12:15)"

#### Scenario: Excluded spans unchanged
- **WHEN** a span is excluded
- **THEN** the line breaks and the existing "not compared" note is shown

#### Scenario: Missing partial data
- **WHEN** the response has no `partial_spans`
- **THEN** no partial note is shown and the chart renders as before
