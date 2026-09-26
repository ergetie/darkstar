## ADDED Requirements

### Requirement: HA ready-by always produces a one-off goal
Whenever an HA ready-by datetime is adopted into a charger's goal — via a live `state_changed` event or via startup/reconnect reconciliation — the backend SHALL write `repeat: "none"`, `ready_by_date` set to the datetime's local date, and `ready_by` set to its local `HH:MM`. The backend SHALL NOT default `repeat` to `daily` or preserve a previous repeating mode on these paths. An HA change to the target-SoC entity alone SHALL NOT modify `repeat`, `ready_by`, `ready_by_date` or `n_days`.

#### Scenario: Live HA ready-by change on a daily goal
- **WHEN** a charger has a daily 07:00 goal and the user sets its HA ready-by entity to `2026-09-27 06:30:00`
- **THEN** the goal SHALL become `repeat: "none"`, `ready_by_date: "2026-09-27"`, `ready_by: "06:30"`

#### Scenario: Reconnect adoption
- **WHEN** the backend reconnects and adopts a sane future HA ready-by
- **THEN** the resulting goal SHALL be the same one-off goal the live-change path would produce for that datetime

#### Scenario: HA target-SoC change only
- **WHEN** only the HA target-SoC entity changes for a charger with a weekdays goal
- **THEN** the goal SHALL keep `repeat: "weekdays"` and its ready-by time

### Requirement: HA sync never moves the every-N-days anchor
HA live changes, reconnect reconciliation and write-back echoes SHALL preserve the goal's `anchor_date` unchanged and SHALL NOT be used to derive a new cycle anchor, even though they update `last_updated`.

#### Scenario: HA echo on an every-3-days goal
- **WHEN** an every-3-days goal anchored on 2026-09-20 receives an HA target-SoC change on 2026-09-25
- **THEN** `anchor_date` SHALL remain 2026-09-20 and the next resolved deadline SHALL be unchanged
