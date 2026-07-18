## Purpose

Let operators temporarily hide known/acknowledged health banners from the system alert surface without permanently dismissing them, so recurring or expected issues don't create alert fatigue while still resurfacing if they persist or the situation changes.

## Requirements

### Requirement: Health banners can be snoozed, never permanently dismissed
Every health banner rendered by the system alert surface (critical and warning) SHALL offer a snooze control (✕). Snoozing SHALL hide that specific issue — keyed by its stable identifier (`code`, falling back to `category`), never by message text — for a fixed 24-hour window stored client-side. After the window expires the issue SHALL reappear if still present. There SHALL be no permanent dismissal.

#### Scenario: Snoozing hides one issue only
- **WHEN** two warning banners are shown and the user snoozes one
- **THEN** only the snoozed issue disappears and the other banner remains visible

#### Scenario: Snooze expires
- **WHEN** an issue was snoozed more than 24 hours ago and is still reported by the health API
- **THEN** its banner is rendered again

#### Scenario: Changing evidence text does not defeat the snooze
- **WHEN** a snoozed invariant's message changes only in its live numbers (e.g. "98.64 %" becomes "98.71 %") between evaluations
- **THEN** the issue remains snoozed, because snoozing keys on the issue's stable identifier, not its message

### Requirement: Snoozed issues remain discoverable
While one or more issues are snoozed, the alert surface SHALL display a compact indicator showing the number of snoozed issues, and interacting with it SHALL allow the user to reveal (un-snooze) them.

#### Scenario: Snoozed issues are one click away
- **WHEN** at least one issue is snoozed
- **THEN** a "N snoozed" indicator is visible, and activating it restores the hidden banner(s)
