## MODIFIED Requirements

### Requirement: Dashboard Energy Resources card renders metrics conditionally
The Dashboard Energy Resources card SHALL display metrics conditionally based on system `has_*` configuration flags. Metrics SHALL only appear when the corresponding feature is enabled.

| Metric | Condition |
|--------|-----------|
| Solar Production | `has_solar: true` |
| Battery Charge / Discharge | `has_battery: true` |
| Water Heating | `has_water_heater: true` |
| EV Charging | `has_ev_charger: true` |

The "House Load" metric SHALL always be displayed. Its actual and average values SHALL both represent base household load, excluding enabled EV charging and water-heater consumption that are tracked separately. The average SHALL be `base_load_avg_daily_kwh` from `GET /api/energy/today`: the base-load total of the last 96 completed 15-minute slots, scaled to 96 slots, and `null` when fewer than 87 slots are recorded. It SHALL NOT be derived from the gross whole-home power sensor. It is a full-day figure shown next to today's so-far actual.

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
- **AND** both House Load actual and average SHALL reflect base load with EV charging and enabled water-heater consumption excluded

#### Scenario: House Load actual and average use the same basis
- **WHEN** the Energy Resources card displays today's House Load and its average comparison
- **THEN** both values SHALL use stored base-load observations that exclude enabled EV and water-heater consumption
- **AND** the average SHALL use the 96 completed 15-minute slots before the current slot

#### Scenario: Insufficient base-load history
- **WHEN** fewer than 87 of the last 96 completed slots have recorded base load
- **THEN** the API SHALL return `base_load_avg_daily_kwh: null`
- **AND** the card SHALL show its unavailable value, not 0 and not a gross-sensor average
