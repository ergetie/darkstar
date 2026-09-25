## ADDED Requirements

### Requirement: Power Flow House node shows residual base load
The Power Flow card SHALL show House power as gross whole-home power minus the total EV power when the EV node is enabled (`system.has_ev_charger`) and minus the total water-heater power when the water node is enabled (`system.has_water_heater`). The totals are the backend-provided `ev_kw` and `water_kw`, which already exclude individually disabled devices. Missing values SHALL count as 0, and the displayed House value SHALL be clamped to zero or greater. The gross total-load measurement SHALL retain its existing meaning outside this presentation.

#### Scenario: EV and water heater are separate loads
- **WHEN** gross whole-home power is 8.0 kW, enabled EV chargers draw 6.9 kW total, and enabled water heaters draw 0.2 kW total
- **THEN** the House node SHALL show 0.9 kW
- **AND** the EV and water nodes SHALL continue to show 6.9 kW and 0.2 kW

#### Scenario: Multiple managed devices are active
- **WHEN** several EV chargers or water heaters are drawing power
- **THEN** the House value SHALL subtract the backend total (`ev_kw`, `water_kw`) once, not each device again

#### Scenario: Managed load node is disabled
- **WHEN** the EV node or the water node is disabled in system configuration
- **THEN** that node's power SHALL NOT be subtracted from the House value

#### Scenario: Managed power exceeds gross load
- **WHEN** the sum of separately displayed EV and water-heater power exceeds the gross load reading
- **THEN** the House node SHALL show 0.0 kW
- **AND** the raw gross load reading SHALL remain unchanged
