# Dashboard EV Display

## Purpose

Dashboard display of energy resources and EV charging metrics with conditional rendering based on system configuration.
## Requirements
### Requirement: Dashboard Energy Resources card renders metrics conditionally
The Dashboard Energy Resources card SHALL display metrics conditionally based on system `has_*` configuration flags. Metrics SHALL only appear when the corresponding feature is enabled.

| Metric | Condition |
|--------|-----------|
| Solar Production | `has_solar: true` |
| Battery Charge / Discharge | `has_battery: true` |
| Water Heating | `has_water_heater: true` |
| EV Charging | `has_ev_charger: true` |

The "House Load" metric SHALL always be displayed.

When `has_ev_charger` is true, the card SHALL expose a "Metrics | EV" tab switch. The "Metrics" tab SHALL show the resource metrics (including an at-a-glance EV summary line); the "EV" tab SHALL show per-charger goal controls and progress as defined in the `ev-dashboard-card` capability. The active tab SHALL be persisted in `localStorage`. When `has_ev_charger` is false (or no chargers are configured), the card SHALL render the Metrics view **regardless of any persisted tab value** — a stale `localStorage` preference for the EV tab SHALL never lock the user out of the Metrics view.

#### Scenario: Full configuration (all features enabled)
- **WHEN** the Dashboard loads with all `has_*` flags `true`
- **THEN** the Metrics tab SHALL display Solar, Battery, Water, EV summary, and House Load
- **AND** an "EV" tab SHALL be available with per-charger controls

#### Scenario: Minimal configuration (no optional features)
- **WHEN** the Dashboard loads with all optional `has_*` flags `false`
- **THEN** only "House Load" is displayed
- **AND** no EV tab is shown

#### Scenario: EV tab preference outlives the charger
- **WHEN** the user last used the EV tab and later disables/removes all EV chargers
- **THEN** the card SHALL render the Metrics view on next load (not an empty EV view with no way back)

#### Scenario: EV-only conditional example
- **WHEN** `has_ev_charger: true`
- **THEN** the Metrics tab SHALL show today's total EV energy as a summary line
- **AND** the EV tab SHALL show per-charger goal controls and charging progress
- **AND** "House Load" reflects base load (EV excluded, as stored in DB)

### Requirement: Frontend fetches config once at Dashboard initialization
The Dashboard frontend SHALL fetch the system configuration once on initialization to determine which metrics to display.

#### Scenario: Frontend reads has_* flags
- **WHEN** the Dashboard initializes
- **THEN** the frontend fetches the system configuration
- **AND** reads `has_solar`, `has_battery`, `has_water_heater`, and `has_ev_charger`
- **AND** renders only the applicable metric fields
