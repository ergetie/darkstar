## MODIFIED Requirements

### Requirement: Per-device executor state tracking
The executor SHALL maintain independent state per charger: charging active flag, slot end time, zero-power tick count, and failure notification flag. Stopping a charger when its plan ends SHALL follow directly from the plan for that charger, independently of other chargers. There SHALL be no separate time-based "safety timeout" overrun check.

#### Scenario: One charger's plan ends while another continues
- **WHEN** charger A's scheduled charging ends
- **AND** charger B is still within its scheduled slot
- **THEN** the executor SHALL stop charger A on that tick
- **AND** charger B SHALL continue charging normally

#### Scenario: Fresh state on config reload
- **WHEN** the executor config is reloaded
- **THEN** the executor SHALL rebuild its per-device state dict from the new charger list
- **AND** chargers removed from config SHALL have their state dropped
