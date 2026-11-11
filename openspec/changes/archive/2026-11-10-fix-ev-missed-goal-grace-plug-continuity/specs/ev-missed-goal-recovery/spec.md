## MODIFIED Requirements

### Requirement: Missed goal stays active during a grace window
When a charger's goal deadline has passed, the charger is plugged in now (or unreachable with last known state plugged in), and the live, non-stale SoC is below `target_soc_percent - missed_goal_tolerance_percent`, the pipeline SHALL keep the goal active with an effective deadline of `missed_deadline + missed_goal_grace_hours`, capped at the goal's next regular ready-by, provided the plug-continuity, SoC-drop and tolerance requirements below allow it.

#### Scenario: Goal missed, car still plugged in
- **WHEN** the goal was 55% by 10:30, it is now 10:31, SoC is 53%, the car has been plugged since before 10:30, and grace is 4 h
- **THEN** the planner SHALL use an effective deadline of 14:30
- **AND** SHALL schedule the remaining energy in the cheapest slots before 14:30

#### Scenario: Charger unreachable
- **WHEN** the charger is unreachable and its last known state was plugged in with a session starting at or before the missed deadline
- **THEN** it SHALL count as continuously plugged
- **AND** if the last known state was unplugged, no grace SHALL apply

#### Scenario: Stale or missing SoC
- **WHEN** the SoC is stale or unavailable
- **THEN** no grace window SHALL apply

#### Scenario: Legit late departure
- **WHEN** the car stayed plugged across the deadline and is still plugged with SoC below target
- **THEN** grace SHALL apply

#### Scenario: Car unplugged after missed deadline
- **WHEN** the deadline passed and the charger reports unplugged
- **THEN** no grace window SHALL apply

#### Scenario: Grace window expired
- **WHEN** the deadline passed more than `missed_goal_grace_hours` ago
- **THEN** the goal SHALL resolve to its next regular ready-by (or none for one-off goals), as today

#### Scenario: Grace disabled
- **WHEN** `missed_goal_grace_hours` is 0
- **THEN** behaviour SHALL be identical to before this change

#### Scenario: Grace disabled, goal changed, grace expired, capped
- **WHEN** `missed_goal_grace_hours` is 0, the goal was saved after the missed deadline, the grace window expired, or the next ready-by precedes the grace end
- **THEN** behaviour SHALL be as before this change

#### Scenario: Goal set after its deadline
- **WHEN** the goal was saved (`last_updated`) after the deadline it would have missed
- **THEN** no grace window SHALL apply, because that deadline was never a goal the planner pursued

#### Scenario: Grace capped by next ready-by
- **WHEN** the grace window would end after the goal's next regular ready-by
- **THEN** the effective deadline SHALL be the next regular ready-by

#### Scenario: Goal rollover
- **WHEN** the goal repeats by weekdays or every_n_days
- **THEN** the missed deadline and next ready-by SHALL be resolved as today, and the continuity check SHALL use the resolved missed deadline

#### Scenario: Required energy and scheduling within the grace window
- **WHEN** a missed goal is kept active within the grace window
- **THEN** `required_kwh` SHALL be computed from live SoC as for a normal goal
- **AND** the solver SHALL schedule it in the cheapest slots within the window using the existing soft shortfall constraint

#### Scenario: Grace window setting
- **WHEN** `missed_goal_grace_hours` is configured
- **THEN** it SHALL be a per-charger `ev_chargers[]` setting defaulting to 4
- **AND** `0` SHALL disable the grace window

### Requirement: Grace requires plug continuity across the missed deadline
Grace SHALL apply only if the charger was continuously plugged in across the missed deadline or has unknown plug history. A plug session SHALL survive short unplug flickers and restarts as specified in the scenarios below.

#### Scenario: Replug after the missed deadline
- **WHEN** the plug session started after the missed deadline (car left and returned, e.g. unplugged 05:56, replugged 07:22 for a 06:00 goal)
- **THEN** no grace window SHALL apply and the goal SHALL resolve to its next regular ready-by

#### Scenario: Short unplug is a flicker
- **WHEN** the charger reads not plugged for less than `EV_UNPLUG_DEBOUNCE_MINUTES` (10) and then plugged again, including across the missed deadline
- **THEN** the plug session SHALL continue with its original start and the grace continuity check SHALL treat it as continuous
- **AND** the debounce SHALL be independent of the charger's plug-state vocabulary, and unreachable readings SHALL NOT start, advance or end it

#### Scenario: Long unplug ends the session
- **WHEN** the charger reads not plugged continuously for at least `EV_UNPLUG_DEBOUNCE_MINUTES`
- **THEN** the plug session SHALL end and a later plugged reading SHALL start a new session (e.g. unplugged 05:56, replugged 07:22 for a 06:00 goal gets no grace)

