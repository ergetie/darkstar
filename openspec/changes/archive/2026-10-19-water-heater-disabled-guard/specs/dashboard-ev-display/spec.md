## ADDED Requirements

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
