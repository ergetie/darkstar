## MODIFIED Requirements

### Requirement: Settings UI section
The frontend SHALL provide a load-balancing settings section with a global enable toggle, the fuse rating, per-phase sensor pickers (labeled to indicate either current or power sensors are accepted), anti-flap tuning fields, a nominal voltage field, a notifications toggle ("Notify on load balancer interventions", bound to `notify_interventions`), and a single reorderable **give-way list** replacing the previous two labeled groups:

- The list SHALL be ordered top-to-bottom, top gives way first, reorderable by drag with always-available up/down button fallback, and SHALL show no numeric priority fields.
- Every `type: current` EV charger SHALL appear in the list automatically (never user-added or user-removed); its row SHALL show name and configured phases read-only, a plain-language capability line derived from its configuration (e.g. "Throttle 16 → 6 A, then pause"), and a link to the EV tab where its settings live. Only its position SHALL be editable here.
- Shed loads (water heater, custom entity, `type: binary` EV charger) SHALL be addable/removable in the list, each with device, phases, and a capability line ("Switch off"). The EV charger picker for shed entries SHALL offer only `type: binary` chargers.
- The section copy SHALL state the top-down give-way rule in plain language and that phase assignment for on/off loads must match the physical installation.
- The reorderable-list control SHALL be implemented as a reusable component suitable for other ordered lists (e.g. a future excess-PV sink priority list).

The settings tab SHALL always be visible in navigation, regardless of `system.has_ev_charger` or `system.has_water_heater` — it SHALL NOT be conditionally hidden the way hardware-specific tabs (Solar, Battery, EV, Heating) are, since a `custom_entity` shed load requires no system flag at all. When the give-way list is empty — no `type: current` EV charger auto-included and no `loads[]` entries configured, regardless of the `has_ev_charger`/`has_water_heater` flags — the give-way section SHALL display an inline explanatory message pointing to the ways to populate it (a dynamically-throttled EV charger configured in the EV tab, or a water heater/custom entity added directly here) instead of a bare empty list. This message SHALL NOT block use of the enable toggle, fuse rating, or sensor fields.

When `load_balancing.enabled` is true and `executor.interval_seconds` exceeds 15, the section SHALL display a persistent inline warning naming both keys and the recommended tick. If any phase resolves to power-sensor mode, the settings UI SHALL show all three per-phase voltage entity fields together as one group (not conditionally per individual phase), each optional and independently falling back to the nominal voltage if left blank.

In the EV chargers settings tab, the current-control load type option SHALL be labeled "Dynamic" (config value unchanged), and while selected the UI SHALL display its consequences in plain language: the planner sets the charge current per slot, the charger is automatically included in the load-balancing give-way list (with a link to that tab), and it becomes eligible for future PV-surplus charging. When a `type: current` charger has no SoC sensor configured, the EV tab SHALL show an inline warning that Darkstar cannot track its charging progress.

#### Scenario: User enables the feature from the UI
- **WHEN** the user fills in fuse rating, sensors, and one give-way entry, then enables the toggle
- **THEN** the config SHALL be persisted through the existing config write path and validation feedback shown inline

#### Scenario: Power sensor reveals voltage fields
- **WHEN** the user selects a power-reporting entity for any of the three phase sensor fields
- **THEN** the settings UI SHALL show all three "Grid voltage sensor" fields together
- **AND** each SHALL be optional, independently

#### Scenario: User reorders a shed load above a charger
- **WHEN** the user drags the water heater entry above a charger entry and saves
- **THEN** `give_way_order` SHALL persist that order
- **AND** the balancer SHALL shed the water heater before throttling that charger (per `phase-load-balancing`)

#### Scenario: Charger rows are managed from the EV tab
- **WHEN** the user changes a charger's type from "Dynamic current (adjustable amps)" to "Binary (On/Off)" in the EV tab
- **THEN** the charger SHALL disappear from the give-way list's automatic entries
- **AND** it SHALL become offerable as a shed entry

#### Scenario: Choosing dynamic current explains its consequences
- **WHEN** the user selects "Dynamic current (adjustable amps)" for a charger in the EV tab
- **THEN** the UI SHALL display the consequence list (planner-controlled amps, automatic load balancing membership, PV-surplus eligibility) at the point of choice

#### Scenario: Slow tick shows a persistent warning in the section
- **WHEN** `load_balancing.enabled` is true and `executor.interval_seconds` is 60
- **THEN** the load-balancing settings section SHALL display an inline warning recommending ≤ 15 s

#### Scenario: Tab visible with no EV charger and no water heater
- **WHEN** `system.has_ev_charger` is false and `system.has_water_heater` is false
- **THEN** the Load Balancing settings tab SHALL still appear in navigation

#### Scenario: Empty state explains prerequisites
- **WHEN** the give-way list has no `type: current` EV charger and `load_balancing.loads[]` is empty (regardless of `system.has_water_heater`/`system.has_ev_charger`)
- **THEN** the section SHALL display a message explaining the give-way list can be populated by a dynamic EV charger, a water heater, or a custom entity added here
- **AND** the enable toggle, fuse rating, and sensor fields SHALL remain usable

#### Scenario: Give-way list populated by a custom entity alone
- **WHEN** the system has no EV charger and no water heater, but the user adds a `custom_entity` shed load to `load_balancing.loads[]`
- **THEN** the empty-state message SHALL NOT be shown
- **AND** the give-way list SHALL show that entry