#### Scenario: Plug session survives a restart
- **WHEN** Darkstar restarts while the charger still reads plugged on its first valid reading and the saved session has no `first_unplugged_at` or one within the debounce window
- **THEN** the saved session start SHALL be restored from the EV state file (no database schema change)

#### Scenario: Saved session not restorable
- **WHEN** the saved record is missing, corrupt, in an old format, or the car was not-plugged longer than the debounce window, or the charger does not read plugged on the first valid reading
- **THEN** the plug history SHALL be unknown and the SoC-drop check below SHALL apply

#### Scenario: Persistence only on transitions
- **WHEN** repeated readings do not change the session
- **THEN** the state file SHALL NOT be written

### Requirement: Grace requires the SoC not to have dropped
When the plug history is continuous or unknown, grace SHALL apply only if the SoC has not dropped since the deadline by more than the noise threshold, since a drop indicates the car was driven.

#### Scenario: Continuous or unknown plug history, SoC dropped
- **WHEN** the plug-session start is unknown or not after the missed deadline (including a session restored after a restart) and the current SoC is lower than the SoC at the missed deadline by more than the noise threshold
- **THEN** no grace window SHALL apply (the car was driven)

#### Scenario: Continuous or unknown plug history, SoC not dropped
- **WHEN** the plug-session start is unknown or not after the missed deadline and the current SoC is equal to, higher than, or within the noise threshold below the SoC at the missed deadline
- **THEN** grace SHALL apply

#### Scenario: Continuous or unknown plug history, no deadline SoC
- **WHEN** the plug-session start is unknown or not after the missed deadline and the SoC at the missed deadline cannot be obtained
- **THEN** the grace decision SHALL behave as before this change (current plugged state only)

### Requirement: Grace respects the missed-goal tolerance
Grace SHALL apply only when the live SoC is below `target_soc_percent - missed_goal_tolerance_percent`. A tolerance of 0 disables the tolerance, and the tolerance SHALL affect only the missed-goal grace.

#### Scenario: SoC within tolerance of the target
- **WHEN** the target is 85%, `missed_goal_tolerance_percent` is 5 and the SoC is 82%
- **THEN** no grace window SHALL apply

#### Scenario: SoC beyond tolerance
- **WHEN** the target is 85%, tolerance is 5 and the SoC is 66% (and all other grace rules allow)
- **THEN** grace SHALL apply

#### Scenario: Tolerance disabled
- **WHEN** `missed_goal_tolerance_percent` is 0
- **THEN** grace SHALL apply for any SoC below the target, as before this change

#### Scenario: Tolerance scope
- **WHEN** the SoC is within tolerance of the target
- **THEN** regular goal planning (required energy, shortfall, deadlines) SHALL still target the full `target_soc_percent`; the tolerance affects only the missed-goal grace

#### Scenario: Tolerance setting
- **WHEN** `missed_goal_tolerance_percent` is configured
- **THEN** it SHALL be a per-charger `ev_chargers[]` setting in percentage points defaulting to 5, shown in the settings UI next to the grace hours
- **AND** an absent key SHALL resolve to the default without a config migration

### Requirement: Grace target is a cost-aware soft target
The grace target SHALL be a soft target whose shortfall penalty is derived from the horizon's import prices (cheapest price before the next regular deadline plus a fraction of the price spread, never below a small positive margin), so that it never forces energy into slots more expensive than the next goal's plan regardless of market price level.

#### Scenario: Grace is cost-aware
- **WHEN** a grace target is active and the next regular goal can deliver the energy at a lower price
- **THEN** the solver SHALL prefer the cheaper plan and report the unmet grace energy as shortfall at the grace penalty, not force expensive slots

#### Scenario: Grace penalty is price-relative
- **WHEN** the same relative price shape occurs on a cheap day and on an expensive day
- **THEN** the grace charging pattern SHALL be the same (energy only in slots near the cheapest price before the next regular deadline)

#### Scenario: Price spike
- **WHEN** a price spike falls inside the grace window
- **THEN** no grace energy SHALL be scheduled in the spike slots

#### Scenario: Flat prices
- **WHEN** import prices are flat (spread about zero)
- **THEN** the grace penalty SHALL exceed the flat price by the minimum margin and grace energy SHALL be scheduled

#### Scenario: Expensive now, cheap overnight
- **WHEN** the current price is 5.8 and overnight prices before the next goal are 2.4
- **THEN** no grace energy SHALL be scheduled in the expensive slots

#### Scenario: Price unknown
- **WHEN** prices for the grace window are unavailable
- **THEN** the grace target SHALL still be applied with the fixed fallback penalty and SHALL NOT raise
