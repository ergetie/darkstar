## MODIFIED Requirements

### Requirement: Dashboard Energy Resources card renders metrics conditionally
The Dashboard Energy Resources card SHALL display metrics conditionally based on system `has_*` configuration flags. Metrics SHALL only appear when the corresponding feature is enabled.

| Metric | Condition |
|--------|-----------|
| Solar Production | `has_solar: true` |
| Battery Charge / Discharge | `has_battery: true` |
| Water Heating | `has_water_heater: true` |
| EV Charging | `has_ev_charger: true` |

The "House Load" metric SHALL always be displayed.

When `has_ev_charger` is true, the card SHALL expose a "Metrics | EV" tab switch. The "Metrics" tab SHALL show the resource metrics (including an at-a-glance EV summary line); the "EV" tab SHALL show per-charger goal controls and progress as defined in the `ev-dashboard-card` capability. The active tab SHALL be persisted in `localStorage`.

#### Scenario: Full configuration (all features enabled)
- **WHEN** the Dashboard loads with all `has_*` flags `true`
- **THEN** the Metrics tab SHALL display Solar, Battery, Water, EV summary, and House Load
- **AND** an "EV" tab SHALL be available with per-charger controls

#### Scenario: Minimal configuration (no optional features)
- **WHEN** the Dashboard loads with all optional `has_*` flags `false`
- **THEN** only "House Load" is displayed
- **AND** no EV tab is shown

#### Scenario: EV-only conditional example
- **WHEN** `has_ev_charger: true`
- **THEN** the Metrics tab SHALL show today's total EV energy as a summary line
- **AND** the EV tab SHALL show per-charger goal controls and charging progress
- **AND** "House Load" reflects base load (EV excluded, as stored in DB)
