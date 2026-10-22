# Spec Delta

## MODIFIED Requirements

### Requirement: Load Balancer tab shows a compact live status view
The Load Balancer tab SHALL display: per-phase current bars for L1/L2/L3 versus the main fuse rating with the same color coding as the Executor page's card (normal / near-limit / over-limit), the current balancer state with its reason text, and compact entries for currently throttled EV chargers and currently shed loads. Idle chargers/loads and routine scheduled-off or startup-held loads SHALL be omitted. Shed warnings SHALL use explicit active intervention status rather than the off command.

#### Scenario: Live phase bars
- **WHEN** the Load Balancer tab is active and a `live_metrics` update arrives
- **THEN** the L1/L2/L3 bars reflect the new currents against the fuse rating without a page refresh

#### Scenario: Active intervention details
- **WHEN** the balancer is throttling an EV charger or shedding a load
- **THEN** the affected charger/load appears with its status, and idle devices are not listed

#### Scenario: Live updates and Executor link
- **WHEN** the Load Balancer tab is displayed
- **THEN** the view SHALL update live from the same data feed as the Executor page card (initial REST fetch plus `live_metrics` WebSocket updates)
- **AND** it SHALL contain a link to the Executor page for full detail
- **AND** the tab SHALL NOT contain any bypass or override control

#### Scenario: Routine off state does not draw intervention attention
- **WHEN** a load is commanded off by its schedule or startup gates without an actual shedding intervention and no other intervention exists
- **THEN** the card SHALL NOT show a red Shed entry or a Shedding Loads heading
- **AND** it SHALL NOT auto-switch tabs or show an intervention warning dot

#### Scenario: Actual shedding remains visible during recovery
- **WHEN** an actual protection-cut load is awaiting safe restoration with demand still on
- **THEN** its Shed entry and aggregate intervention attention SHALL remain visible until restoration or explicit off demand ends the intervention

### Requirement: Executor page remains unchanged
The Executor page's `LoadBalancerStatusCard` SHALL retain its existing layout and controls. Its shedding entries and heading SHALL use the same explicit active-intervention status as the compact Dashboard card, excluding routine scheduled-off and startup-held loads.

#### Scenario: Executor page after the change
- **WHEN** the user opens the Executor page
- **THEN** the load-balancer card retains its layout and controls while reporting shedding only for active shedding interventions

#### Scenario: Compact and detail views agree
- **WHEN** a status update contains both a routine off load and an actively shed load
- **THEN** both cards SHALL list only the actively shed load as shed
- **AND** the routine off load SHALL remain excluded even if its off command is true
