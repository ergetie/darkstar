## ADDED Requirements

### Requirement: Keep-on slots render as an EV standby band

The main schedule chart SHALL render slots whose `ev_keep_on` dict contains any true flag — and whose planned `ev_charging_kw` is 0 — as a thin fixed-height "EV standby" band along the bottom of the chart, visually distinct from the EV charging bars. The band SHALL NOT encode any power value (keep-on plans no energy). It SHALL have its own legend entry, and its tooltip SHALL explain the semantics (charger switch held on after target; the vehicle draws only what it needs). Slots with genuinely planned EV power SHALL continue to render as normal EV charging bars regardless of keep-on flags.

#### Scenario: Keep-on slot renders standby band, no charging bar
- **WHEN** a schedule slot has `ev_keep_on = {"ev1": true}` and `ev_charging_kw` = 0
- **THEN** the chart SHALL render the EV standby band for that slot
- **AND** no EV charging bar SHALL be drawn for that slot

#### Scenario: Standby band carries explanation
- **WHEN** the user hovers/taps the EV standby band or reads the legend
- **THEN** a legend entry "EV standby" SHALL be present
- **AND** the tooltip SHALL state that the charger switch is held on after target and the car draws only what it needs

#### Scenario: Planned charging takes precedence over the band
- **WHEN** a slot has both planned EV power (`ev_charging_kw > 0`) and a keep-on flag
- **THEN** the normal EV charging bar SHALL be rendered for that slot

#### Scenario: Schedules without keep-on data render unchanged
- **WHEN** a schedule slot has no `ev_keep_on` field
- **THEN** the chart SHALL render exactly as before this change, with no standby band
