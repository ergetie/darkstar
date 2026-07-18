# PowerFlow Load-Balancer Tab

## Purpose

TBD

## Requirements

### Requirement: PowerFlow card gains a Load Balancer tab when load balancing is enabled
The Dashboard's PowerFlow card SHALL render a tab strip with **Flow** and **Load Balancer** tabs, styled like the Energy Resources card's tabs, when the load balancer reports itself enabled (`enabled` true and state not `disabled`). When load balancing is disabled or unconfigured, the card SHALL render exactly as it does today: the flow view only, with no tab strip.

#### Scenario: Load balancing enabled
- **WHEN** the load-balancer status reports enabled
- **THEN** the PowerFlow card shows Flow and Load Balancer tabs, with Flow content unchanged from today

#### Scenario: Load balancing disabled
- **WHEN** the load-balancer status reports disabled or is unconfigured
- **THEN** the card shows only the flow view with no tab strip, visually identical to the current card

### Requirement: Load Balancer tab shows a compact live status view
The Load Balancer tab SHALL display: per-phase current bars for L1/L2/L3 versus the main fuse rating with the same color coding as the Executor page's card (normal / near-limit / over-limit), the current balancer state with its reason text, and compact entries for currently throttled EV chargers and currently shed loads. Idle chargers/loads SHALL be omitted. The view SHALL update live from the same data feed as the Executor page card (initial REST fetch plus `live_metrics` WebSocket updates) and SHALL contain a link to the Executor page for full detail. The tab SHALL NOT contain any bypass or override control.

#### Scenario: Live phase bars
- **WHEN** the Load Balancer tab is active and a `live_metrics` update arrives
- **THEN** the L1/L2/L3 bars reflect the new currents against the fuse rating without a page refresh

#### Scenario: Active intervention details
- **WHEN** the balancer is throttling an EV charger or shedding a load
- **THEN** the affected charger/load appears with its status, and idle devices are not listed

### Requirement: Card auto-switches to the Load Balancer tab once per intervention episode
When the balancer state transitions from a non-intervening state (idle, paused, disabled) into an intervening state (throttling, shedding, stale-sensor fallback), the card SHALL switch the active tab to Load Balancer once, at that transition. Transitions between intervening states SHALL NOT re-trigger the switch. If the user manually switches away during an ongoing episode, the card SHALL NOT force the tab again until a new episode begins. The auto-switch SHALL NOT overwrite the user's persisted tab preference.

#### Scenario: Intervention starts
- **WHEN** the state changes from idle to shedding while the Flow tab is active
- **THEN** the card switches to the Load Balancer tab

#### Scenario: User switches back mid-episode
- **WHEN** the user returns to the Flow tab while shedding is still active, and the state later changes to throttling
- **THEN** the card stays on the Flow tab

#### Scenario: New episode after recovery
- **WHEN** the balancer returns to idle and later starts throttling again
- **THEN** the card auto-switches once more

### Requirement: Warning indicator while an intervention is active and unseen
While the balancer is in an intervening state and the Load Balancer tab is not the active tab, the Load Balancer tab label SHALL display a warning dot. The dot SHALL disappear when the intervention ends or the tab is viewed.

#### Scenario: Dot shown on Flow tab during intervention
- **WHEN** throttling is active and the user is on the Flow tab
- **THEN** the Load Balancer tab label shows a warning dot

#### Scenario: Dot absent when idle
- **WHEN** the balancer is idle
- **THEN** no warning dot is shown

### Requirement: Tab selection persists like the Resources card
The selected tab SHALL persist across page loads via localStorage (using the same pattern as the Resources card, key `darkstar-powerflow-tab`). A persisted Load Balancer selection SHALL fall back to the Flow view whenever the Load Balancer tab is unavailable.

#### Scenario: Persisted tab restored
- **WHEN** the user selected the Load Balancer tab and reloads the Dashboard with load balancing enabled
- **THEN** the Load Balancer tab is active

#### Scenario: Persisted tab unavailable
- **WHEN** localStorage holds the Load Balancer tab but load balancing is now disabled
- **THEN** the flow view renders with no tab strip and no errors

### Requirement: Executor page remains unchanged
The Executor page's `LoadBalancerStatusCard` SHALL remain functionally and visually unchanged by this feature. Shared helpers MAY be imported from it, but its rendered output and behavior SHALL NOT change.

#### Scenario: Executor page after the change
- **WHEN** the user opens the Executor page
- **THEN** the load-balancer card renders and behaves exactly as before
