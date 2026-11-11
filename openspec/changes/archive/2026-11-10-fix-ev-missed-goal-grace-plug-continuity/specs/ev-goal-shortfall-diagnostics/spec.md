## ADDED Requirements

### Requirement: Goal diagnostics use real time for partial slots
Goal diagnostics SHALL use the real current time (not the 15-minute-floored slot time) for slot eligibility and remaining slot-0 time. When the time remaining before the deadline multiplied by the charger's maximum power is below the required energy, the reason SHALL be `deadline_too_close` (or the unreachable classification). A partial slot SHALL NOT be reported against the full-slot minimum chunk.

#### Scenario: Partial slot 0
- **WHEN** 6 minutes remain in slot 0 and the requirement exceeds remaining time x max kW
- **THEN** the reason SHALL be `deadline_too_close`
- **AND** the minimum chunk reported SHALL be scaled to the remaining time
