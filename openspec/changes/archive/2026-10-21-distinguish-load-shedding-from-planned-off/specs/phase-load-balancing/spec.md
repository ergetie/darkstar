# Spec Delta

## ADDED Requirements

### Requirement: Off commands are distinct from shedding interventions
The balancer SHALL distinguish an off command from an active shedding intervention. Only an actual fuse-protection cut with demand not explicitly off SHALL establish a shedding intervention. Scheduled-off commands and conservative startup holds SHALL NOT establish one. Reporting changes SHALL preserve physical off dispatch and all existing switching and restore safety gates.

#### Scenario: Scheduled off at healthy currents
- **WHEN** a managed load is scheduled off and its minimum on time allows the off command
- **THEN** the executor SHALL command it off without reporting an active shedding intervention or sending a shedding notification
- **AND** its off timer SHALL remain available for future minimum-off and restore checks

#### Scenario: Conservative startup hold
- **WHEN** a managed load first appears with an off or unknown measured state, including when its schedule requests on
- **THEN** its conservative off command SHALL obey the existing startup and restore gates
- **AND** startup alone SHALL NOT report shedding or notify, even while waiting for room, cooling or minimum off time

#### Scenario: Actual overload cut
- **WHEN** the fuse-protection trigger and give-way order cause an on/off load to be cut and its demand is not explicitly off
- **THEN** the load SHALL report an active shedding intervention with its overload reason
- **AND** the existing physical off command SHALL be applied immediately

#### Scenario: Unknown demand does not disable protection
- **WHEN** an on/off load has no explicit scheduled demand and is cut for fuse protection
- **THEN** it SHALL report an active shedding intervention and retain existing safe restore behavior
- **AND** missing scheduled demand alone SHALL NOT create an intervention

#### Scenario: Planned stop held by minimum on time
- **WHEN** a plan requests off but minimum on time temporarily defers that stop
- **THEN** the plan request alone SHALL NOT create an active shedding intervention
- **AND** an actual overload cut SHALL still bypass minimum on time without claiming that explicitly off demand was suppressed

### Requirement: Shedding reporting follows the intervention lifecycle
An active shedding intervention SHALL remain reported while a protection-cut load with demand not explicitly off awaits safe restoration. It SHALL clear on restoration or explicit off demand, without resetting physical switching clocks. Disabled balancing and removed loads SHALL NOT retain active intervention status. Aggregate shedding state SHALL depend on active interventions rather than off commands.

#### Scenario: Safe recovery is still pending
- **WHEN** a protection-cut load is still requested on and currents recover but minimum off time, resume delay, cooling, reverse ordering or the room gate prevents restore
- **THEN** its intervention SHALL remain active with the applicable waiting reason
- **AND** it SHALL clear when restoration is granted

#### Scenario: Schedule ends while protection-cut load stays off
- **WHEN** the schedule changes a protection-cut load's demand to off
- **THEN** its active intervention SHALL clear in that tick
- **AND** its original physical off timestamp and minimum-off protection SHALL be preserved
- **AND** a later scheduled-on request SHALL NOT revive the old intervention without a new actual protection cut

#### Scenario: Only planned-off loads exist
- **WHEN** all off commands are routine plan or startup states and no other entry is intervening
- **THEN** aggregate state SHALL be idle rather than shedding

#### Scenario: Other interventions remain visible
- **WHEN** a routine off load coexists with EV throttling, battery limiting, a pause, stale fallback or another actively shed load
- **THEN** the routine off load SHALL NOT mask or create an intervention
- **AND** the existing aggregate precedence SHALL apply using actual shedding interventions

#### Scenario: Notification edges and diagnostics are truthful
- **WHEN** intervention notifications are enabled and a load enters actual shedding
- **THEN** exactly one shedding notification SHALL be sent for that transition
- **AND** unchanged ticks, planned stops and startup holds SHALL NOT send shedding notifications
- **AND** decision logs and diagnostic snapshots SHALL distinguish off-command transitions from shedding interventions without claiming a physical restore when only intervention status clears

#### Scenario: Removed or disabled entries
- **WHEN** a load is removed from balancing or balancing is disabled
- **THEN** it SHALL no longer contribute active shedding status or stale notification state
- **AND** a future genuine intervention after re-enabling SHALL be eligible for its own notification
