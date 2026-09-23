## MODIFIED Requirements

### Requirement: EV charger is throttled first using per-phase feedback
When any phase used by a charging EV has negative headroom, the balancer SHALL reduce that charger's ampere setpoint by at least the magnitude of the worst negative headroom, immediately in the same tick, clamped to the charger's minimum current. The reduction, any hold, and the relief the charger contributes to the shared headroom pool SHALL be computed from the charger's effective baseline (see `ev-measured-draw`) rather than the last commanded setpoint; when no measurement exists the effective baseline equals the commanded setpoint. When headroom is positive, the balancer MAY raise the setpoint toward the planner-derived target, never above `min(charger max_current_a, planner-derived amps)`.

Give-way ordering across ALL balanced loads SHALL be governed by the single ordered list `load_balancing.give_way_order` (see the `load-balancing-settings` capability): the balancer SHALL process entries top-down, and an entry SHALL only be asked to give way once every entry above it that draws on the overloaded phase(s) is exhausted (a charger entry is exhausted when paused; a shed entry when shed). A charger entry gives way by immediate setpoint reduction toward its `min_current_a`. When multiple entries could give way in the same tick, list position — not device kind — SHALL decide the order. A household whose order matches the migrated default (all current-type chargers before all shed loads) SHALL behave exactly as the previous two-tier system, and a household with a single dynamically-throttled charger and no shed loads SHALL behave exactly as before this requirement was introduced.

#### Scenario: Stove turns on while EV charges
- **WHEN** the EV charges 3-phase at 16 A and a new house load drives L1 headroom to −6 A
- **THEN** the balancer SHALL reduce the EV setpoint to 10 A or lower in the same tick

#### Scenario: Car draws below its setpoint during an overload
- **WHEN** the EV has a settled 16 A setpoint, measures 10 A draw, and L1 headroom is −4 A
- **THEN** the balancer SHALL reduce the setpoint to 6 A or lower in the same tick
- **AND** the relief folded into the pool for later entries SHALL be computed from 10 A, not 16 A

#### Scenario: Balancer never exceeds the planned charging level
- **WHEN** the planner-derived target for the current slot is 10 A and all phases have ample headroom
- **THEN** the balancer SHALL NOT raise the setpoint above 10 A

#### Scenario: Two chargers share an overloaded phase, higher-listed gives way first
- **WHEN** charger A is listed above charger B in `give_way_order`, and both draw on L1, which has −10 A headroom
- **THEN** the balancer SHALL reduce charger A toward its floor first, using as much of the −10 A deficit as charger A's headroom down to `min_current_a` can absorb
- **AND** charger B SHALL only be reduced if charger A being fully exhausted is insufficient to resolve the remaining deficit

#### Scenario: Shed load ordered above a charger gives way before the charger slows
- **WHEN** `give_way_order` lists the water heater (shed entry, declared on L2) above charger A (also on L2), and L2 headroom goes negative while the water heater is heating
- **THEN** the balancer SHALL shed the water heater first
- **AND** charger A's setpoint SHALL only be reduced if the deficit persists after the water heater is shed

#### Scenario: Single dynamically-throttled charger is unaffected by ordering
- **WHEN** only one `type: current` EV charger is configured and no shed loads exist
- **THEN** its position in `give_way_order` SHALL have no observable effect on balancer behavior
