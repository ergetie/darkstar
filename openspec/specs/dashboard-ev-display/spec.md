# Dashboard EV Display

## Purpose

Dashboard display of energy resources and EV charging metrics with conditional rendering based on system configuration.
## Requirements
### Requirement: Dashboard Energy Resources card renders metrics conditionally
The Dashboard Energy Resources card SHALL display metrics conditionally based on system `has_*` flags, only when the corresponding feature is enabled. The "House Load" metric SHALL always be displayed, with actual and average values both representing base household load excluding EV charging and water-heater consumption. When `has_ev_charger` is true the card SHALL expose a "Metrics | EV" tab switch, and when false it SHALL render the Metrics view regardless of any persisted tab value.

#### Scenario: Metric visibility conditions
- **WHEN** the card renders
- **THEN** Solar Production appears only when `has_solar: true`
- **AND** Battery Charge / Discharge appears only when `has_battery: true`
- **AND** Water Heating appears only when `has_water_heater: true`
- **AND** EV Charging appears only when `has_ev_charger: true`

#### Scenario: House Load average definition
- **WHEN** the card shows the House Load average
- **THEN** it is `base_load_avg_daily_kwh` from `GET /api/energy/today`: the base-load total of the last 96 completed 15-minute slots, scaled to 96 slots, and `null` when fewer than 87 slots are recorded
- **AND** it is not derived from the gross whole-home power sensor
- **AND** it is a full-day figure shown next to today's so-far actual

#### Scenario: EV tab switch behavior
- **WHEN** `has_ev_charger` is true
- **THEN** the "Metrics" tab shows the resource metrics including an at-a-glance EV summary line
- **AND** the "EV" tab shows per-charger goal controls and progress as defined in the `ev-dashboard-card` capability
- **AND** the active tab is persisted in `localStorage`

#### Scenario: Stale tab preference ignored without chargers
- **WHEN** `has_ev_charger` is false or no chargers are configured
- **THEN** the card renders the Metrics view regardless of any persisted tab value
- **AND** a stale `localStorage` EV preference never locks the user out of the Metrics view

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
- **AND** both House Load actual and average SHALL reflect base load with EV charging and enabled water-heater consumption excluded

#### Scenario: House Load actual and average use the same basis
- **WHEN** the Energy Resources card displays today's House Load and its average comparison
- **THEN** both values SHALL use stored base-load observations that exclude enabled EV and water-heater consumption
- **AND** the average SHALL use the 96 completed 15-minute slots before the current slot

#### Scenario: Insufficient base-load history
- **WHEN** fewer than 87 of the last 96 completed slots have recorded base load
- **THEN** the API SHALL return `base_load_avg_daily_kwh: null`
- **AND** the card SHALL show its unavailable value, not 0 and not a gross-sensor average

### Requirement: Frontend fetches config once at Dashboard initialization
The Dashboard frontend SHALL fetch the system configuration once on initialization to determine which metrics to display.

#### Scenario: Frontend reads has_* flags
- **WHEN** the Dashboard initializes
- **THEN** the frontend fetches the system configuration
- **AND** reads `has_solar`, `has_battery`, `has_water_heater`, and `has_ev_charger`
- **AND** renders only the applicable metric fields

### Requirement: Water UI is hidden when has_water_heater is false
When `system.has_water_heater` is `false`, the Dashboard SHALL hide every water heating control, banner, node and planned/future chart series. Past water history (recorded actuals and past slots) SHALL stay visible in charts and history views. The flag defaults to `true` when absent. The Settings Heating tab SHALL stay reachable with a disabled notice.

#### Scenario: Flag off hides water controls
- **GIVEN** `system.has_water_heater` is `false` and `water_heaters[]` is non-empty
- **WHEN** the Dashboard renders
- **THEN** no PowerFlow water node, Energy Resources water row, water boost button, heater selector, vacation toggle, water boost banner, or planned/future water chart series is rendered, while water series for completed slots remain visible

#### Scenario: Heating tab stays reachable
- **GIVEN** the flag is `false`
- **WHEN** the user opens Settings > Heating
- **THEN** the tab renders its content with a "disabled" notice
